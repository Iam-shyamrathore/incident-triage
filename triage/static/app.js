const get = (id) => document.getElementById(id);
const casePicker = get("case-picker");
const modePicker = get("mode-picker");
const run = get("run");
let cases = new Map();
let services = [];
let inputMode = "custom";
let busy = false;
const KINDS = [
  ["trace", "Failed trace", "Paste a failed span or error"],
  ["latency", "p95 latency", "Milliseconds, e.g. 721"],
  ["health", "Dependency health", ""],
  ["error_counter", "Error counts", "Failed / total, e.g. 12/100"],
];

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail[0]?.msg?.replace(/^Value error, /, "") : payload.detail;
    throw new Error(typeof detail === "string" ? detail : "Could not complete the request.");
  }
  return payload;
}

function showCase() {
  const record = cases.get(casePicker.value);
  if (!record) return;
  get("alert-text").textContent = record.alert;
  get("case-service").textContent = `${record.service} · ${record.environment}`;
  reset("Ready for input");
  get("replay-status").textContent = "";
}

function chooseMode(mode) {
  if (busy) return;
  inputMode = mode;
  get("depth-tip").hidden = mode !== "custom";
  for (const [key, panel, button] of [
    ["custom", "custom-form", "open-custom"], ["examples", "example-form", "open-replays"],
  ]) {
    const active = mode === key;
    get(panel).hidden = !active;
    get(panel).disabled = !active;
    get(button).setAttribute("aria-pressed", active);
  }
  for (const option of modePicker.options) {
    if (option.value === "flat" || option.value === "preload") option.disabled = mode === "custom";
  }
  if (modePicker.selectedOptions[0]?.disabled) modePicker.value = "learned";
  if (mode === "examples") showCase();
  reset("Ready for input");
  get("replay-status").textContent = "";
  updateControls();
}

function selectOptions(select, options, current) {
  select.replaceChildren(...options.map(([value, title]) => new Option(title, value)));
  select.value = current;
}

function labeled(title, control) {
  const label = element("label", title);
  label.append(control);
  return label;
}

function addSignal({ service = get("custom-service").value, kind = "trace", value = "", age = 0 } = {}) {
  if (get("signal-rows").childElementCount >= 6) return;
  const group = element("div", null, "signal-row");
  const source = element("select");
  const kindPicker = element("select");
  selectOptions(source, services, service);
  selectOptions(kindPicker, KINDS, kind);
  const measurement = element("div");
  const ageInput = element("input");
  ageInput.type = "number";
  ageInput.min = 0;
  ageInput.max = 240;
  ageInput.required = true;
  ageInput.value = age;
  ageInput.dataset.name = "age";

  function updateMeasurement(initial = "") {
    const selected = kindPicker.value;
    const definition = KINDS.find(([id]) => id === selected);
    const control = element(selected === "health" ? "select" : "input");
    if (selected === "health") {
      selectOptions(control, [["degraded", "Degraded"], ["unavailable", "Unavailable"], ["healthy", "Healthy"]], initial || "unavailable");
    } else {
      control.placeholder = definition[2];
      control.value = initial;
      control.maxLength = 300;
      control.required = true;
      if (selected === "latency") control.inputMode = "numeric";
    }
    control.dataset.name = "value";
    measurement.replaceChildren(labeled(selected === "latency" ? "Value (ms)" : "Value", control));
  }

  const top = element("div", null, "input-pair");
  const bottom = element("div", null, "evidence-value");
  const remove = element("button", "Remove", "text-button remove-signal");
  remove.type = "button";
  remove.addEventListener("click", () => {
    group.remove();
    updateControls();
  });
  source.dataset.name = "service";
  kindPicker.dataset.name = "kind";
  top.append(labeled("Service", source), labeled("Measurement", kindPicker));
  bottom.append(measurement, labeled("Minutes ago", ageInput), remove);
  group.append(top, bottom);
  kindPicker.addEventListener("change", () => updateMeasurement());
  updateMeasurement(value);
  get("signal-rows").append(group);
  updateControls();
}

function loadSample() {
  get("custom-service").value = "checkoutservice";
  get("custom-alert").value = "Checkout requests are failing during payment.";
  get("custom-depth").value = "2";
  get("signal-rows").replaceChildren();
  addSignal({ service: "payment-gateway", kind: "trace", value: "The payment gateway span returned UNAVAILABLE." });
  reset("Ready for input");
  get("replay-status").textContent = "";
}

