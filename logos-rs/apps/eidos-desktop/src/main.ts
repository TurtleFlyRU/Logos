import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./style.css";

interface PathsDto {
  repo_root: string;
  data_root: string;
  working_wm: string;
  agents_cfg: string | null;
}

interface LlmProfileDto {
  profile_name: string;
  model: string;
  base_url: string;
  read_timeout_sec: number;
}

interface ChatMessageDto {
  role: string;
  content: string;
  timestamp: number;
  tool_call_id?: string;
}

interface AppStateDto {
  session_id: string;
  paths: PathsDto;
  profile: LlmProfileDto;
  messages: ChatMessageDto[];
  stub: boolean;
}

interface SendMessageResult {
  reply: string;
  llm_status?: string;
  pipeline_text?: string;
  status_warning?: string;
}

interface SessionRecord {
  session_id: string;
  updated_at: number;
}

interface SettingsDto {
  paths: PathsDto;
  profile: LlmProfileDto;
  session_id: string;
  stub: boolean;
  agent_profile_env: string | null;
  desktop_stub_env: boolean;
  rust_boot: boolean;
  rust_context: boolean;
  sidecar_disabled: boolean;
}

interface SleepResult {
  output: string;
  exit_code: number;
}

interface ContextMetricsDto {
  total_budget: number;
  total_chars: number;
  approx_prompt_tokens: number;
  system_messages: number;
  history_messages: number;
  tool_messages: number;
  layers: Record<string, boolean>;
  layer_chars: Record<string, number>;
  layer_tokens: Record<string, number>;
  budget_report: string;
}

const app = document.getElementById("app")!;

app.innerHTML = `
  <header>
    <h1>Эйдос</h1>
    <span class="meta" id="meta">…</span>
    <button type="button" id="btn-env" title="Переменные окружения">Env</button>
    <button type="button" id="btn-budget" title="Метрики слоёв и бюджет">Контекст</button>
    <button type="button" id="btn-pipelines" title="Справка /pipeline">Пайплайны</button>
    <button type="button" id="btn-boot">Boot</button>
    <button type="button" id="btn-sleep" title="python3 eidos.py sleep">Сон</button>
    <button type="button" id="btn-settings" title="Профиль и пути">Настройки</button>
    <button type="button" id="btn-agents" title="Редактировать agents.yaml">agents</button>
    <button type="button" class="primary" id="btn-new">Новая сессия</button>
  </header>
  <aside class="sessions-panel">
    <h2>Сессии</h2>
    <div id="sessions"></div>
  </aside>
  <main class="chat-panel">
    <div id="messages"></div>
    <div id="loading" class="loading hidden">Запрос к модели…</div>
  </main>
  <aside class="context-panel hidden" id="context-panel">
    <div class="context-head">
      <h2 id="context-title">Контекст</h2>
      <button type="button" id="btn-context-close" aria-label="Закрыть">×</button>
    </div>
    <div id="context-body" class="context-body"></div>
  </aside>
  <aside class="context-panel agents-panel hidden" id="agents-panel">
    <div class="context-head">
      <h2>agents.yaml</h2>
      <button type="button" id="btn-agents-close" aria-label="Закрыть">×</button>
    </div>
    <p id="agents-meta" class="agents-meta"></p>
    <textarea id="agents-editor" class="agents-editor" spellcheck="false"></textarea>
    <div class="agents-actions">
      <button type="button" class="primary" id="btn-agents-save">Сохранить</button>
      <button type="button" id="btn-agents-reload">Перечитать</button>
    </div>
  </aside>
  <footer>
    <textarea
      id="input"
      rows="2"
      lang="ru"
      autocapitalize="off"
      autocomplete="off"
      spellcheck="true"
      placeholder="Сообщение… (/pipeline, /run, /review)"
    ></textarea>
    <button type="button" id="btn-send">Отправить</button>
  </footer>
  <p class="ime-hint" id="ime-hint"></p>
`;

