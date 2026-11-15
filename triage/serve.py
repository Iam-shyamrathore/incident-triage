"""Run the private graph-node and the public ASGI process in one container."""

import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def graph_environment(scratch):
    env = os.environ.copy()
    if env.get("DYNO") and env.get("CLOUD_PROVIDER") != "aws":
        raise SystemExit(
            "Set CLOUD_PROVIDER=aws and configure the S3 backend before deploying to Heroku"
        )
    if env.get("CLOUD_PROVIDER") == "aws" and not env.get("AWS_BUCKET_NAME"):
        raise SystemExit("Set AWS_BUCKET_NAME for the HydraDB S3 backend")
    is_replay = env.get("TRIAGE_EPHEMERAL_REPLAY") == "1"
    if is_replay and env.get("CLOUD_PROVIDER", "local") != "local":
        raise SystemExit("Ephemeral replay mode requires the local graph store")
    token = env.pop("GRAPH_AUTH_TOKEN", "") or (
        secrets.token_hex(32) if is_replay else ""
    )
    local_path = (
        scratch / "graph" if is_replay else Path(env.get("LOCAL_PATH", "/data/graph"))
    )
    if is_replay:
        local_path.mkdir()
        env["TRIAGE_LOAD_VERIFIED_TRAINING"] = "1"
    if len(token) < 32:
        raise SystemExit("Set a GRAPH_AUTH_TOKEN of at least 32 characters")
    token_file = scratch / "token"
    token_file.touch(mode=0o600)
    token_file.write_text(token)
    return {
        **env,
        "CLOUD_PROVIDER": env.get("CLOUD_PROVIDER", "local"),
        "LOCAL_PATH": str(local_path),
        "GRAPH_NAMESPACE": env.get("GRAPH_NAMESPACE", "triage"),
        "GRAPH_ID": "default",
        "GRAPH_CELL_ID": "cell-0",
        "GRAPH_CELLS": "cell-0",
        "GRAPH_NODE_ID": "node-0",
        "GRAPH_DATA_PATH": env.get("GRAPH_DATA_PATH", "incident-triage"),
        "GRAPH_BOLT_ADDR": "127.0.0.1:17687",
        "GRAPH_ADVERTISED_BOLT_ADDR": "127.0.0.1:17687",
        "GRAPH_BOLT_NODE_ADDRESSES": "node-0=127.0.0.1:17687",
        "GRAPH_HTTP_ADDR": "127.0.0.1:18443",
        "GRAPH_ADMIN_ADDR": "127.0.0.1:19091",
        "GRAPH_ALLOW_PLAINTEXT": "true",
        "GRAPH_AUTH_TOKEN_FILE": str(token_file),
        "GRAPH_DATA_CACHE_DIR": str(scratch / "cache"),
        "GRAPH_DATA_CACHE_BYTES": str(64 * 1024 * 1024),
        "GRAPH_SLATE_DB_CACHE_BYTES": str(64 * 1024 * 1024),
        "GRAPH_USAGE_REPORT_ENABLED": "false",
        "RUST_MIN_STACK": str(32 * 1024 * 1024),
    }


def wait_for_graph(graph):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline and graph.poll() is None:
        try:
            with urlopen("http://127.0.0.1:19091/readyz", timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(0.25)
    raise RuntimeError("HydraDB did not become ready")


def main():
    processes = []
    stopping = False

    def terminate(*_):
        nonlocal stopping
        stopping = True
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    with tempfile.TemporaryDirectory(prefix="incident-triage-") as workdir:
        env = graph_environment(Path(workdir))
        try:
            graph_env = {
                k: v
                for k, v in env.items()
                if k
                not in {
                    "TRIAGE_VERTEX_CREDENTIALS",
                    "TRIAGE_MODEL_KEY",
                    "INFERENCE_KEY",
                }
            }
            graph = subprocess.Popen(["/usr/local/bin/graph-node"], env=graph_env)
            processes.append(graph)
            wait_for_graph(graph)
            if stopping:
                return 0
            web = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "triage.api:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    env.get("PORT", "8080"),
                    "--limit-concurrency",
                    "32",
                    "--timeout-graceful-shutdown",
                    "10",
                ],
                env=env,
            )
            processes.append(web)
            while not stopping:
                if any(process.poll() is not None for process in processes):
                    return 1
                time.sleep(0.3)
            return 0
        finally:
            terminate()
            for process in reversed(processes):
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