function updateControls() {
  get("add-signal").disabled = busy || !services.length || get("signal-rows").childElementCount >= 6;
  get("load-example").disabled = busy || !services.length;
  run.disabled = busy || (inputMode === "custom" ? !services.length : !cases.size);
}

function customPayload() {
  const signals = [...get("signal-rows").querySelectorAll(".signal-row")].map(row => {
    const read = name => row.querySelector(`[data-name="${name}"]`).value;
    return { service: read("service"), kind: read("kind"), value: read("value"), age: Number(read("age")) };
  });
  return {
    alert: get("custom-alert").value, service: get("custom-service").value,
    hop_limit: Number(get("custom-depth").value), signals, mode: modePicker.value,
  };
}

function reset(label) {
  get("trace-state").textContent = label;
  get("output").hidden = true;
  get("empty").hidden = false;
  get("metrics").hidden = true;
}

function summarizeFinding(data) {
  if (!data) return "";
  if (data.status !== "observed") return "The tool found no matching telemetry.";
  const evidence = data.evidence;
  if (evidence.trace) return evidence.trace;
  if (evidence.failed_requests != null) return `${evidence.failed_requests} of ${evidence.sampled_requests} sampled requests failed.`;
  if (evidence.p95_ms != null) return `The observed p95 latency was ${evidence.p95_ms} ms.`;
  if (evidence.connection_status) return `Connections are ${evidence.connection_status}.`;
  if (evidence.deployment) return `Release ${evidence.deployment.key} was visible before the alert.`;
  return evidence.log || "The tool returned an observation.";
}

function render(result) {
  const output = get("output");
  get("empty").hidden = true;
  output.hidden = false;
  const selection = result.selected;
  get("trace-state").textContent = selection ? "Check completed" : "Abstained";
  get("check-label").textContent = selection ? "First diagnostic" : "No diagnostic selected";
  get("action-title").textContent = selection ? selection.skill : "Wait for evidence";
  get("action-detail").textContent = selection
    ? [selection.service_name, selection.owner, selection.deploy,
      selection.confirmations ? `${selection.confirmations} verified earlier replays` : null].filter(Boolean).join(" · ")
    : result.explanation;

  get("finding").hidden = !result.tool_result;
  get("finding-text").textContent = summarizeFinding(result.tool_result);

  const reachable = result.reachable || [];
  get("reach").hidden = !reachable.length;
  get("reach-label").textContent = `Services HydraDB reached · ${reachable.length}`;
  get("reach-list").textContent = reachable.join(" · ");

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
    ["HydraDB reads", result.metrics.graph_calls],
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
  const custom = inputMode === "custom";
  const payload = custom ? customPayload() : { case: casePicker.value, mode: modePicker.value };
  busy = true;
  updateControls();
  get("custom-form").disabled = true;
  get("example-form").disabled = true;
  modePicker.disabled = true;
  reset("Running");
  get("trace-prompt").textContent = "Resolving the alert and selecting a diagnostic…";
  get("replay-status").textContent = "Running triage";
  try {
    const result = await json(custom ? "/api/sandbox" : "/api/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    render(result);
    get("replay-status").textContent = result.status === "executed" ? "Check completed" : "Completed without a tool call";
  } catch (error) {
    reset("Unavailable");
    get("replay-status").textContent = error.message;
  } finally {
    get("trace-prompt").textContent = "Run the incident to see which services HydraDB reaches and which diagnostic the agent runs.";
    busy = false;
    get("custom-form").disabled = !custom;
    get("example-form").disabled = custom;
    modePicker.disabled = false;
    updateControls();
  }
}

async function loadCases() {
  const data = await json("/api/cases");
  cases = new Map(data.map((record) => [record.id, record]));
  casePicker.replaceChildren(...data.map((record) => new Option(record.title, record.id)));
  if (inputMode === "examples") showCase();
  updateControls();
}

async function loadServices() {
  const data = await json("/api/services");
  services = data.map((service) => [service.key, service.name]);
  selectOptions(get("custom-service"), services, "checkoutservice");
  loadSample();
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

get("open-custom").addEventListener("click", () => chooseMode("custom"));
get("open-replays").addEventListener("click", () => chooseMode("examples"));
get("load-example").addEventListener("click", loadSample);
get("add-signal").addEventListener("click", () => addSignal());
casePicker.addEventListener("change", showCase);
modePicker.addEventListener("change", () => {
  reset("Ready for input");
  get("replay-status").textContent = "";
});
get("replay-form").addEventListener("submit", runReplay);
loadCases().catch((error) => { get("replay-status").textContent = error.message; });
loadServices().catch((error) => { get("replay-status").textContent = error.message; });
showHealth();
showBenchmark();
