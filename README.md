# Incident Triage

Replay an on-call alert and see the first useful diagnostic check. HydraDB resolves the service, traverses dependencies, and retrieves the runbook, skill, tool schema and MCP server. The agent receives a bounded packet and selects one read-only diagnostic or abstains. The web UI shows the graph path, selected arguments and observed tool response.

Built for HydraDB Hackathon Track 2. [Open the live demo](https://hydradb-incident-triage.vercel.app). The topology is a subset of [Online Boutique at a pinned revision](https://github.com/GoogleCloudPlatform/microservices-demo/tree/c7cb6d5bfd6ea3aed768634ebbcb98cb7a523712/kubernetes-manifests). The payment gateway, owners, incidents, deployments, labels and telemetry are synthetic.

## Try your own incident

Start in **Your incident**. Edit the alert, choose an alerted service from the live sandbox catalog, and enter a trace, latency, connection status or error count. Measurements enter HydraDB as observations scoped to the current request. The selected MCP tool receives the submitted measurement and reports it with source attribution. Example replays remain available for reproducing the benchmark.

With the editable checkout sample, run **1 hop** and observe that the payment gateway is outside the graph scope. Set **2 hops**, change the failed-span text and rerun. The returned trace should contain exactly the new sample, with the path from Checkout through Payments to the gateway. The sandbox exposes the seeded Online Boutique dependency catalog and accepts submitted telemetry. Use synthetic or sanitized measurements.

## Architecture

```text
Alert → Alias → Service → dependency Service → Runbook → Skill → Tool → McpServer
                           ↳ observed signals and deployments by replay and time

API → HydraDB HTTP → bounded context packet → one model decision → MCP tools/call
```

The app keeps a live MCP stdio session. Startup compares the schemas discovered by `tools/list` with the definitions stored in HydraDB. Graph routing uses typed and directed traversal for candidate eligibility. The displayed dependency hops come from `algo.SPpaths`, and the remaining nodes come from the typed Cypher match. A graph read failure fails the replay.

Feedback is written as one stable graph event per verified training incident and run. Later requests read relevant earlier confirmations by alert service, symptom and skill. Repeated confirmations can narrow the shortlist when the leading candidate is supported by the strongest current observation. The agent still evaluates whether to execute the check. The public API accepts fixed replays and sandbox incidents. Diagnostic MCP calls are read-only.

## Run with Docker Compose

Use Docker with Compose and a model endpoint implementing `POST /v1/chat/completions`. For local model runs, [Ollama](https://docs.ollama.com/api/openai-compatibility) can serve Qwen without an API key.

```sh
ollama pull qwen2.5:1.5b
```

Run Ollama separately. Set `TRIAGE_MODEL_URL` to an address reachable from the container, such as `http://host.docker.internal:11434` on Docker Desktop. The URL is a base URL without the `/v1` suffix.

```sh
export GRAPH_AUTH_TOKEN="$(openssl rand -hex 32)"
export TRIAGE_MODEL_URL=http://host.docker.internal:11434
export TRIAGE_MODEL=qwen2.5:1.5b
docker compose up --build
```

Open [the local app](http://localhost:8080). The Compose volume retains graph data across restarts. For a deterministic smoke test, set `TRIAGE_DECISION_MODE=ranked`. The UI labels that mode and the reported model call count is zero.

## Run and evaluate with an existing HydraDB instance

Use a self-hosted HydraDB v0.4.0 graph called `default` with cell `cell-0`, and a token file readable by the app. The app also accepts the graph token in `TRIAGE_GRAPH_TOKEN`. Set the namespace to match the engine. [HydraDB setup guide](https://github.com/hydra-db/hydradb/blob/v0.4.0/USING-HYDRADB.md)

```sh
uv sync --locked
export GRAPH_AUTH_TOKEN_FILE=/path/to/graph-token
export GRAPH_NAMESPACE=triage
export TRIAGE_GRAPH_URL=http://127.0.0.1:18443
export TRIAGE_MODEL_URL=http://127.0.0.1:11434
export TRIAGE_MODEL=qwen2.5:1.5b
export TRIAGE_LOAD_VERIFIED_TRAINING=1
uv run uvicorn triage.api:app --port 8080
```

A hosted model also needs `TRIAGE_MODEL_KEY`, or Heroku's `INFERENCE_URL` and `INFERENCE_KEY`. Model output is validated against the server's eligible action IDs. All tool arguments are resolved by the application.

With the same environment run these commands from the repo root.

```sh
uv run pytest -q
uv run python -m scripts.evaluate
```

The evaluator saves `results/benchmark.json` using a fresh feedback run ID. It applies three batches of earlier training cases and evaluates the same 12 held-out cases at each checkpoint. The included [benchmark report](data/benchmark.json) is served at `/api/benchmark`.

## Verified local benchmark

| Routing | Correct first action | Median tool schemas | Median model input |
| --- | ---: | ---: | ---: |
| All tools | 2/12 | 6 | 3,007 tokens |
| Flat BM25 | 5/12 | 1.5 | 660 tokens |
| Frozen HydraDB | 9/12 | 2.5 | 714 tokens |
| HydraDB after round 3 | 12/12 | 1 | 402 tokens |

The graph curve was 9 → 9 → 10 → 12 correct. The scored action includes the tool, service, bound arguments, observed result and, in graph modes, a graph path. Correct abstention counts as a success. Scores use the same Qwen 2.5 1.5B model throughout. Token medians use cases with model calls. The all-tools arm includes the full candidate and schema catalog. Flat BM25 can search text representations of the same underlying relationship facts.

The fixture has 12 held-out replays drawn from shared synthetic scenario families and 10 training replays. It measures this fixture and does not establish production accuracy. The base graph contains 260 nodes and 419 edges, excluding the catalog marker and feedback events. HydraDB ran in a Linux ARM64 VM with 2 vCPUs and 2 GiB RAM on an Apple M2, using local storage. The load check sent 30 candidate queries at each of concurrency 1, 5 and 10. It recorded zero errors and p95 times of 19 ms, 59 ms and 165 ms respectively. End-to-end timing includes the local model and MCP.

## Vercel replay deployment

The Vercel Container runtime builds the root Dockerfile. An instance runs the API, MCP replay server and pinned HydraDB engine together. The public API serves example replays and temporary custom incidents. Each fresh container seeds a local graph under its temporary directory and loads the earlier verified replay outcomes into HydraDB. This gives the demo the same learned state after every cold start. An open-ended production workflow that accepts new feedback would need a persistent storage backend.

The production app uses Gemini 3.5 Flash-Lite. The benchmark above uses Qwen 2.5 1.5B.

For Vertex AI Express, set the **server-only** variable `TRIAGE_VERTEX_API_KEY`. For standard Vertex AI, set `TRIAGE_VERTEX_CREDENTIALS` to a service-account JSON with access to an enabled Vertex project, or point `GOOGLE_APPLICATION_CREDENTIALS` to a credentials file for local runs. The provider defaults to `gemini-3.5-flash-lite`. Set `TRIAGE_MODEL` to override it. Keep credentials out of the repository. [Vertex AI Express authentication](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/express-mode/api-reference)

```sh
vercel deploy --prod --env PORT=8080 --env TRIAGE_EPHEMERAL_REPLAY=1
```

The graph token is generated inside each replay container. To test the graph and MCP without a remote model, add `--env TRIAGE_DECISION_MODE=ranked`. The UI labels ranked mode. [Vercel Container runtime](https://vercel.com/docs/functions/runtimes/container)

## Heroku release

`Dockerfile` and `heroku.yml` package the web UI and API on one Heroku app. The web server binds `$PORT`. The supervisor runs HydraDB privately on loopback and the API starts the MCP subprocess. For a Heroku release, set the existing target app to the container stack and configure the following runtime values before pushing. Use a stable, private S3 bucket for graph data because Heroku dyno storage is ephemeral.

| Required | Value |
| --- | --- |
| `CLOUD_PROVIDER` | `aws` |
| `AWS_BUCKET_NAME`, `AWS_DEFAULT_REGION` | Dedicated bucket and its region |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Credentials scoped to the graph bucket and prefix |
| `GRAPH_AUTH_TOKEN` | Random token of at least 32 characters |
| `TRIAGE_MODEL` | Chat model identifier |
| `TRIAGE_MODEL_URL` and `TRIAGE_MODEL_KEY`, or `INFERENCE_URL` and `INFERENCE_KEY` | Model endpoint and credential |
| `TRIAGE_LOAD_VERIFIED_TRAINING` | `1` to initialize the sample verified feedback set |

`GRAPH_DATA_PATH` defaults to `incident-triage`. Pin it per deployment. Use one web dyno for the demo and verify its memory headroom and startup time.

```sh
heroku stack:set container --app YOUR_APP
heroku git:remote --app YOUR_APP
git push heroku HEAD:main
```

After release, check `/health`, run a public replay and inspect the tool result. Restart the dyno, then verify that the graph and learned confirmations are still present. The Heroku release remains unverified. [Heroku container builds](https://devcenter.heroku.com/articles/build-docker-images-heroku-yml) · [Dyno filesystem](https://devcenter.heroku.com/articles/dynos#ephemeral-filesystem)

## License

Incident Triage is MIT-licensed. The separately distributed engine follows [HydraDB's Elastic License 2.0](https://github.com/hydra-db/hydradb/blob/v0.4.0/LICENSE).
