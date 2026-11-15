import asyncio
import os
from uuid import uuid4

import httpx
import pytest

from triage.catalog import REPLAYS, stable_id
from triage.config import Settings
from triage.decision import Decider
from triage.engine import TriageEngine, shortlist
from triage.graph import Graph
from triage.mcp_client import connect
from triage.training import train_round


def test_shortlist_needs_current_support_and_repeated_feedback():
    confirmed = {
        "service": "gateway",
        "tool": "trace_failures",
        "score": 16,
        "confirmations": 2,
    }
    alternate = {
        "service": "shipping",
        "tool": "inspect_errors",
        "score": 12,
        "confirmations": 0,
    }
    signals = [{"service": "gateway", "kind": "error_counter", "severity": 11}]
    assert shortlist([confirmed, alternate], signals, "learned") == [confirmed]
    assert shortlist([confirmed, alternate], signals, "graph") == [confirmed, alternate]
    newer = signals + [{"service": "shipping", "kind": "error_counter", "severity": 13}]
    assert shortlist([confirmed, alternate], newer, "learned") == [confirmed, alternate]
    assert shortlist([confirmed, alternate], [], "learned") == [confirmed, alternate]


def test_real_mcp_lists_definitions_and_calls_a_bound_tool():
    async def check():
        case = REPLAYS["checkout-amber"]
        async with connect() as mcp:
            assert len(mcp.definitions) == 6
            result = await mcp.call(
                "trace_failures",
                {
                    "case_id": case["id"],
                    "service": "payment-gateway",
                    "observed_at": case["at"],
                },
            )
            assert result["status"] == "observed"
            assert "UNAVAILABLE" in result["evidence"]["trace"]

    asyncio.run(check())


@pytest.mark.skipif(
    not (os.getenv("GRAPH_AUTH_TOKEN_FILE") or os.getenv("TRIAGE_GRAPH_TOKEN")),
    reason="Requires the local HydraDB container",
)
def test_hydradb_traversal_feedback_and_batch_retries(monkeypatch):
    monkeypatch.setenv("TRIAGE_DECISION_MODE", "ranked")

    async def check():
        settings = Settings.from_env()
        async with httpx.AsyncClient(timeout=10) as http, connect() as mcp:
            graph = Graph(settings, http)
            engine = TriageEngine(graph, Decider(settings, http), mcp)
            if not await graph.ready():
                await graph.seed(mcp.definitions)
            await graph.check_schemas(mcp.definitions)
            anchor = await graph.resolve("Checkout API")
            assert anchor["key"] == "checkoutservice"
            actions = await graph.actions(anchor)
            assert "payment-gateway" in {row["service"] for row in actions}

            temporary = {"src": anchor["id"], "dst": stable_id("service", "adservice")}
            assert "adservice" not in {row["service"] for row in actions}
            try:
                await graph.edges("DEPENDS_ON", [temporary])
                live_actions = await graph.actions(anchor)
                assert "adservice" in {row["service"] for row in live_actions}
            finally:
                await graph.query(
                    "MATCH (a {id: $src})-[e:DEPENDS_ON]->(b {id: $dst}) DELETE e",
                    temporary,
                )
            assert "adservice" not in {
                row["service"] for row in await graph.actions(anchor)
            }

            run = f"integration-{uuid4().hex}"
            try:
                replay = REPLAYS["checkout-amber"]
                skill = stable_id("skill", "payment-gateway", "trace_failures")
                for _ in range(2):
                    for round_number in (1, 2):
                        _, bookmark = await train_round(engine, run, round_number)
                counts = await graph.feedback(replay, run, 2, bookmark)
                assert counts[skill] == 2
                result = await engine.run(replay, "learned", run, 2, bookmark)
                assert result["selected"]["tool"] == "trace_failures"
                assert result["selected"]["confirmations"] == 2
                assert len(result["tool_schemas"]) == 1
                assert [node["name"] for node in result["evidence"][:3]] == [
                    "Checkout",
                    "Payments",
                    "Payment gateway",
                ]
                empty = await engine.run(REPLAYS["checkout-stale"], "learned", run, 2)
                assert empty["status"] == "abstained"
                assert not empty["observations"]
                assert empty["metrics"]["mcp_calls"] == 0
            finally:
                await graph.query(
                    "MATCH (f:Feedback {feedback_run: $run}) DETACH DELETE f",
                    {"run": run},
                )

    asyncio.run(check())
