import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_VERSION = "online-boutique-2"


@dataclass(frozen=True)
class Settings:
    graph_url: str
    graph_token: str
    namespace: str
    model_url: str
    model_key: str
    model: str
    decision_mode: str
    vertex_credentials: str = field(default="", repr=False)
    vertex_api_key: str = field(default="", repr=False)
    vertex_project: str = ""
    vertex_location: str = "global"

    @property
    def model_configured(self):
        return bool(
            self.model
            and (self.vertex_api_key or self.vertex_credentials or self.model_url)
        )

    @classmethod
    def from_env(cls):
        token_file = os.getenv("GRAPH_AUTH_TOKEN_FILE")
        token = os.getenv("TRIAGE_GRAPH_TOKEN")
        if token_file and not token:
            token = Path(token_file).read_text().strip()
        mode = os.getenv("TRIAGE_DECISION_MODE", "model")
        if mode not in {"model", "ranked"}:
            raise ValueError("TRIAGE_DECISION_MODE must be model or ranked")
        vertex_api_key = os.getenv("TRIAGE_VERTEX_API_KEY", "")
        vertex_credentials = os.getenv("TRIAGE_VERTEX_CREDENTIALS", "")
        vertex_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if vertex_file and not (vertex_credentials or vertex_api_key):
            vertex_credentials = Path(vertex_file).read_text()
        return cls(
            graph_url=os.getenv("TRIAGE_GRAPH_URL", "http://127.0.0.1:18443").rstrip(
                "/"
            ),
            graph_token=token or "",
            namespace=os.getenv("GRAPH_NAMESPACE", "triage"),
            model_url=os.getenv(
                "TRIAGE_MODEL_URL", os.getenv("INFERENCE_URL", "")
            ).rstrip("/"),
            model_key=os.getenv("TRIAGE_MODEL_KEY", os.getenv("INFERENCE_KEY", "")),
            model=os.getenv(
                "TRIAGE_MODEL",
                "gemini-3.5-flash-lite"
                if (vertex_credentials or vertex_api_key)
                else "",
            ),
            vertex_credentials=vertex_credentials,
            vertex_api_key=vertex_api_key,
            vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            vertex_location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            decision_mode=mode,
        )
