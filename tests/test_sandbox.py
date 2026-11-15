import asyncio
import os

import httpx
import pytest
from pydantic import ValidationError

from triage.catalog import stable_id
from triage.config import Settings
from triage.decision import Decider
from triage.engine import TriageEngine
from triage.graph import Graph
from triage.incidents import PROVIDED_SOURCE, CustomIncident
from triage.mcp_client import connect


def test_sandbox_rejects_impossible_error_counts():
    with pytest.raises(ValidationError, match="Failed requests cannot exceed"):
        CustomIncident.model_validate(
            {
                "alert": "Checkout errors",
                "service": "checkoutservice",
                "signals": [
                    {
                        "service": "checkoutservice",
                        "kind": "error_counter",
                        "value": "12/10",
                    },
                ],
            }
        )


@pytest.mark.skipif(
    not (os.getenv("GRAPH_AUTH_TOKEN_FILE") or os.getenv("TRIAGE_GRAPH_TOKEN")),
    reason="Requires a local HydraDB container",
)
def test_custom_evidence_respects_hop_limit_and_reaches_real_mcp(monkeypatch):
    monkeypatch.setenv("TRIAGE_DECISION_MODE", "ranked")

    async def check():
        case = CustomIncident.model_validate(
            {
                "alert": "Checkout errors",
                "service": "checkoutservice",
                "signals": [
                    {
                        "service": "payment-gateway",
                        "kind": "trace",
                        "value": "user probe GW-483",
                    }
                ],
            }
        ).as_case()
        key = stable_id("incident", case["id"])
        settings = Settings.from_env()
        async with httpx.AsyncClient(timeout=10) as http, connect() as mcp:
            graph = Graph(settings, http)
            if not await graph.ready():
                await graph.seed(mcp.definitions)
            engine = TriageEngine(graph, Decider(settings, http), mcp)
            async with graph.custom_incident(case):
                shallow = await engine.run(case, "graph", hop_limit=1)
                assert shallow["status"] == "abstained"
                assert "Payment gateway" not in shallow["reachable"]
                deep = await engine.run(case, "graph", hop_limit=2)
                assert [node["name"] for node in deep["evidence"][:3]] == [
                    "Checkout",
                    "Payments",
                    "Payment gateway",
                ]
                assert deep["tool_result"]["evidence"] == {"trace": "user probe GW-483"}
                assert deep["tool_result"]["source"] == PROVIDED_SOURCE
                assert deep["metrics"]["mcp_calls"] == 1
            rows, _ = await graph.query(
                "MATCH (s:Signal {scope: $id}) RETURN s.id AS id", {"id": key}
            )
            assert not rows
            rows, _ = await graph.query(
                "MATCH (i:Incident {id: $id}) RETURN i.id AS id", {"id": key}
            )
            assert not rows

    asyncio.run(check())
