"""Replay a fixed holdout with four routing strategies and isolated training rounds."""

import argparse
import asyncio
import json
import math
import statistics
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx

from triage.catalog import REPLAYS
from triage.config import ROOT, SEED_VERSION, Settings
from triage.decision import Decider
from triage.engine import TriageEngine
from triage.graph import Graph, graph_records
from triage.mcp_client import connect
from triage.training import train_round

GOLD = json.loads((ROOT / "tests" / "gold.json").read_text())


def verdict(case, result):
    gold = GOLD[case["id"]]
    selected = result["selected"]
    matches = (
        selected
        and selected["service"] == gold["service"]
        and selected["tool"] == gold["tool"]
        and selected["arguments"]
        == {
            "case_id": case["id"],
            "service": gold["service"],
            "observed_at": case["at"],
        }
        and result["tool_result"]["status"] == "observed"
        and (result["mode"] in {"flat", "preload"} or bool(result["evidence"]))
    )
    correct = result["status"] == "abstained" if gold["tool"] is None else bool(matches)
    return {
        "case": case["id"],
        "expected": gold,
        "correct": correct,
        "status": result["status"],
        "selected": selected,
        "tool_result": result["tool_result"],
        "evidence": result["evidence"],
        "candidate_hit": gold["tool"] is None
        or any(
            entry["tool"] == gold["tool"] and entry["service"] == gold["service"]
            for entry in result["actions"]
        ),
        "tools": [entry["name"] for entry in result["tool_schemas"]],
        **result["metrics"],
    }


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def summarize(label, details):
    scored = [item for item in details if "error" not in item]
    prompt_tokens = [
        item["prompt_tokens"] for item in scored if item["prompt_tokens"] is not None
    ]
    schema_bytes = [item["schema_bytes"] for item in scored]
    return {
        "label": label,
        "correct": sum(item["correct"] for item in scored),
        "total": len(details),
        "errors": len(details) - len(scored),
        "candidate_hits": sum(item["candidate_hit"] for item in scored),
        "tool_observations": sum(
            item["tool_result"] and item["tool_result"]["status"] == "observed"
            for item in scored
            if item["tool_result"]
        ),
        "median_schemas": statistics.median(len(item["tools"]) for item in scored)
        if scored
        else None,
        "median_schema_bytes": statistics.median(schema_bytes)
        if schema_bytes
        else None,
        "median_prompt_tokens": statistics.median(prompt_tokens)
        if prompt_tokens
        else None,
        "median_calls_before_tool": statistics.median(
            item["model_calls"] for item in scored
        )
        if scored
        else None,
        "p50_ms": percentile([item["total_ms"] for item in scored], 0.50),
        "p95_ms": percentile([item["total_ms"] for item in scored], 0.95),
        "cases": details,
    }


async def score(engine, mode, name, cases, run, checkpoint=0, bookmark=None):
    details = []
    for case in cases:
        try:
            result = await engine.run(case, mode, run, checkpoint, bookmark)
            details.append(verdict(case, result))
        except (RuntimeError, httpx.HTTPError) as error:
            details.append({"case": case["id"], "error": str(error)})
    summary = summarize(name, details)
    print(
        f"{name}: {summary['correct']}/{summary['total']} correct, {summary['errors']} errors",
        flush=True,
    )
    return summary


async def load_sample(graph, service, concurrency):
    permits = asyncio.Semaphore(concurrency)

    async def query():
        async with permits:
            start = perf_counter()
            try:
                await graph.actions(service)
            except RuntimeError:
                return None
            return round((perf_counter() - start) * 1000, 2)

    elapsed = await asyncio.gather(*(query() for _ in range(30)))
    times = [value for value in elapsed if value is not None]
    return {
        "concurrency": concurrency,
        "requests": len(elapsed),
        "errors": len(elapsed) - len(times),
        "p50_ms": percentile(times, 0.50),
        "p95_ms": percentile(times, 0.95),
    }


async def evaluate(args):
    settings = Settings.from_env()
    run = args.run or uuid.uuid4().hex
    cases = [case for case in REPLAYS.values() if case["split"] == "holdout"]
    async with httpx.AsyncClient(timeout=10) as http, connect() as tools:
        graph = Graph(settings, http)
        if not await graph.ready():
            await graph.seed(tools.definitions)
        await graph.check_schemas(tools.definitions)
        engine = TriageEngine(graph, Decider(settings, http), tools)
        if settings.decision_mode == "model":
            await engine.run(REPLAYS["checkout-amber"], "graph")
        baseline = [
            await score(engine, mode, name, cases, run)
            for mode, name in (
                ("preload", "All tools"),
                ("flat", "Flat BM25"),
                ("graph", "Frozen HydraDB"),
            )
        ]
        curve = [
            {
                "round": 0,
                "training_cases": 0,
                "correct": baseline[-1]["correct"],
                "total": len(cases),
            }
        ]
        checkpoints, total, bookmark = [], 0, None
        for checkpoint in range(1, 4):
            added, bookmark = await train_round(engine, run, checkpoint)
            total += added
            entry = await score(
                engine,
                "learned",
                f"HydraDB after round {checkpoint}",
                cases,
                run,
                checkpoint,
                bookmark,
            )
            curve.append(
                {
                    "round": checkpoint,
                    "training_cases": total,
                    "correct": entry["correct"],
                    "total": len(cases),
                }
            )
            checkpoints.append(entry)
        anchor = await graph.resolve("checkoutservice")
        load = [await load_sample(graph, anchor, c) for c in (1, 5, 10)]
        nodes, edges = graph_records(tools.definitions)
        stamp = {
            "created_at": datetime.now(UTC).isoformat(),
            "hydradb": "0.4.0",
            "seed": SEED_VERSION,
            "decision": settings.decision_mode,
            "model": settings.model if settings.decision_mode == "model" else None,
            "data": "Online Boutique manifest subset plus synthetic replay fixtures. Holdouts share scenario families.",
            "nodes": sum(map(len, nodes.values())),
            "edges": sum(map(len, edges.values())),
            "training_cases": total,
            "holdout_cases": len(cases),
        }
        report = {
            "run": run,
            "metadata": stamp,
            "modes": baseline + checkpoints[-1:],
            "curve": curve,
            "checkpoints": checkpoints,
            "graph_query_load": load,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="Training run ID. Omit for a new isolated run.")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results" / "benchmark.json"
    )
    args = parser.parse_args()
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
