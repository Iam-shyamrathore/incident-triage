const get = (id) => document.getElementById(id);
const casePicker = get("case-picker");
const modePicker = get("mode-picker");
const run = get("run");
let cases = new Map();

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Could not complete the request.");
  return payload;
}

function showCase() {
  const record = cases.get(casePicker.value);
  if (!record) return;
  get("case-code").textContent = record.id.toUpperCase();
  get("alert-text").textContent = record.alert;
  get("case-service").textContent = `${record.service} · ${record.environment}`;
  reset("AWAITING REPLAY");
  get("replay-status").textContent = "";
}

function reset(label) {
  get("trace-state").textContent = label;
  get("output").hidden = true;
  get("empty").hidden = false;
  get("metrics").hidden = true;
}

function summarizeFinding(data) {
  if (!data) return "";
  if (data.status !== "observed") return "This replay does not have matching telemetry.";
  const evidence = data.evidence;
  if (evidence.trace) return evidence.trace.split(": ").slice(1).join(": ") || evidence.trace;
  if (evidence.failed_requests != null) return `${evidence.failed_requests} of ${evidence.sampled_requests} sampled requests failed.`;
  if (evidence.p95_ms != null) return `The observed p95 latency was ${evidence.p95_ms} ms.`;
  if (evidence.connection_status) return `The replay shows ${evidence.connection_status} connections.`;
  if (evidence.deployment) return `Release ${evidence.deployment.key} was visible before the alert.`;
  return evidence.log || "The tool returned an observation.";
}

function render(result) {
  const output = get("output");
  get("empty").hidden = true;
  output.hidden = false;
  const selection = result.selected;
  get("trace-state").textContent = selection ? "CHECK EXECUTED" : "ABSTAINED";
  get("check-label").textContent = selection ? "FIRST DIAGNOSTIC" : "NO DIAGNOSTIC SELECTED";
  get("action-title").textContent = selection ? selection.skill : "Wait for evidence";
  get("action-detail").textContent = selection
    ? [selection.service_name, selection.owner, selection.deploy,
      selection.confirmations ? `${selection.confirmations} verified earlier replays` : null].filter(Boolean).join(" · ")
    : result.explanation;

  get("finding").hidden = !result.tool_result;
  get("finding-text").textContent = summarizeFinding(result.tool_result);

  get("path").replaceChildren(...result.evidence.map((node, index) => {
    const li = element("li");
    li.append(element("span", node.kind, "node-type"), element("span", node.name, "node-name"));
    if (index) li.append(element("small", result.links[index - 1].type));
    return li;
  }));
  get("trace").hidden = !result.evidence.length;
  get("signals").replaceChildren(...result.observations.map((signal) =>
    element("li", signal.text)));
  get("observations").hidden = !result.observations.length;

  get("tool-result").hidden = !result.tool_result;
  get("tool-json").textContent = result.tool_result
    ? JSON.stringify({ tool: selection.tool, arguments: selection.arguments, response: result.tool_result }, null, 2)
    : "";
  get("context").hidden = !result.tool_schemas.length;
  get("context-title").textContent = `Agent context · ${result.tool_schemas.length} of ${result.catalog_tools} schemas`;
  get("action-list").replaceChildren(...result.actions.map((action) =>
    element("li", `${action.service_name} · ${action.skill}`)));
  get("schema-list").replaceChildren(...result.tool_schemas.map((schema) => {
    const node = element("div", null, "tool-schema");
    node.append(element("strong", schema.name), element("p", schema.description));
    const details = element("details");
    details.append(element("summary", "Input schema"), element("pre", JSON.stringify(schema.schema, null, 2)));
    node.append(details);
    return node;
  }));

  const values = [
    ["Routing", result.metrics.model || "Ranked"],
    ["HydraDB queries", result.metrics.graph_calls],
    ["Model calls", result.metrics.model_calls],
    ["MCP calls", result.metrics.mcp_calls],
    ["Elapsed", `${(result.metrics.total_ms / 1000).toFixed(2)} s`],
  ];
  if (result.metrics.prompt_tokens != null) values.splice(3, 0, ["Prompt tokens", result.metrics.prompt_tokens]);
  get("metrics").replaceChildren(...values.map(([label, value]) => {
    const row = element("div");
    row.append(element("dt", label), element("dd", value));
    return row;
  }));
  get("metrics").hidden = false;
}

