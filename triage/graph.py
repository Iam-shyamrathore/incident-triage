import json
from collections import defaultdict
from uuid import uuid4

import httpx

from .catalog import (
    DEFAULT_TOOLS,
    DEPENDENCIES,
    REPLAYS,
    SERVICES,
    SKILLS,
    SOURCE,
    TOOLS_BY_SERVICE,
    normalized,
    stable_id,
)
from .config import SEED_VERSION


class GraphError(RuntimeError):
    pass


class Graph:
    def __init__(self, settings, http: httpx.AsyncClient):
        self.http = http
        self.url = settings.graph_url + "/v1/graphs/default/query"
        self.headers = {
            "Authorization": f"Bearer {settings.graph_token}",
            "X-Graph-Namespace": settings.namespace,
        }

    async def query(self, query, parameters=None, bookmark=None):
        # HydraDB incorporates query IDs into persisted mutation idempotency keys.
        # Survive a graph restart without reusing the server's process-local defaults.
        body = {
            "cell_id": "cell-0",
            "query_id": uuid4().hex,
            "query": query,
            "parameters": parameters or {},
        }
        if bookmark:
            body["bookmark"] = bookmark
        try:
            response = await self.http.post(self.url, headers=self.headers, json=body)
            response.raise_for_status()
            data = response.json()
            rows = [
                dict(
                    zip(
                        data["columns"],
                        (cell.get("value") if cell else None for cell in row),
                        strict=True,
                    )
                )
                for row in data["rows"]
            ]
            if data.get("next_cursor"):
                raise GraphError("HydraDB returned an incomplete page")
        except (httpx.HTTPError, KeyError, ValueError) as error:
            detail = (
                response.text[:500]
                if isinstance(error, httpx.HTTPStatusError)
                else str(error)
            )
            raise GraphError(f"HydraDB query failed: {detail}") from error
        return rows, data.get("bookmark")

    async def ready(self):
        rows, _ = await self.query(
            "MATCH (n:Catalog {id: $id}) RETURN n.version AS version",
            {
                "id": stable_id("catalog", SEED_VERSION),
            },
        )
        return rows == [{"version": SEED_VERSION}]

    async def upsert(self, label, records):
        keys = sorted(records[0].keys() - {"id"})
        assignments = ", ".join(f"n.{key} = row.{key}" for key in keys)
        query = (
            f"UNWIND $rows AS row MERGE (n {{id: row.id}}) SET n:{label}, {assignments}"
        )
        for start in range(0, len(records), 100):
            await self.query(query, {"rows": records[start : start + 100]})

    async def edges(self, relation, records):
        query = f"UNWIND $rows AS row CREATE (a {{id: row.src}})-[:{relation}]->(b {{id: row.dst}})"
        bookmark = None
        for start in range(0, len(records), 100):
            _, bookmark = await self.query(
                query, {"rows": records[start : start + 100]}
            )
        return bookmark

    async def seed(self, definitions):
        nodes, edges = graph_records(definitions)
        for label, records in nodes.items():
            await self.upsert(label, records)
        for relation, records in edges.items():
            await self.edges(relation, records)
        await self.upsert(
            "Catalog",
            [{"id": stable_id("catalog", SEED_VERSION), "version": SEED_VERSION}],
        )

    async def check_schemas(self, definitions):
        rows, _ = await self.query(
            "MATCH (t:Tool) RETURN t.key AS key, t.definition AS definition"
        )
        schemas = {row["key"]: json.loads(row["definition"]) for row in rows}
        if schemas != definitions:
            raise GraphError("Graph tool definitions differ from MCP tools/list")

    async def resolve(self, alias):
        rows, _ = await self.query(
            "MATCH (a:Alias {key: $alias})-[:RESOLVES_TO]->(s:Service) "
            "RETURN DISTINCT s.id AS id, s.key AS key, s.name AS name",
            {"alias": normalized(alias)},
        )
        return rows[0] if len(rows) == 1 else None

    async def actions(self, service):
        projection = (
            "(u:Service)-[:HAS_RUNBOOK]->(r:Runbook)-[:DEFINES_SKILL]->(k:Skill)"
            "-[:USES_TOOL]->(t:Tool)-[:SERVED_BY]->(m:McpServer) "
        )
        columns = (
            "RETURN DISTINCT u.id AS service_id, u.key AS service, u.name AS service_name, "
            "r.id AS runbook_id, r.title AS runbook, k.id AS skill_id, k.title AS skill, "
            "k.instructions AS instructions, k.tags AS tags, k.priority AS priority, "
            "t.id AS tool_id, t.key AS tool, t.definition AS definition, m.id AS server_id, m.name AS server"
        )
        local = f"MATCH {projection} WHERE u.id = $id {columns}"
        upstream = (
            f"MATCH (s:Service {{id: $id}})-[:DEPENDS_ON*1..3]->{projection} {columns}"
        )
        rows, _ = await self.query(f"{local} UNION {upstream}", {"id": service["id"]})
        for row in rows:
            row["definition"] = json.loads(row["definition"])
        return rows

    async def observations(self, replay):
        params = {
            "id": stable_id("incident", replay["id"]),
            "at": replay["at"],
            "env": replay["environment"],
            "start": replay["at"] - 30,
        }
        rows, _ = await self.query(
            "MATCH (i:Incident {id: $id})-[:HAS_SIGNAL]->(o:Signal)-[:ABOUT]->(s:Service) "
            "WHERE o.environment = $env AND o.observed >= $start AND o.observed <= $at "
            "RETURN s.key AS service, o.kind AS kind, o.text AS text, o.severity AS severity, "
            "o.observed AS observed ORDER BY severity DESC, observed DESC",
            params,
        )
        deploys, _ = await self.query(
            "MATCH (i:Incident {id: $id})-[:OBSERVED_DEPLOYMENT]->(d:Deployment)<-[:HAS_DEPLOYMENT]-(s:Service) "
            "WHERE d.environment = $env AND d.at >= $start AND d.at <= $at "
            "RETURN s.key AS service, d.key AS deploy, d.at AS at ORDER BY at DESC",
            params,
        )
        return rows, deploys

    async def feedback(self, replay, run, checkpoint, bookmark=None):
        rows, _ = await self.query(
            "MATCH (f:Feedback)-[:CORRECT_FOR]->(k:Skill) "
            "WHERE f.feedback_run = $run AND f.batch <= $checkpoint AND f.source = $source "
            "AND f.symptom = $symptom AND f.at < $at "
            "RETURN k.id AS skill_id, count(f.id) AS confirmations",
            {
                "run": run,
                "checkpoint": checkpoint,
                "source": replay["service"],
                "symptom": replay["symptom"],
                "at": replay["at"],
            },
            bookmark,
        )
        return {row["skill_id"]: row["confirmations"] for row in rows}

    async def record(self, run, replay, service, tool):
        if replay["split"] != "train":
            raise ValueError("Only labeled training cases can contribute feedback")
        event_id = stable_id("feedback", run, replay["id"])
        await self.upsert(
            "Feedback",
            [
                {
                    "id": event_id,
                    "feedback_run": run,
                    "source": replay["service"],
                    "symptom": replay["symptom"],
                    "batch": replay["batch"],
                    "at": replay["at"],
                }
            ],
        )
        return await self.edges(
            "CORRECT_FOR", [{"src": event_id, "dst": stable_id("skill", service, tool)}]
        )

    async def evidence(self, start, action):
        details = []
        if start["id"] != action["service_id"]:
            # Procedure arguments are constructed only from graph-returned integer IDs.
            src, dst = int(start["id"]), int(action["service_id"])
            rows, _ = await self.query(
                f"CALL algo.SPpaths({{sourceNode: {src}, targetNode: {dst}, "
                "relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', maxLen: 3, pathCount: 1}) "
                "YIELD path RETURN path"
            )
            if not rows:
                raise GraphError(
                    "The selected candidate no longer has a dependency path"
                )
            path = rows[0]["path"]
            details = [
                {
                    "id": node["id"],
                    "name": node["properties"]["name"]["String"],
                    "kind": "Service",
                }
                for node in path["nodes"][:-1]
            ]
        owner, _ = await self.query(
            "MATCH (s:Service {id: $id})-[:OWNED_BY]->(t:Team) RETURN t.name AS owner",
            {"id": action["service_id"]},
        )
        details.extend(
            [
                {
                    "id": action["service_id"],
                    "name": action["service_name"],
                    "kind": "Service",
                },
                {
                    "id": action["runbook_id"],
                    "name": action["runbook"],
                    "kind": "Runbook",
                },
                {"id": action["skill_id"], "name": action["skill"], "kind": "Skill"},
                {"id": action["tool_id"], "name": action["tool"], "kind": "MCP tool"},
                {
                    "id": action["server_id"],
                    "name": action["server"],
                    "kind": "MCP server",
                },
            ]
        )
        return details, owner[0]["owner"] if owner else None


