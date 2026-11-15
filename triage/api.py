import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import REPLAYS, label
from .config import ROOT, Settings
from .decision import Decider, DecisionError
from .engine import MODES, TriageEngine
from .graph import Graph, GraphError
from .mcp_client import connect
from .training import train_round

LOG = logging.getLogger(__name__)
STATIC = ROOT / "triage" / "static"


@asynccontextmanager
async def lifespan(app):
    settings = Settings.from_env()
    async with httpx.AsyncClient(timeout=8) as http, connect() as tools:
        graph = Graph(settings, http)
        if not await graph.ready():
            await graph.seed(tools.definitions)
        await graph.check_schemas(tools.definitions)
        engine = TriageEngine(graph, Decider(settings, http), tools)
        if os.getenv("TRIAGE_LOAD_VERIFIED_TRAINING") == "1":
            run = os.getenv("TRIAGE_FEEDBACK_RUN", "submission")
            for checkpoint in (1, 2, 3):
                await train_round(engine, run, checkpoint)
        app.state.engine = engine
        app.state.slots = asyncio.Semaphore(3)
        yield


app = FastAPI(title="Incident Triage", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ReplayRequest(BaseModel):
    case: str = Field(min_length=1, max_length=60)
    mode: str = Field(default="learned", max_length=16)
    service: str | None = Field(default=None, min_length=1, max_length=80)
    alert: str | None = Field(default=None, min_length=1, max_length=500)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health():
    engine = app.state.engine
    try:
        graph_ready = await engine.graph.ready()
    except GraphError:
        raise HTTPException(503, "HydraDB is unavailable") from None
    if not graph_ready:
        raise HTTPException(503, "The graph catalog is not initialized")
    settings = engine.decider.settings
    return {
        "graph": "ready",
        "mcp_tools": len(engine.mcp.definitions),
        "decision": settings.decision_mode,
        "model": settings.model or None,
        "model_configured": settings.model_configured,
    }


@app.get("/api/cases")
async def cases():
    return [
        {
            "id": case["id"],
            "title": case["title"],
            "alert": case["alert"],
            "service": label(case["service"]),
            "environment": case["environment"],
        }
        for case in REPLAYS.values()
        if case["public"]
    ]


@app.get("/api/benchmark", include_in_schema=False)
async def benchmark():
    path = ROOT / "data" / "benchmark.json"
    if not path.is_file():
        raise HTTPException(404, "A benchmark has not been published for this build")
    return FileResponse(path, media_type="application/json")


@app.post("/api/triage")
async def triage(request: ReplayRequest):
    replay = REPLAYS.get(request.case)
    if not replay or not replay["public"]:
        raise HTTPException(404, "Choose one of the available replay cases")
    if request.mode not in MODES:
        raise HTTPException(422, "Unknown retrieval mode")
    if request.service and request.mode in {"flat", "preload"}:
        raise HTTPException(422, "Service overrides are available in graph modes")
    if app.state.slots.locked():
        raise HTTPException(429, "The replay runner is busy. Try again in a moment.")
    async with app.state.slots:
        try:
            return await app.state.engine.run(
                replay,
                request.mode,
                os.getenv("TRIAGE_FEEDBACK_RUN", "submission"),
                service_hint=request.service,
                alert=request.alert,
            )
        except (GraphError, DecisionError) as error:
            LOG.warning("Replay %s is unavailable: %s", request.case, error)
            raise HTTPException(
                503, "The graph or configured model could not complete this replay."
            ) from None
        except RuntimeError:
            LOG.exception("Replay tool failed")
            raise HTTPException(
                502, "The replay tool could not complete this check."
            ) from None
