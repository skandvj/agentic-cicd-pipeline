const state = {
  apiBase: window.location.origin,
  agents: [],
  health: null
};

const panels = [...document.querySelectorAll(".panel")];
const steps = [...document.querySelectorAll(".step")];
const apiBaseInput = document.querySelector("#apiBase");
const readinessList = document.querySelector("#readinessList");
const modeDot = document.querySelector("#modeDot");
const modeLabel = document.querySelector("#modeLabel");
const modeDetail = document.querySelector("#modeDetail");
const runtimeMode = document.querySelector("#runtimeMode");
const runtimeEnv = document.querySelector("#runtimeEnv");
const agentSelect = document.querySelector("#agentSelect");
const scenarioSelect = document.querySelector("#scenarioSelect");
const invokeMessage = document.querySelector("#invokeMessage");

apiBaseInput.value = state.apiBase;

steps.forEach((step) => {
  step.addEventListener("click", () => showPanel(step.dataset.step));
});

document.querySelector("#checkHealth").addEventListener("click", checkHealth);
document.querySelector("#invokeAgent").addEventListener("click", invokeAgent);
document.querySelector("#loadSummary").addEventListener("click", loadSummary);
document.querySelector("#loadTraces").addEventListener("click", loadTraces);
document.querySelector("#copyPitch").addEventListener("click", copyPitch);
scenarioSelect.addEventListener("change", () => {
  invokeMessage.value = scenarioSelect.value;
});

checkHealth();

function showPanel(id) {
  steps.forEach((step) => step.classList.toggle("is-active", step.dataset.step === id));
  panels.forEach((panel) => panel.classList.toggle("is-visible", panel.id === id));
  const titles = {
    connect: "Connect the runtime",
    invoke: "Run a live agent",
    evaluate: "Explain the eval gate",
    observe: "Inspect production signals",
    handoff: "Share the project"
  };
  document.querySelector("#panelTitle").textContent = titles[id] || "Control center";
}

async function checkHealth() {
  state.apiBase = apiBaseInput.value.replace(/\/$/, "") || window.location.origin;
  setStatus("Checking runtime", "Calling /health", "");
  try {
    const health = await fetchJson("/health");
    state.health = health;
    state.agents = health.agents || [];
    runtimeMode.textContent = health.mode || "unknown";
    runtimeEnv.textContent = health.environment || "environment";
    setStatus("Runtime connected", `${health.mode || "unknown"} mode`, "ok");
    renderAgents();
    renderReadiness(health);
  } catch (error) {
    runtimeMode.textContent = "-";
    runtimeEnv.textContent = "not connected";
    setStatus("Runtime unavailable", error.message, "bad");
    readinessList.innerHTML = "";
  }
}

function renderAgents() {
  agentSelect.innerHTML = "";
  const agents = state.agents.length ? state.agents : ["customer-support-agent", "sales-research-agent"];
  for (const agent of agents) {
    const option = document.createElement("option");
    option.value = agent;
    option.textContent = agent;
    agentSelect.append(option);
  }
}

function renderReadiness(health) {
  const items = [
    ["Runtime mode", health.mode === "production" ? "Production" : "Demo"],
    ["Agent catalog", `${(health.agents || []).length} agents available`],
    ["Provider path", health.mode === "production" ? "Live SDK calls required" : "Deterministic demo providers"],
    ["Persistence", health.mode === "production" ? "PostgreSQL required" : "In-memory demo storage"]
  ];
  readinessList.innerHTML = items.map(([label, value]) => (
    `<div class="check-item"><span>${label}</span><strong>${value}</strong></div>`
  )).join("");
}

async function invokeAgent() {
  const agent = agentSelect.value || "customer-support-agent";
  const payload = { message: invokeMessage.value };
  const output = document.querySelector("#invokeOutput");
  output.textContent = "Invoking...";
  try {
    output.textContent = JSON.stringify(await fetchJson(`/v1/agents/${agent}/invoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }), null, 2);
  } catch (error) {
    output.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

async function loadSummary() {
  const output = document.querySelector("#observabilityOutput");
  output.textContent = "Loading summary...";
  try {
    output.textContent = JSON.stringify(await fetchJson("/api/metrics/summary?period=24h"), null, 2);
  } catch (error) {
    output.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

async function loadTraces() {
  const output = document.querySelector("#observabilityOutput");
  output.textContent = "Loading traces...";
  try {
    output.textContent = JSON.stringify(await fetchJson("/api/traces?limit=5"), null, 2);
  } catch (error) {
    output.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

async function copyPitch() {
  const text = "Agentic CI/CD Pipeline: production infrastructure for AI agents with schema validation, live providers, tool backends, eval gates, trace storage, cost/latency metrics, and staged deployment controls.";
  await navigator.clipboard.writeText(text);
  document.querySelector("#copyPitch").textContent = "Copied";
}

async function fetchJson(path, options) {
  const response = await fetch(`${state.apiBase}${path}`, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function setStatus(label, detail, tone) {
  modeLabel.textContent = label;
  modeDetail.textContent = detail;
  modeDot.className = `status-dot ${tone || ""}`.trim();
}
