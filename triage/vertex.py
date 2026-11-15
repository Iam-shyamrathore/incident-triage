import asyncio
import json
import re

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account


class VertexModel:
    def __init__(self, settings, http: httpx.AsyncClient):
        info = json.loads(settings.vertex_credentials)
        self.credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        project = settings.vertex_project or info["project_id"]
        location = settings.vertex_location
        if not (
            all(re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in (project, location))
            and re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", settings.model)
        ):
            raise ValueError("Invalid Vertex AI project, location or model identifier")
        host = (
            "aiplatform.googleapis.com"
            if location == "global"
            else f"{location}-aiplatform.googleapis.com"
        )
        self.url = (
            f"https://{host}/v1/projects/{project}/locations/{location}"
            f"/publishers/google/models/{settings.model}:generateContent"
        )
        self.http = http
        self.lock = asyncio.Lock()

    async def generate(self, instructions, content, schema):
        async with self.lock:
            if not self.credentials.valid:
                await asyncio.to_thread(self.credentials.refresh, Request())
            token = self.credentials.token
        response = await self.http.post(
            self.url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": content}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 80,
                    "thinkingConfig": {"thinkingBudget": 0},
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        key: value
                        for key, value in schema.items()
                        if key != "additionalProperties"
                    },
                },
            },
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(
            part.get("text", "") for part in parts if not part.get("thought")
        ), data.get("usageMetadata", {}).get("promptTokenCount")
