import json
from time import perf_counter

import httpx
from google.auth.exceptions import GoogleAuthError

from .vertex import VertexModel


class DecisionError(RuntimeError):
    pass


class Decider:
    def __init__(self, settings, http):
        self.settings = settings
        self.http = http
        self.vertex = (
            VertexModel(settings, http)
            if settings.vertex_api_key or settings.vertex_credentials
            else None
        )

    async def choose(self, alert, observations, actions, definitions):
        packet = {
            "alert": alert,
            "observations": observations,
            "actions": actions,
            "mcp_tool_definitions": list(definitions.values()),
        }
        content = json.dumps(packet, separators=(",", ":"))
        schema_bytes = len(
            json.dumps(packet["mcp_tool_definitions"], separators=(",", ":")).encode()
        )
        metrics = {
            "decision": self.settings.decision_mode,
            "schema_bytes": schema_bytes,
            "prompt_tokens": None,
            "model_calls": 0,
            "model_ms": 0,
        }
        if not actions or not observations:
            metrics["schema_bytes"] = 0
            return None, metrics
        if self.settings.decision_mode == "ranked":
            return actions[0]["id"], metrics
        if not self.settings.model_configured:
            raise DecisionError(
                "Configure Vertex AI or a chat completions endpoint before using model mode"
            )

        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "integer", "minimum": 0, "maximum": len(actions)}
            },
            "required": ["action"],
            "additionalProperties": False,
        }
        request = {
            "model": self.settings.model,
            "temperature": 0,
            "max_completion_tokens": 80,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Choose the first useful read-only diagnostic from the supplied candidate actions. "
                        "Use fresh observations to identify the relevant service and diagnostic kind. "
                        "A release alone is weaker than observed failures. A direct upstream failure can "
                        "be more informative than an aggregate downstream symptom. Prefer a failed trace "
                        "when an upstream span is failing, error counts for local 5xx, latency for slow "
                        "responses, and dependency health for connection failures. Each action lists its "
                        "matched observation kinds and confirmed comparable replays. Candidate order is a prior. "
                        "Return JSON with one integer field action. Use the candidate id or 0 "
                        "when there is no actionable evidence."
                    ),
                },
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "triage_action",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        start = perf_counter()
        try:
            if self.vertex:
                prompt = request["messages"][0]["content"]
                content, token_count = await self.vertex.generate(
                    prompt, content, schema
                )
            else:
                headers = {}
                if self.settings.model_key:
                    headers["Authorization"] = f"Bearer {self.settings.model_key}"
                result = await self.http.post(
                    f"{self.settings.model_url}/v1/chat/completions",
                    headers=headers,
                    json=request,
                    timeout=25,
                )
                result.raise_for_status()
                data = result.json()
                content = data["choices"][0]["message"]["content"]
                token_count = data.get("usage", {}).get("prompt_tokens")
            if not isinstance(content, str):
                raise TypeError("The model response has no text")
            content = content.strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            choice = json.loads(content)["action"]
        except (
            httpx.HTTPError,
            GoogleAuthError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            raise DecisionError(
                "The configured model did not return a valid decision"
            ) from error
        if type(choice) is not int or choice not in {
            0,
            *(action["id"] for action in actions),
        }:
            raise DecisionError(
                "The model selected an action outside the retrieved context"
            )
        metrics.update(
            model_calls=1,
            model=self.settings.model,
            model_ms=round((perf_counter() - start) * 1000, 1),
            prompt_tokens=token_count,
        )
        return choice or None, metrics
