import asyncio
import json
from types import SimpleNamespace

import httpx

from triage.decision import Decider
from triage.vertex import service_account


def test_vertex_uses_oauth_and_validates_structured_action(monkeypatch):
    credentials = SimpleNamespace(valid=True, token="test-oauth-token")
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        lambda *_args, **_kw: credentials,
    )
    settings = SimpleNamespace(
        vertex_credentials='{"project_id":"test-project"}',
        vertex_project="",
        vertex_location="global",
        model="gemini-2.5-flash-lite",
        decision_mode="model",
        model_configured=True,
    )

    def respond(request):
        assert request.url.host == "aiplatform.googleapis.com"
        assert request.url.path.endswith("/gemini-2.5-flash-lite:generateContent")
        assert request.headers.get("Authorization") == "Bearer test-oauth-token"
        body = json.loads(request.content)
        assert (
            body["generationConfig"]["responseSchema"]["properties"]["action"][
                "maximum"
            ]
            == 1
        )
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"action":1}'}]}}],
                "usageMetadata": {"promptTokenCount": 101},
            },
        )

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            action, metrics = await Decider(settings, http).choose(
                "Checkout failed", [{"kind": "error_counter"}], [{"id": 1}], {}
            )
            assert action == 1
            assert metrics["prompt_tokens"] == 101

    asyncio.run(check())