def graph_records(definitions):
    nodes, relations = defaultdict(list), defaultdict(list)
    id_keys = {}

    def node(label, logical_key, **properties):
        key = (label.lower(), *logical_key)
        identity = stable_id(*key)
        existing = id_keys.get(identity)
        if existing is None:
            nodes[label].append({"id": identity, **properties})
            id_keys[identity] = key
        elif existing != key:
            raise ValueError("Graph identity collision")
        return identity

    def link(kind, source, target):
        record = {"src": source, "dst": target}
        if record not in relations[kind]:
            relations[kind].append(record)

    server = node("McpServer", ("replay",), name="Online Boutique replay")
    tool_ids = {
        tool: node(
            "Tool", (tool,), key=tool, definition=json.dumps(definition, sort_keys=True)
        )
        for tool, definition in definitions.items()
    }
    for tool_id in tool_ids.values():
        link("SERVED_BY", tool_id, server)

    for key, (name, owner, aliases) in SERVICES.items():
        service = node(
            "Service",
            (key,),
            key=key,
            name=name,
            source="Synthetic" if key == "payment-gateway" else SOURCE,
        )
        link("OWNED_BY", service, node("Team", (owner,), name=owner))
        for alias in dict.fromkeys(
            normalized(value) for value in (key, name, *aliases)
        ):
            link("RESOLVES_TO", node("Alias", (alias,), key=alias), service)
        runbook = node("Runbook", (key,), title=f"{name} diagnostics")
        link("HAS_RUNBOOK", service, runbook)
        for tool in TOOLS_BY_SERVICE.get(key, DEFAULT_TOOLS):
            title, instructions, tags, priority = SKILLS[tool]
            skill = node(
                "Skill",
                (key, tool),
                title=title,
                instructions=instructions,
                tags=tags,
                priority=priority,
            )
            link("DEFINES_SKILL", runbook, skill)
            link("USES_TOOL", skill, tool_ids[tool])

    for key, targets in DEPENDENCIES.items():
        for target in targets:
            link("DEPENDS_ON", stable_id("service", key), stable_id("service", target))

    for replay in REPLAYS.values():
        case = replay["id"]
        incident = node(
            "Incident",
            (case,),
            key=case,
            environment=replay["environment"],
            observed=replay["at"],
        )
        for index, signal in enumerate(replay["signals"]):
            target = stable_id("service", signal["service"])
            props = {k: v for k, v in signal.items() if k != "service"}
            record = node("Signal", (case, str(index)), **props)
            link("HAS_SIGNAL", incident, record)
            link("ABOUT", record, target)
        for deploy in replay["deployments"]:
            record = node(
                "Deployment",
                (deploy["key"],),
                key=deploy["key"],
                environment=deploy["environment"],
                at=deploy["at"],
            )
            link("OBSERVED_DEPLOYMENT", incident, record)
            link("HAS_DEPLOYMENT", stable_id("service", deploy["service"]), record)
    return nodes, relations
