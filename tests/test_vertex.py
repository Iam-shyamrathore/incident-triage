import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from triage.decision import Decider
from triage.vertex import service_account


@pytest.mark.parametrize("express", [False, True])
def test_vertex_authenticates_and_validates_structured_action(monkeypatch, express):
    credentials = SimpleNamespace(valid=True, token="test-oauth-token")
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        lambda *_args, **_kw: credentials,
    )
    settings = SimpleNamespace(
        vertex_api_key="test-api-key" if express else "",
        vertex_credentials='{"project_id":"test-project"}',
        vertex_project="",
        vertex_location="global",
        model="gemini-3.5-flash-lite",
        decision_mode="model",
        model_configured=True,
    )

    def respond(request):
        assert request.url.host == "aiplatform.googleapis.com"
        assert request.url.path.endswith("/gemini-3.5-flash-lite:generateContent")
        if express:
            assert request.url.path.startswith("/v1/publishers/")
            assert request.headers.get("x-goog-api-key") == "test-api-key"
            assert "Authorization" not in request.headers
        else:
            assert request.url.path.startswith("/v1/projects/test-project/")
            assert request.headers.get("Authorization") == "Bearer test-oauth-token"
            assert "x-goog-api-key" not in request.headers
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