const metaEl = document.getElementById("meta")!;
const sessionsEl = document.getElementById("sessions")!;
const messagesEl = document.getElementById("messages")!;
const loadingEl = document.getElementById("loading")!;
const inputEl = document.getElementById("input") as HTMLTextAreaElement;
const btnSend = document.getElementById("btn-send") as HTMLButtonElement;
const btnBoot = document.getElementById("btn-boot") as HTMLButtonElement;
const btnNew = document.getElementById("btn-new")!;
const btnEnv = document.getElementById("btn-env")!;
const btnBudget = document.getElementById("btn-budget")!;
const btnPipelines = document.getElementById("btn-pipelines")!;
const btnSleep = document.getElementById("btn-sleep") as HTMLButtonElement;
const btnSettings = document.getElementById("btn-settings")!;
const btnAgents = document.getElementById("btn-agents")!;
const contextPanel = document.getElementById("context-panel")!;
const contextTitle = document.getElementById("context-title")!;
const contextBody = document.getElementById("context-body") as HTMLDivElement;
const btnContextClose = document.getElementById("btn-context-close")!;
const agentsPanel = document.getElementById("agents-panel")!;
const agentsMeta = document.getElementById("agents-meta")!;
const agentsEditor = document.getElementById("agents-editor") as HTMLTextAreaElement;
const btnAgentsClose = document.getElementById("btn-agents-close")!;
const btnAgentsSave = document.getElementById("btn-agents-save")!;
const btnAgentsReload = document.getElementById("btn-agents-reload")!;

let currentSession = "";
let composing = false;
let streamAssistantEl: HTMLDivElement | null = null;
let streamText = "";
/** Очередь отрисовки дельт: не чаще одного кадра (меньше нагрузки на WebKit/WSL). */
let streamFlushRafId: number | null = null;

interface ChatStreamDeltaPayload {
  session_id: string;
  delta: string;
}

interface ChatStreamEndPayload {
  session_id: string;
  result: SendMessageResult;
}

interface AgentsEditorState {
  content: string;
  active_file: string;
  save_target: string;
}

function showContext(title: string, body: string) {
  hideAgentsPanel();
  app.classList.remove("context-budget-wide");
  contextTitle.textContent = title;
  contextBody.className = "context-body context-body-plain";
  contextBody.textContent = body;
  contextPanel.classList.remove("hidden");
  app.classList.add("context-open");
}

function hideContext() {
  contextPanel.classList.add("hidden");
  app.classList.remove("context-open");
  app.classList.remove("context-budget-wide");
}

function hideAgentsPanel() {
  agentsPanel.classList.add("hidden");
  app.classList.remove("agents-open");
}

async function openAgentsEditor() {
  hideContext();
  try {
    const st = await invoke<AgentsEditorState>("get_agents_editor_state");
    agentsEditor.value = st.content;
    agentsMeta.textContent = `Сейчас читается: ${st.active_file}\nСохранение → ${st.save_target}`;
    agentsPanel.classList.remove("hidden");
    app.classList.add("agents-open");
  } catch (e) {
    appendStatus(`agents.yaml: ${e}`);
  }
}

function setLoading(on: boolean) {
  loadingEl.classList.toggle("hidden", !on);
  btnSend.disabled = on;
  inputEl.disabled = on;
}

function setupInput() {
  inputEl.lang = "ru";
  inputEl.setAttribute("inputmode", "text");
  inputEl.focus();

  inputEl.addEventListener("compositionstart", () => {
    composing = true;
  });
  inputEl.addEventListener("compositionend", () => {
    composing = false;
  });

  inputEl.addEventListener("keydown", (ev) => {
    if (composing || ev.isComposing || ev.keyCode === 229) return;
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      void send();
    }
  });

  const hint = document.getElementById("ime-hint");
  if (hint) {
    hint.textContent =
      "Enter — отправить · Shift+Enter — новая строка · в чате работают /pipeline, /run, /review как в CLI";
  }
}

