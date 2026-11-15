import asyncio
import math
import re
from collections import Counter
from time import perf_counter

from .catalog import (
    DEFAULT_TOOLS,
    DEPENDENCIES,
    SERVICES,
    SKILLS,
    TOOLS_BY_SERVICE,
    label,
    stable_id,
    visible_signals,
)

GRAPH_MODES = {"graph", "learned"}
MODES = {"graph", "learned", "flat", "preload"}
CANDIDATE_LIMIT = 3

SIGNAL_AFFINITY = {
    "error_counter": {"inspect_errors": 3, "trace_failures": 3, "sample_logs": 1},
    "latency": {"inspect_latency": 4},
    "health": {"dependency_health": 6, "inspect_latency": 1, "sample_logs": 1},
    "deploy": {"list_deployments": 2},
}


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def flat_catalog(definitions):
    records = []
    for service, (name, owner, aliases) in SERVICES.items():
        for tool in TOOLS_BY_SERVICE.get(service, DEFAULT_TOOLS):
            skill, instructions, tags, priority = SKILLS[tool]
            relation_text = " ".join(
                f"{label(source)} depends on {' '.join(label(target) for target in targets)}"
                for source, targets in DEPENDENCIES.items()
                if service in (source, *targets)
            )
            records.append(
                {
                    "service": service,
                    "service_name": name,
                    "owner": owner,
                    "skill": skill,
                    "instructions": instructions,
                    "tags": tags,
                    "priority": priority,
                    "tool": tool,
                    "definition": definitions[tool],
                    "terms": words(
                        " ".join(
                            (
                                name,
                                owner,
                                *aliases,
                                skill,
                                instructions,
                                tags,
                                definitions[tool]["description"],
                                relation_text,
                            )
                        )
                    ),
                }
            )
    return records


def bm25(query, records):
    query_terms = set(words(query))
    term_frequency = [Counter(record["terms"]) for record in records]
    document_frequency = Counter(term for record in term_frequency for term in record)
    average_length = sum(len(record["terms"]) for record in records) / len(records)
    count = len(records)

    def score(record, terms):
        slope = 1.2 * (0.25 + 0.75 * len(record["terms"]) / average_length)
        return sum(
            math.log(
                1
                + (count - document_frequency[word] + 0.5)
                / (document_frequency[word] + 0.5)
            )
            * (terms[word] * 2.2)
            / (terms[word] + slope)
            for word in query_terms
            if terms[word]
        )

    return [
        {**record, "score": score(record, terms), "confirmations": 0}
        for record, terms in zip(records, term_frequency, strict=True)
    ]


def supported_signals(record, signals):
    return [
        signal
        for signal in signals
        if signal["service"] == record["service"]
        and SIGNAL_AFFINITY.get(signal["kind"], {}).get(record["tool"], 0) > 0
    ]


def shortlist(ranked, signals, mode):
    if mode == "preload":
        return ranked
    candidates = ranked[:CANDIDATE_LIMIT]
    if mode != "learned" or len(candidates) < 2:
        return candidates
    strongest, next_best = candidates[:2]
    support = supported_signals(strongest, signals)
    # Scope the learned shortcut to repeated outcomes with contemporaneous
    # evidence. The model still decides whether the check is justified.
    if (
        strongest["confirmations"] >= 2
        and strongest["score"] - next_best["score"] >= 2
        and support
        and max(signal["severity"] for signal in support)
        == max(signal["severity"] for signal in signals)
    ):
        return [strongest]
    return candidates


def graph_rank(replay, records, signals, confirmations):
    ranked = []
    for record in records:
        relevant = [
            min(signal["severity"], 16)
            + SIGNAL_AFFINITY.get(signal["kind"], {}).get(record["tool"], -5)
            for signal in signals
            if signal["service"] == record["service"]
        ]
        best_signal = max(relevant, default=0)
        matched_words = len(set(words(replay["alert"])) & set(words(record["tags"])))
        confirmed = confirmations.get(record["skill_id"], 0)
        score = (
            best_signal
            + record["priority"]
            + min(2, matched_words)
            + min(3, confirmed) * 1.5
        )
        ranked.append({**record, "score": score, "confirmations": confirmed})
    return ranked