async function runReplay(event) {
  event.preventDefault();
  run.disabled = true;
  casePicker.disabled = true;
  modePicker.disabled = true;
  reset("RUNNING REPLAY");
  get("empty").querySelector("p").textContent = "Resolving the alert and selecting a diagnostic…";
  get("replay-status").textContent = "Replay running";
  try {
    const result = await json("/api/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case: casePicker.value, mode: modePicker.value }),
    });
    render(result);
    get("replay-status").textContent = result.status === "executed" ? "Replay completed" : "Replay completed without a tool call";
  } catch (error) {
    reset("REPLAY UNAVAILABLE");
    get("replay-status").textContent = error.message;
  } finally {
    get("empty").querySelector("p").textContent = "Run an alert to see the selected diagnostic and the graph behind it.";
    run.disabled = false;
    casePicker.disabled = false;
    modePicker.disabled = false;
  }
}

async function loadCases() {
  const data = await json("/api/cases");
  cases = new Map(data.map((record) => [record.id, record]));
  casePicker.replaceChildren(...data.map((record) => new Option(record.title, record.id)));
  run.disabled = !data.length;
  showCase();
}

async function showHealth() {
  const status = get("engine-status");
  const label = (text) => status.replaceChildren(element("span", null, "dot"), document.createTextNode(text));
  try {
    const health = await json("/health");
    label(health.decision === "ranked" ? "HydraDB · ranked" : health.model_configured ? "HydraDB ready" : "Model unconfigured");
    status.classList.add("ready");
  } catch {
    label("HydraDB unavailable");
  }
}

async function showBenchmark() {
  try {
    const benchmark = await json("/api/benchmark");
    const meta = benchmark.metadata;
    get("bench-meta").textContent = `${meta.holdout_cases} held-out replays · ${meta.model || meta.decision}`;
    get("bench-rows").replaceChildren(...benchmark.modes.map((row) => {
      const item = element("tr");
      for (const point of [
        row.label, `${row.correct} / ${row.total}`, row.median_schemas ?? "—",
        row.median_prompt_tokens == null ? "—" : `${Math.round(row.median_prompt_tokens)} tokens`,
        row.p95_ms == null ? "—" : `${Math.round(row.p95_ms)} ms`,
      ]) item.append(element("td", point));
      return item;
    }));
    get("curve").replaceChildren(...benchmark.curve.map((round) => {
      const item = element("li", `Round ${round.round} · ${round.training_cases} seen`);
      const bar = element("progress");
      bar.max = round.total;
      bar.value = round.correct;
      bar.setAttribute("aria-label", `Round ${round.round} correct first actions`);
      item.append(element("strong", `${round.correct} / ${round.total}`), bar);
      return item;
    }));
    get("bench-note").textContent = "Held-out cases share synthetic scenario families. Token medians use replays where the model was called.";
    const load = benchmark.graph_query_load?.at(-1);
    if (load) get("bench-load").textContent = `Graph load sample · ${load.requests} queries at concurrency ${load.concurrency} · p95 ${Math.round(load.p95_ms)} ms · ${load.errors} errors`;
    get("bench-content").hidden = false;
  } catch {
    get("bench-meta").textContent = "Evaluation results are unavailable for this build.";
  }
}

casePicker.addEventListener("change", showCase);
modePicker.addEventListener("change", showCase);
get("replay-form").addEventListener("submit", runReplay);
loadCases().catch((error) => { get("replay-status").textContent = error.message; });
showHealth();
showBenchmark();