function renderMessages(messages: ChatMessageDto[]) {
  messagesEl.innerHTML = "";
  for (const m of messages) {
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    div.textContent = m.content;
    messagesEl.appendChild(div);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendStatus(text: string) {
  const div = document.createElement("div");
  div.className = "msg status";
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendUserBubble(text: string) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function cancelStreamDomFlush() {
  if (streamFlushRafId !== null) {
    cancelAnimationFrame(streamFlushRafId);
    streamFlushRafId = null;
  }
}

function flushStreamDomNow() {
  if (!streamAssistantEl) return;
  streamAssistantEl.textContent = streamText;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function scheduleStreamDomFlush() {
  if (streamFlushRafId !== null) return;
  streamFlushRafId = requestAnimationFrame(() => {
    streamFlushRafId = null;
    flushStreamDomNow();
  });
}

function beginAssistantStream() {
  cancelStreamDomFlush();
  streamText = "";
  streamAssistantEl = document.createElement("div");
  streamAssistantEl.className = "msg assistant streaming";
  streamAssistantEl.textContent = "";
  messagesEl.appendChild(streamAssistantEl);
  streamAssistantEl.textContent = "…";
}

function setupChatStreamListeners() {
  void listen<{ session_id: string }>("chat-stream-start", (ev) => {
    if (ev.payload.session_id !== currentSession) return;
    beginAssistantStream();
  });

  void listen<ChatStreamDeltaPayload>("chat-stream-delta", (ev) => {
    if (ev.payload.session_id !== currentSession) return;
    if (streamAssistantEl && streamText.length === 0 && ev.payload.delta.length > 0) {
      streamAssistantEl.textContent = "";
      loadingEl.classList.add("hidden");
    }
    streamText += ev.payload.delta;
    scheduleStreamDomFlush();
  });

  void listen<ChatStreamEndPayload>("chat-stream-end", async (ev) => {
    if (ev.payload.session_id !== currentSession) return;
    cancelStreamDomFlush();
    streamAssistantEl = null;
    const res = ev.payload.result;
    await refreshState();
    loadingEl.classList.add("hidden");
    if (res.llm_status) appendStatus(res.llm_status);
    if (res.status_warning) appendStatus(res.status_warning);
    if (res.pipeline_text) appendStatus(res.pipeline_text);
  });

  void listen<{ session_id: string; message: string }>("chat-stream-error", (ev) => {
    if (ev.payload.session_id !== currentSession) return;
    cancelStreamDomFlush();
    streamAssistantEl = null;
    appendStatus(`Ошибка: ${ev.payload.message}`);
  });
}

async function refreshState() {
  const state = await invoke<AppStateDto>("get_app_state");
  currentSession = state.session_id;
  const cfg = state.paths.agents_cfg ?? "—";
  metaEl.textContent = `${state.profile.profile_name} · ${state.profile.model} · ${state.session_id.slice(0, 8)}…`;
  metaEl.title = `agents: ${cfg}\nbase: ${state.profile.base_url}`;
  renderMessages(state.messages);
  await refreshSessions();
}

async function refreshSessions() {
  const list = await invoke<SessionRecord[]>("list_sessions");
  sessionsEl.innerHTML = "";
  for (const s of list.slice(0, 40)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "session-item" + (s.session_id === currentSession ? " active" : "");
    const d = new Date(s.updated_at * 1000);
    btn.innerHTML = `${s.session_id.slice(0, 8)}…<small>${d.toLocaleString()}</small>`;
    btn.onclick = async () => {
      await invoke("switch_session", { sessionId: s.session_id });
      await refreshState();
    };
    sessionsEl.appendChild(btn);
  }
}

async function send() {
  const text = inputEl.value.trim();
  if (!text) return;

  const low = text.toLowerCase();
  if (low === "/env" || low === "/env all") {
    inputEl.value = "";
    const body = await invoke<string>("get_env_report", { activeOnly: false });
    showContext("Env", body);
    return;
  }
  if (low === "/env active") {
    inputEl.value = "";
    const body = await invoke<string>("get_env_report", { activeOnly: true });
    showContext("Env (active)", body);
    return;
  }
  if (low.startsWith("/budget")) {
    inputEl.value = "";
    await showContextMetrics();
    return;
  }
  if (low === "/pipeline help" || low === "/pipeline") {
    inputEl.value = "";
    const body = await invoke<string>("get_pipeline_help");
    showContext("Пайплайны", body);
    return;
  }

  inputEl.value = "";
  appendUserBubble(text);
  setLoading(true);
  loadingEl.classList.remove("hidden");

  try {
    await invoke("send_message", { text });
  } catch (e) {
    cancelStreamDomFlush();
    streamAssistantEl = null;
    appendStatus(`Ошибка: ${e}`);
    await refreshState();
  } finally {
    setLoading(false);
    loadingEl.classList.add("hidden");
    inputEl.focus();
  }
}

btnSend.onclick = () => void send();
setupInput();
setupChatStreamListeners();

btnBoot.onclick = async () => {
  btnBoot.disabled = true;
  try {
    await invoke("run_boot");
    appendStatus("[eidos] Boot выполнен.");
  } catch (e) {
    appendStatus(`Boot: ${e}`);
  } finally {
    btnBoot.disabled = false;
  }
};

btnNew.onclick = async () => {
  setLoading(true);
  try {
    await invoke("new_session", { clearWm: true, runBoot: true });
    await refreshState();
    hideContext();
  } finally {
    setLoading(false);
  }
};

btnEnv.onclick = async () => {
  try {
    const body = await invoke<string>("get_env_report", { activeOnly: false });
    showContext("Env", body);
  } catch (e) {
    showContext("Env", String(e));
  }
};

/** Подписи слоёв контекста (ключи из Python/Rust). */
const LAYER_LABELS: Record<string, string> = {
  persona: "Персона",
  identity: "Identity",
  wm_plan_focus: "План WM",
  attention: "Внимание",
  active_memory: "Активная память",
  boot_snippet: "Boot",
  principles: "Принципы",
  other: "Прочее",
  history: "История",
  wm_summary: "Сводка WM",
};

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showBudgetPanel(m: ContextMetricsDto, draftHint: string) {
  hideAgentsPanel();
  app.classList.add("context-budget-wide");
  contextTitle.textContent = "Контекст · бюджет";
  contextBody.className = "context-body context-body-budget";
  contextBody.innerHTML = buildBudgetHtml(m, draftHint);
  contextPanel.classList.remove("hidden");
  app.classList.add("context-open");
}

function buildBudgetHtml(m: ContextMetricsDto, draftHint: string): string {
  const budget = m.total_budget;
  const used = Math.max(0, m.total_chars);
  /** При uncapped бюджете полосы слоёв считают долю от текущего промпта, иначе — от лимита. */
  const layerDenominator = budget > 0 ? budget : Math.max(used, 1);
  const pctFill = budget > 0 ? Math.min(100, (used / budget) * 100) : 0;
  const pctStr = budget > 0 ? pctFill.toFixed(1) : "—";
  const free = budget > 0 ? Math.max(0, budget - used) : 0;
  const over = budget > 0 && used > budget;

  const layerOrder = [
    "persona",
    "identity",
    "wm_plan_focus",
    "attention",
    "active_memory",
    "boot_snippet",
    "principles",
    "other",
    "history",
    "wm_summary",
  ];

  const layerRows: string[] = [];
  for (const key of layerOrder) {
    const ch = m.layer_chars[key];
    if (!ch) continue;
    const tok = m.layer_tokens[key] ?? 0;
    const on = m.layers[key];
    const onLabel = on === undefined ? "" : on ? "вкл." : "выкл.";
    const label = LAYER_LABELS[key] ?? key;
    const barPct = Math.min(100, (ch / layerDenominator) * 100);
    const barClass =
      barPct > 85 ? "budget-bar-fill budget-bar-fill-high" : "budget-bar-fill";
    const shareHint =
      budget <= 0
        ? ` · ${barPct.toFixed(1)}% промпта`
        : "";
    layerRows.push(`<div class="budget-layer">
      <div class="budget-layer-head">
        <span class="budget-layer-name">${escapeHtml(label)} <code>${escapeHtml(key)}</code></span>
        <span class="budget-layer-meta">${ch.toLocaleString()} симв. · ~${tok.toLocaleString()} tok${onLabel ? ` · ${escapeHtml(onLabel)}` : ""}${shareHint}</span>
      </div>
      <div class="budget-bar-track"><div class="${barClass}" style="width:${barPct.toFixed(1)}%"></div></div>
    </div>`);
  }

  const draftBlock = draftHint
    ? `<p class="budget-draft-hint">${escapeHtml(draftHint)}</p>`
    : "";

  const mainBarClass = over
    ? "budget-bar-fill budget-bar-fill-over"
    : pctFill > 85
      ? "budget-bar-fill budget-bar-fill-high"
      : "budget-bar-fill";

  const uncappedHint =
    budget <= 0
      ? `<p class="budget-uncapped-hint">Лимит символов не задан (<code>EIDOS_CHAT_TOTAL_CHARS</code>). Ниже — <strong>доля каждого слоя</strong> от текущего размера промпта (${used.toLocaleString()} симв.); общий «% заполнения» к лимиту недоступен.</p>`
      : "";

  const mainBarBlock =
    budget > 0
      ? `<div class="budget-bar-track budget-bar-total"><div class="${mainBarClass}" style="width:${Math.min(100, pctFill).toFixed(1)}%"></div></div>`
      : "";

  const reportRaw = m.budget_report?.trim() || "—";
  const reportHtml = escapeHtml(reportRaw);

  return `<div class="budget-root">
    ${draftBlock}
    ${uncappedHint}
    <section class="budget-summary">
      <div class="budget-stat">
        <span class="budget-stat-label">Символов в промпте</span>
        <span class="budget-stat-value">${used.toLocaleString()} / ${budget > 0 ? budget.toLocaleString() : "∞"}</span>
      </div>
      <div class="budget-stat">
        <span class="budget-stat-label">Заполнение лимита</span>
        <span class="budget-stat-value ${over ? "budget-over" : ""}">${budget > 0 ? `${pctStr}%` : "—"}</span>
      </div>
      <div class="budget-stat">
        <span class="budget-stat-label">Свободно</span>
        <span class="budget-stat-value">${budget > 0 ? free.toLocaleString() : "—"} симв.</span>
      </div>
      <div class="budget-stat">
        <span class="budget-stat-label">≈ Токены</span>
        <span class="budget-stat-value">~${m.approx_prompt_tokens.toLocaleString()}</span>
      </div>
    </section>
    ${mainBarBlock}
    <section class="budget-wm-msg">
      <h3 class="budget-section-title">События в промпте</h3>
      <div class="budget-chips">
        <span class="budget-chip">system <strong>${m.system_messages}</strong></span>
        <span class="budget-chip">история <strong>${m.history_messages}</strong></span>
        <span class="budget-chip">tool <strong>${m.tool_messages}</strong></span>
      </div>
    </section>
    <section class="budget-layers">
      <h3 class="budget-section-title">Слои system / extra</h3>
      ${layerRows.length ? layerRows.join("") : "<p class=\"budget-muted\">Нет данных по слоям (возможно, бюджет не задан).</p>"}
    </section>
    <details class="budget-details">
      <summary>Полный текст отчёта /budget (sidecar)</summary>
      <pre class="budget-report-pre">${reportHtml}</pre>
    </details>
  </div>`;
}

async function showContextMetrics() {
  try {
    const draft = inputEl.value.trim();
    const m = await invoke<ContextMetricsDto>("get_context_metrics", {
      userMessage: draft || null,
    });
    const hint = draft
      ? "В метриках учтён черновик в поле ввода (как следующее пользовательское сообщение)."
      : "";
    showBudgetPanel(m, hint);
  } catch (e) {
    showContext("Контекст", String(e));
  }
}

btnBudget.onclick = () => void showContextMetrics();

btnPipelines.onclick = async () => {
  try {
    const body = await invoke<string>("get_pipeline_help");
    showContext("Пайплайны", body);
  } catch (e) {
    showContext("Пайплайны", String(e));
  }
};

btnContextClose.onclick = () => hideContext();

function formatSettings(s: SettingsDto): string {
  const lines = [
    "Профиль LLM",
    `  имя: ${s.profile.profile_name}`,
    `  модель: ${s.profile.model}`,
    `  base_url: ${s.profile.base_url}`,
    `  timeout: ${s.profile.read_timeout_sec}s`,
    "",
    "Сессия",
    `  id: ${s.session_id}`,
    `  stub (desktop): ${s.stub ? "да" : "нет"}`,
    "",
    "Пути",
    `  repo: ${s.paths.repo_root}`,
    `  data: ${s.paths.data_root}`,
    `  WM: ${s.paths.working_wm}`,
    `  agents: ${s.paths.agents_cfg ?? "—"}`,
    "",
    "Переменные (только при старте приложения)",
    `  EIDOS_AGENT_PROFILE: ${s.agent_profile_env ?? "—"}`,
    `  EIDOS_DESKTOP_STUB: ${s.desktop_stub_env ? "да" : "нет"}`,
    `  EIDOS_RUST_BOOT: ${s.rust_boot ? "да" : "нет"}`,
    `  EIDOS_RUST_CONTEXT: ${s.rust_context ? "да" : "нет"}`,
    `  EIDOS_RUST_NO_SIDECAR: ${s.sidecar_disabled ? "да" : "нет"}`,
    "",
    "Секреты API не показываются. Смена профиля — перезапуск с новым EIDOS_AGENT_PROFILE.",
  ];
  return lines.join("\n");
}

btnSleep.onclick = async () => {
  if (
    !window.confirm(
      "Запустить sleep-пайплайн памяти?\n\nСжатие эпизодов и обновление журнала.",
    )
  ) {
    return;
  }
  const useForce = window.confirm("Добавить --force (игнорировать lock)?");
  btnSleep.disabled = true;
  setLoading(true);
  try {
    const res = await invoke<SleepResult>("run_sleep", { force: useForce });
    const title = res.exit_code === 0 ? "Сон завершён" : `Сон (код ${res.exit_code})`;
    showContext(title, res.output || "(пустой вывод)");
  } catch (e) {
    showContext("Сон — ошибка", String(e));
  } finally {
    btnSleep.disabled = false;
    setLoading(false);
  }
};

btnSettings.onclick = async () => {
  try {
    const s = await invoke<SettingsDto>("get_settings");
    showContext("Настройки", formatSettings(s));
  } catch (e) {
    showContext("Настройки", String(e));
  }
};

btnAgents.onclick = () => void openAgentsEditor();

btnAgentsClose.onclick = () => hideAgentsPanel();

btnAgentsReload.onclick = () => void openAgentsEditor();

btnAgentsSave.onclick = async () => {
  try {
    await invoke("save_agents_config", { content: agentsEditor.value });
    appendStatus(
      "[eidos] agents.yaml сохранён. Параметры LLM подхватываются с диска на следующий запрос; шапка обновлена.",
    );
    await refreshState();
    await openAgentsEditor();
  } catch (e) {
    appendStatus(`Сохранение agents: ${e}`);
  }
};

void refreshState().catch((e) => {
  metaEl.textContent = `Ошибка: ${e}`;
});