class TriageEngine:
    def __init__(self, graph, decider, mcp):
        self.graph = graph
        self.decider = decider
        self.mcp = mcp
        self.flat_actions = flat_catalog(mcp.definitions)

    async def run(
        self,
        replay,
        mode="graph",
        feedback_run="submission",
        checkpoint=3,
        bookmark=None,
        service_hint=None,
        alert=None,
    ):
        if mode not in MODES:
            raise ValueError(f"Unknown retrieval mode {mode}")
        started = perf_counter()
        db_calls = 0

        async def database(operation, *args):
            nonlocal db_calls
            db_calls += 2 if operation == self.graph.observations else 1
            return await operation(*args)

        # The observation time and tool data remain pinned to the replay for all modes.
        case = {**replay, "alert": alert or replay["alert"]}
        anchor = None
        if mode in GRAPH_MODES:
            anchor = await database(self.graph.resolve, service_hint or case["service"])
            if anchor is not None:
                case["service"] = anchor["key"]

        if mode in GRAPH_MODES and anchor:
            candidates, (signals, deploys) = await asyncio.gather(
                database(self.graph.actions, anchor),
                database(self.graph.observations, case),
            )
            confirmations = (
                await database(
                    self.graph.feedback,
                    case,
                    feedback_run,
                    checkpoint,
                    bookmark,
                )
                if mode == "learned"
                else {}
            )
            ranked = graph_rank(case, candidates, signals, confirmations)
        elif mode in GRAPH_MODES:
            signals, deploys, ranked = [], [], []
        else:
            signals = visible_signals(case)
            deploys = [
                {
                    "service": deploy["service"],
                    "deploy": deploy["key"],
                    "at": deploy["at"],
                }
                for deploy in case["deployments"]
                if deploy["environment"] == case["environment"]
                and 0 <= case["at"] - deploy["at"] <= 30
            ]
            text = " ".join(
                (
                    case["alert"],
                    label(case["service"]),
                    case["symptom"],
                    *(signal["text"] for signal in signals),
                )
            )
            ranked = bm25(text, self.flat_actions)

        ranked.sort(
            key=lambda entry: (-entry["score"], entry["service"], entry["tool"])
        )
        selected = shortlist(ranked, signals, mode)
        definitions = {}
        actions = []
        for action_id, candidate in enumerate(selected, start=1):
            deployment = next(
                (
                    item["deploy"]
                    for item in deploys
                    if item["service"] == candidate["service"]
                ),
                None,
            )
            candidate_args = {
                "case_id": case["id"],
                "service": candidate["service"],
                "observed_at": case["at"],
            }
            actions.append(
                {
                    "id": action_id,
                    "service": candidate["service"],
                    "service_name": candidate["service_name"],
                    "tool": candidate["tool"],
                    "skill": candidate["skill"],
                    "instructions": candidate["instructions"],
                    "deploy": deployment,
                    "matched_observations": sorted(
                        {
                            signal["kind"]
                            for signal in supported_signals(candidate, signals)
                        }
                    ),
                    "confirmations": candidate["confirmations"],
                    "arguments": candidate_args,
                }
            )
            definitions[candidate["tool"]] = candidate["definition"]

        decision, metrics = await self.decider.choose(
            case["alert"], signals, actions, definitions
        )
        if not signals:
            definitions = {}
        result = {
            "case": case["id"],
            "mode": mode,
            "status": "abstained",
            "anchor": None if anchor is None else anchor["name"],
            "observations": signals,
            "actions": actions,
            "tool_schemas": list(definitions.values()),
            "catalog_tools": len(self.mcp.definitions),
            "metrics": metrics,
            "selected": None,
            "evidence": [],
            "links": [],
            "tool_result": None,
            "explanation": "HydraDB could not resolve the service."
            if mode in GRAPH_MODES and not anchor
            else "There is insufficient evidence for a first diagnostic check.",
        }
        graph_before_tool = db_calls
        if decision is not None:
            winner, chosen = actions[decision - 1], selected[decision - 1]
            resolution = await self.mcp.call(winner["tool"], winner["arguments"])
            links, evidence, owner = [], [], chosen.get("owner")
            if anchor is not None:
                evidence, owner = await self.graph.evidence(anchor, chosen)
                db_calls += 1 if anchor["id"] == chosen["service_id"] else 2
                labels = [
                    "DEPENDS_ON"
                    if right["kind"] == "Service"
                    else {
                        "Runbook": "HAS_RUNBOOK",
                        "Skill": "DEFINES_SKILL",
                        "MCP tool": "USES_TOOL",
                        "MCP server": "SERVED_BY",
                    }[right["kind"]]
                    for right in evidence[1:]
                ]
                for left, right, relationship in zip(
                    evidence[:-1], evidence[1:], labels, strict=True
                ):
                    links.append(
                        {
                            "source": str(left["id"]),
                            "target": str(right["id"]),
                            "type": relationship,
                        }
                    )
                evidence = [{**node, "id": str(node["id"])} for node in evidence]
            result.update(
                status="executed",
                selected={**winner, "owner": owner},
                tool_result=resolution,
                evidence=evidence,
                links=links,
                explanation=f"{winner['skill']} for {winner['service_name']}.",
            )
        metrics.update(
            graph_calls=db_calls,
            graph_calls_before_tool=graph_before_tool,
            total_ms=round((perf_counter() - started) * 1000, 1),
            mcp_calls=int(decision is not None),
        )
        return result

    async def verify_feedback(self, run, replay, service, tool):
        anchor = await self.graph.resolve(replay["service"])
        if not anchor or not any(
            entry["skill_id"] == stable_id("skill", service, tool)
            for entry in await self.graph.actions(anchor)
        ):
            raise ValueError("Feedback action is not eligible from the alert service")
        arguments = {
            "case_id": replay["id"],
            "service": service,
            "observed_at": replay["at"],
        }
        replay_output = await self.mcp.call(tool, arguments)
        if replay_output["status"] != "observed":
            raise ValueError("Feedback action has no replay evidence")
        return await self.graph.record(run, replay, service, tool)
