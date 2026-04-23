// MyAgentForge frontend.
// - API key + base URL + model: stored in localStorage (browser-only)
// - Projects + history: stored in IndexedDB (browser-only)
// - Keys are sent to the server per WebSocket request and NEVER persisted server-side.

import * as DB from "/static/db.js";

const LS_API_KEY = "maf.llm.api_key";
const LS_BASE_URL = "maf.llm.base_url";
const LS_MODEL = "maf.llm.model";
const LS_SESSION_ONLY = "maf.session_only";  // "1" => store key in sessionStorage (wiped on tab close)

let ws = null;
let isRunning = false;
let currentProject = null;       // full project object from IndexedDB
let currentFiles = {};           // files generated this run
let accumulatedMessages = [];    // messages accumulated during current task
let streamingMessages = {};      // msg_id -> {text, el, body}
let serverMode = "prod";

const PROGRESS_MAP = {
    pending: 5, planning: 20, coding: 45, reviewing: 65,
    fixing: 55, testing: 85, debugging: 70,
    completed: 100, failed: 100,
};


// ============================================================
// LLM config (stored locally — localStorage OR sessionStorage if "clear on close" is on)
// ============================================================
function isSessionOnly() {
    // Preference itself is in localStorage so it survives restarts
    return localStorage.getItem(LS_SESSION_ONLY) === "1";
}

function keyStore() {
    // The KEY is kept in either sessionStorage or localStorage based on the preference.
    // base_url and model are always in localStorage (not sensitive).
    return isSessionOnly() ? sessionStorage : localStorage;
}

function getLLMConfig() {
    return {
        api_key: keyStore().getItem(LS_API_KEY) || "",
        base_url: localStorage.getItem(LS_BASE_URL) || "",
        model: localStorage.getItem(LS_MODEL) || "",
    };
}

function saveLLMConfig(cfg) {
    if (cfg.api_key !== undefined) {
        // Ensure the key only exists in the chosen store
        const store = keyStore();
        const other = store === localStorage ? sessionStorage : localStorage;
        other.removeItem(LS_API_KEY);
        store.setItem(LS_API_KEY, cfg.api_key);
    }
    if (cfg.base_url !== undefined) localStorage.setItem(LS_BASE_URL, cfg.base_url);
    if (cfg.model !== undefined) localStorage.setItem(LS_MODEL, cfg.model);
}

function clearLLMConfig() {
    localStorage.removeItem(LS_API_KEY);
    sessionStorage.removeItem(LS_API_KEY);
    localStorage.removeItem(LS_BASE_URL);
    localStorage.removeItem(LS_MODEL);
}

function setSessionOnly(on) {
    if (on) {
        localStorage.setItem(LS_SESSION_ONLY, "1");
        // Migrate any currently-stored key from localStorage to sessionStorage
        const existing = localStorage.getItem(LS_API_KEY);
        if (existing) {
            sessionStorage.setItem(LS_API_KEY, existing);
            localStorage.removeItem(LS_API_KEY);
        }
    } else {
        localStorage.removeItem(LS_SESSION_ONLY);
        // Migrate key from sessionStorage to localStorage
        const existing = sessionStorage.getItem(LS_API_KEY);
        if (existing) {
            localStorage.setItem(LS_API_KEY, existing);
            sessionStorage.removeItem(LS_API_KEY);
        }
    }
}

function maskKey(k) {
    if (!k) return "—";
    if (k.length < 10) return "***";
    return k.slice(0, 6) + "..." + k.slice(-4);
}


// ============================================================
// WebSocket
// ============================================================
function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById("connectionDot").classList.add("connected");
        document.getElementById("connectionStatus").textContent = "Connected";
    };

    ws.onclose = () => {
        document.getElementById("connectionDot").classList.remove("connected");
        document.getElementById("connectionStatus").textContent = "Disconnected";
        setTimeout(connect, 2000);
    };

    ws.onmessage = (e) => {
        let event;
        try { event = JSON.parse(e.data); } catch { return; }
        handleEvent(event);
    };
}

function handleEvent(event) {
    switch (event.type) {
        case "agent_status":
            updateAgentStatus(event.data.agent, event.data.status);
            break;
        case "message":
            addMessage(event.data.sender, event.data.receiver, event.data.content);
            break;
        case "stream_start":
            startStreamingMessage(event.data.sender, event.data.receiver, event.data.msg_id);
            break;
        case "stream":
            appendToStreamingMessage(event.data.msg_id, event.data.chunk);
            break;
        case "stream_end":
            endStreamingMessage(event.data.msg_id);
            break;
        case "task_status":
            updateProgress(event.data.status);
            break;
        case "code_output":
            currentFiles = event.data.files;
            renderCode(event.data.files);
            document.getElementById("downloadBtn").style.display = "flex";
            break;
        case "error":
            addMessage("system", "user", "Error: " + event.data.message);
            resetUI();
            break;
    }
}

function updateAgentStatus(agent, status) {
    const card = document.getElementById(`agent-${agent}`);
    if (!card) return;
    card.className = "agent-card " + status;
    card.querySelector(".agent-status").textContent =
        status === "working" ? "Working..." : status.charAt(0).toUpperCase() + status.slice(1);
}

function ensureStream() {
    const stream = document.getElementById("messagesStream");
    const emptyState = stream.querySelector(".empty-state");
    if (emptyState) emptyState.remove();
    return stream;
}

function addMessage(sender, receiver, content) {
    const stream = ensureStream();
    const displayContent = content.length > 800 ? content.substring(0, 800) + "\n... (truncated)" : content;

    const msg = document.createElement("div");
    msg.className = "message";
    msg.innerHTML = `
        <div class="message-header">
            <span class="message-sender sender-${sender}">${escapeHtml(sender)}</span>
            <span class="message-arrow">&#10132;</span>
            <span class="message-receiver">${escapeHtml(receiver)}</span>
        </div>
        <div class="message-body"></div>
    `;
    msg.querySelector(".message-body").textContent = displayContent;
    stream.appendChild(msg);
    stream.scrollTop = stream.scrollHeight;

    accumulatedMessages.push({ sender, receiver, content });
}

function startStreamingMessage(sender, receiver, msgId) {
    const stream = ensureStream();
    const msg = document.createElement("div");
    msg.className = "message streaming";
    msg.innerHTML = `
        <div class="message-header">
            <span class="message-sender sender-${sender}">${escapeHtml(sender)}</span>
            <span class="message-arrow">&#10132;</span>
            <span class="message-receiver">${escapeHtml(receiver)}</span>
        </div>
        <div class="message-body"></div>
    `;
    stream.appendChild(msg);
    stream.scrollTop = stream.scrollHeight;
    streamingMessages[msgId] = {
        element: msg,
        body: msg.querySelector(".message-body"),
        text: "",
        sender, receiver,
    };
}

function appendToStreamingMessage(msgId, chunk) {
    const msg = streamingMessages[msgId];
    if (!msg) return;
    msg.text += chunk;
    msg.body.textContent = msg.text.length > 800 ? "..." + msg.text.slice(-800) : msg.text;
    const stream = document.getElementById("messagesStream");
    stream.scrollTop = stream.scrollHeight;
}

function endStreamingMessage(msgId) {
    const msg = streamingMessages[msgId];
    if (!msg) return;
    msg.element.classList.remove("streaming");
    accumulatedMessages.push({ sender: msg.sender, receiver: msg.receiver, content: msg.text });
    delete streamingMessages[msgId];
}

async function updateProgress(status) {
    const bar = document.getElementById("progressBar");
    const fill = document.getElementById("progressFill");
    const label = document.getElementById("progressLabel");

    bar.classList.add("active");
    fill.style.width = (PROGRESS_MAP[status] || 0) + "%";
    label.textContent = status.replace("_", " ");

    if (status === "completed" || status === "failed") {
        fill.style.background = status === "completed"
            ? "linear-gradient(90deg, #4ecdc4, #6bff6b)"
            : "#ff4444";
        label.style.color = status === "completed" ? "#4ecdc4" : "#ff4444";

        // Persist to IndexedDB
        if (currentProject) {
            currentProject.messages = [...accumulatedMessages];
            if (Object.keys(currentFiles).length) currentProject.files = currentFiles;
            currentProject.runs = currentProject.runs || [];
            currentProject.runs.push({
                task: document.getElementById("taskInput").dataset.lastTask || "",
                status: status,
                completed_at: Date.now(),
            });
            try {
                await DB.updateProject(currentProject);
                await refreshHistory();
                updateStorageMeter();
            } catch (e) {
                console.error("Failed to save project:", e);
            }
        }

        // Clear currentProject so the NEXT task creates a new project (not a follow-up).
        // The finished project stays in history and can be reopened from there.
        currentProject = null;
        hideProjectIndicator();
        document.getElementById("taskInput").placeholder = "Describe a software engineering task...";

        resetUI();
    }
}

function getLang(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    const map = { py: "python", js: "javascript", html: "markup", css: "css", json: "json", sh: "bash", bash: "bash", md: "markdown" };
    return map[ext] || "none";
}

function renderCode(files) {
    const output = document.getElementById("codeOutput");
    output.innerHTML = "";
    for (const [filename, code] of Object.entries(files)) {
        const lang = getLang(filename);
        const fileEl = document.createElement("div");
        fileEl.className = "code-file";

        const header = document.createElement("div");
        header.className = "code-file-header";
        header.innerHTML = `<span class="code-filename">${escapeHtml(filename)}</span><button class="code-copy-btn">Copy</button>`;
        header.querySelector(".code-copy-btn").addEventListener("click", (e) => copyCode(e.target));

        const pre = document.createElement("pre");
        pre.className = `language-${lang}`;
        const codeTag = document.createElement("code");
        codeTag.className = `language-${lang}`;
        codeTag.textContent = code;
        pre.appendChild(codeTag);

        fileEl.appendChild(header);
        fileEl.appendChild(pre);
        output.appendChild(fileEl);

        if (window.Prism) Prism.highlightElement(codeTag);
    }
    renderPreview(files);
}

function renderPreview(files) {
    const preview = document.getElementById("previewOutput");
    const names = Object.keys(files);
    const htmlName = names.find(f => /^(index|main)\.html?$/i.test(f)) || names.find(f => /\.html?$/i.test(f));
    const htmlFile = htmlName ? files[htmlName] : null;

    if (!htmlFile) {
        preview.innerHTML = `<div class="empty-state"><span>&#128196;</span><p>No HTML file to preview</p></div>`;
        return;
    }

    let inlined = htmlFile;
    for (const [fname, content] of Object.entries(files)) {
        if (fname === htmlName) continue;
        if (fname.endsWith(".css")) {
            inlined = inlined.replace(new RegExp(`<link[^>]*href=["']?${escapeRegex(fname)}["']?[^>]*>`, "gi"), `<style>${content}</style>`);
        } else if (fname.endsWith(".js")) {
            inlined = inlined.replace(new RegExp(`<script[^>]*src=["']?${escapeRegex(fname)}["']?[^>]*>\\s*</script>`, "gi"), `<script>${content}<\/script>`);
        }
    }

    const blob = new Blob([inlined], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    preview.innerHTML = `
        <div class="preview-toolbar">
            <span class="preview-url">&#128279; ${escapeHtml(htmlName)}</span>
            <button class="code-copy-btn" id="openNewTabBtn">Open in new tab</button>
        </div>
        <iframe class="preview-frame" src="${url}" sandbox="allow-scripts allow-forms"></iframe>
    `;
    document.getElementById("openNewTabBtn").addEventListener("click", () => window.open(url, "_blank"));
}

function copyCode(btn) {
    const pre = btn.closest(".code-file").querySelector("pre");
    const code = pre.querySelector("code")?.textContent || pre.textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    });
}

async function downloadZip() {
    if (!Object.keys(currentFiles).length) return;
    const btn = document.getElementById("downloadBtn");
    btn.disabled = true;
    btn.innerHTML = "<span>&#8635;</span> Preparing...";
    try {
        const res = await fetch("/download-zip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files: currentFiles }),
        });
        if (!res.ok) throw new Error("Download failed");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "myagentforge-output.zip";
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert("Download failed: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = "<span>&#11015;</span> ZIP";
    }
}


// ============================================================
// Submit task
// ============================================================
async function submitTask() {
    const input = document.getElementById("taskInput");
    const task = input.value.trim();
    if (!task) { alert("Please enter a task"); return; }
    if (!ws || ws.readyState !== WebSocket.OPEN) { alert("Not connected. Check the server is running."); return; }
    if (isRunning) { alert("A task is running. Click Stop first."); return; }

    const cfg = getLLMConfig();
    if (serverMode !== "mock" && !cfg.api_key) {
        alert("No API key set. Click the gear icon to add your LLM API key (stored only in your browser).");
        openSettings();
        return;
    }

    isRunning = true;
    accumulatedMessages = [];
    streamingMessages = {};
    currentFiles = {};
    input.dataset.lastTask = task;

    // Create or append to project
    if (!currentProject) {
        currentProject = await DB.createProject(task);
        showProjectIndicator(currentProject.title);
    }

    document.getElementById("runBtn").style.display = "none";
    document.getElementById("stopBtn").style.display = "flex";
    document.getElementById("downloadBtn").style.display = "none";
    document.getElementById("messagesStream").innerHTML = "";
    document.getElementById("codeOutput").innerHTML = '<div class="empty-state"><span>&#128196;</span><p>Code will appear here</p></div>';
    document.getElementById("previewOutput").innerHTML = '<div class="empty-state"><span>&#128065;</span><p>Preview will appear here</p></div>';
    document.querySelectorAll(".agent-card").forEach(c => {
        c.className = "agent-card";
        c.querySelector(".agent-status").textContent = "Idle";
    });
    const fill = document.getElementById("progressFill");
    fill.style.width = "0%";
    fill.style.background = "linear-gradient(90deg, var(--accent), #4ecdc4)";
    document.getElementById("progressLabel").style.color = "";

    ws.send(JSON.stringify({
        action: "run",
        task,
        llm_config: serverMode === "mock" ? {} : cfg,
    }));
}

function stopTask() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ action: "cancel" }));
}

function useTemplate(task) {
    document.getElementById("taskInput").value = task;
    submitTask();
}

function resetUI() {
    isRunning = false;
    document.getElementById("runBtn").style.display = "flex";
    document.getElementById("stopBtn").style.display = "none";
}

function switchTab(tab) {
    document.querySelectorAll(".panel-tab").forEach(t => {
        if (t.dataset.tab) t.classList.toggle("active", t.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-content").forEach(c => {
        c.classList.toggle("active", c.dataset.tab === tab);
    });
}


// ============================================================
// Server config (display only — no secrets)
// ============================================================
async function loadServerConfig() {
    try {
        const res = await fetch("/api/config");
        const data = await res.json();
        serverMode = data.mode || "prod";
        const badge = document.getElementById("modeBadge");
        badge.textContent = serverMode;
        badge.className = "mode-badge mode-" + serverMode;
        const notes = {
            mock: "MOCK mode — no LLM calls, canned responses.",
            dev: "DEV mode — minimal LLM calls. Pennies per run.",
            prod: "PROD mode — full quality.",
        };
        badge.title = notes[serverMode] || serverMode;
        updateModelBadge();
    } catch (e) {
        console.error(e);
    }
}

function updateModelBadge() {
    const cfg = getLLMConfig();
    const label = cfg.model && cfg.api_key
        ? cfg.model
        : (serverMode === "mock" ? "mock mode" : "set up key");
    document.getElementById("modelLabel").textContent = label;
    document.getElementById("modelBadge").title = cfg.model
        ? `${cfg.model} @ ${cfg.base_url} | key: ${maskKey(cfg.api_key)}`
        : "Click to configure your API key";
}


// ============================================================
// Providers (for reference in settings modal)
// ============================================================
const PROVIDERS = [
    { name: "Cerebras", badge: "free", badgeLabel: "FREE", desc: "Fastest inference. Llama, Qwen, GPT-OSS.",
      keyUrl: "https://cloud.cerebras.ai/platform/api-keys", modelsUrl: "https://inference-docs.cerebras.ai/introduction",
      baseUrl: "https://api.cerebras.ai/v1" },
    { name: "Groq", badge: "free", badgeLabel: "FREE", desc: "Very fast. Daily token limit.",
      keyUrl: "https://console.groq.com/keys", modelsUrl: "https://console.groq.com/docs/models",
      baseUrl: "https://api.groq.com/openai/v1" },
    { name: "Google Gemini", badge: "free", badgeLabel: "FREE", desc: "1500 req/day on 2.0 Flash.",
      keyUrl: "https://aistudio.google.com/apikey", modelsUrl: "https://ai.google.dev/gemini-api/docs/models/gemini",
      baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/" },
    { name: "OpenRouter", badge: "free", badgeLabel: "FREE TIER", desc: "Aggregator for many models.",
      keyUrl: "https://openrouter.ai/keys", modelsUrl: "https://openrouter.ai/models",
      baseUrl: "https://openrouter.ai/api/v1" },
    { name: "Mistral", badge: "free", badgeLabel: "FREE TIER", desc: "Mistral Large, Codestral.",
      keyUrl: "https://console.mistral.ai/api-keys/", modelsUrl: "https://docs.mistral.ai/getting-started/models/models_overview/",
      baseUrl: "https://api.mistral.ai/v1" },
    { name: "Together AI", badge: "free", badgeLabel: "$25 CREDIT", desc: "Llama, Qwen, DeepSeek.",
      keyUrl: "https://api.together.xyz/settings/api-keys", modelsUrl: "https://docs.together.ai/docs/serverless-models",
      baseUrl: "https://api.together.xyz/v1" },
    { name: "SambaNova", badge: "free", badgeLabel: "FREE TIER", desc: "Fast Llama inference.",
      keyUrl: "https://cloud.sambanova.ai/apis", modelsUrl: "https://docs.sambanova.ai/cloud/docs/get-started/supported-models",
      baseUrl: "https://api.sambanova.ai/v1" },
    { name: "DeepSeek", badge: "paid", badgeLabel: "CHEAP", desc: "V3 & R1. ~$0.14/1M tokens.",
      keyUrl: "https://platform.deepseek.com/api_keys", modelsUrl: "https://api-docs.deepseek.com/quick_start/pricing",
      baseUrl: "https://api.deepseek.com/v1" },
    { name: "OpenAI", badge: "paid", badgeLabel: "PAID", desc: "GPT-4o, o1, o3-mini.",
      keyUrl: "https://platform.openai.com/api-keys", modelsUrl: "https://platform.openai.com/docs/models",
      baseUrl: "https://api.openai.com/v1" },
    { name: "Ollama", badge: "local", badgeLabel: "LOCAL", desc: "Run locally. Unlimited, offline.",
      keyUrl: "https://ollama.com/download", modelsUrl: "https://ollama.com/library",
      baseUrl: "http://localhost:11434/v1" },
];

function renderProviders() {
    const cfg = getLLMConfig();
    const activeBase = cfg.base_url;
    const grid = document.getElementById("providersGrid");
    grid.innerHTML = "";
    PROVIDERS.forEach(p => {
        const isActive = activeBase && activeBase.startsWith(p.baseUrl.replace(/\/$/, ""));
        const card = document.createElement("div");
        card.className = "provider-card" + (isActive ? " active" : "");
        card.innerHTML = `
            <div class="provider-header">
                <span class="provider-name">${escapeHtml(p.name)}${isActive ? ' <span style="color:#4ecdc4">&check;</span>' : ''}</span>
                <span class="provider-badge-${p.badge}">${p.badgeLabel}</span>
            </div>
            <div class="provider-desc">${escapeHtml(p.desc)}</div>
            <div class="provider-actions">
                <a href="${p.keyUrl}" target="_blank" rel="noopener">Get Key</a>
                <a href="${p.modelsUrl}" target="_blank" rel="noopener">Models</a>
                <button class="use-provider-btn">Use</button>
            </div>
        `;
        card.querySelector(".use-provider-btn").addEventListener("click", () => {
            document.getElementById("keyBaseUrl").value = p.baseUrl;
            if (p.name === "Ollama" && !document.getElementById("keyApiKey").value) {
                document.getElementById("keyApiKey").value = "ollama";
            }
            document.getElementById("keyModel").focus();
            setKeyStatus("Base URL filled. Now add your key and model, then Save.", "ok");
        });
        grid.appendChild(card);
    });
}


// ============================================================
// Settings modal
// ============================================================
function openSettings() {
    const cfg = getLLMConfig();
    document.getElementById("keyApiKey").value = cfg.api_key;
    document.getElementById("keyBaseUrl").value = cfg.base_url;
    document.getElementById("keyModel").value = cfg.model;
    document.getElementById("sessionOnlyToggle").checked = isSessionOnly();
    setKeyStatus("");
    renderProviders();
    document.getElementById("settingsModal").classList.add("active");
}

function closeSettings() {
    document.getElementById("settingsModal").classList.remove("active");
}

function setKeyStatus(msg, kind = "") {
    const el = document.getElementById("keyStatus");
    el.textContent = msg;
    el.className = "key-status " + (kind || "");
}


// ============================================================
// History drawer (uses IndexedDB)
// ============================================================
async function refreshHistory() {
    try {
        const projects = await DB.listProjects();
        renderHistory(projects);
    } catch (e) {
        console.error("Failed to load history:", e);
    }
}

function renderHistory(projects) {
    const list = document.getElementById("historyList");
    const count = document.getElementById("historyCount");
    if (count) count.textContent = `${projects.length} project${projects.length === 1 ? "" : "s"}`;
    if (!projects.length) {
        list.innerHTML = '<div class="empty-state small"><p>No projects yet</p></div>';
        return;
    }
    list.innerHTML = "";
    projects.forEach(p => {
        const item = document.createElement("div");
        item.className = "history-item" + (currentProject && p.id === currentProject.id ? " active" : "");
        const date = new Date(p.updated_at);
        const when = date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        const hasFiles = p.files && Object.keys(p.files).length > 0;
        const fileCount = hasFiles ? Object.keys(p.files).length : 0;
        const dlAttrs = hasFiles
            ? `title="Download ${fileCount} file${fileCount === 1 ? '' : 's'} as ZIP"`
            : `title="No files in this project" disabled`;
        item.innerHTML = `
            <div class="history-item-body">
                <div class="history-item-title">${escapeHtml(p.title)}</div>
                <div class="history-item-time">${when}${hasFiles ? ` · ${fileCount} file${fileCount === 1 ? '' : 's'}` : ' · no files'}</div>
            </div>
            <div class="history-item-actions">
                <button class="history-item-btn history-item-download" ${dlAttrs}>&#11015;</button>
                <button class="history-item-btn history-item-delete" title="Delete">&times;</button>
            </div>
        `;
        item.querySelector(".history-item-body").addEventListener("click", () => loadProject(p.id));

        const dlBtn = item.querySelector(".history-item-download");
        if (hasFiles) {
            dlBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                downloadProjectZip(p);
            });
        }

        item.querySelector(".history-item-delete").addEventListener("click", async (e) => {
            e.stopPropagation();
            if (!confirm("Delete this project?")) return;
            await DB.deleteProject(p.id);
            if (currentProject && currentProject.id === p.id) startNewProject();
            await refreshHistory();
        updateStorageMeter();
        });
        list.appendChild(item);
    });
}

async function downloadProjectZip(project) {
    if (!project.files || !Object.keys(project.files).length) {
        alert("This project has no files to download.");
        return;
    }
    try {
        const res = await fetch("/download-zip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files: project.files }),
        });
        if (!res.ok) throw new Error("Download failed");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const safeName = (project.title || "project").replace(/[^a-z0-9-_]+/gi, "-").slice(0, 50);
        a.download = `${safeName}.zip`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert("Download failed: " + e.message);
    }
}

async function loadProject(projectId) {
    const p = await DB.getProject(projectId);
    if (!p) { alert("Project not found"); return; }
    currentProject = p;

    document.getElementById("messagesStream").innerHTML = "";
    accumulatedMessages = p.messages || [];
    (p.messages || []).forEach(m => addMessage(m.sender, m.receiver, m.content));
    accumulatedMessages = p.messages || [];

    if (p.files && Object.keys(p.files).length) {
        currentFiles = p.files;
        renderCode(p.files);
        document.getElementById("downloadBtn").style.display = "flex";
    }

    document.querySelectorAll(".agent-card").forEach(c => {
        c.className = "agent-card done";
        c.querySelector(".agent-status").textContent = "Done";
    });

    showProjectIndicator(p.title);
    document.getElementById("taskInput").placeholder = "Ask a follow-up... (e.g., 'Add dark mode')";

    await refreshHistory();
    closeHistory();
}

function showProjectIndicator(title) {
    const ind = document.getElementById("projectIndicator");
    document.getElementById("indicatorTitle").textContent = title;
    ind.style.display = "flex";
}

function hideProjectIndicator() {
    document.getElementById("projectIndicator").style.display = "none";
}

function startNewProject() {
    currentProject = null;
    currentFiles = {};
    streamingMessages = {};
    accumulatedMessages = [];
    document.getElementById("messagesStream").innerHTML = '<div class="empty-state"><span>&#129302;</span><p>Submit a task to watch the agents collaborate</p></div>';
    document.getElementById("codeOutput").innerHTML = '<div class="empty-state"><span>&#128196;</span><p>Code will appear here</p></div>';
    document.getElementById("previewOutput").innerHTML = '<div class="empty-state"><span>&#128065;</span><p>Preview will appear here</p></div>';
    document.getElementById("downloadBtn").style.display = "none";
    document.getElementById("taskInput").value = "";
    document.getElementById("taskInput").placeholder = "Describe a software engineering task...";
    document.querySelectorAll(".agent-card").forEach(c => {
        c.className = "agent-card";
        c.querySelector(".agent-status").textContent = "Idle";
    });
    document.getElementById("progressBar").classList.remove("active");
    hideProjectIndicator();
    refreshHistory();
}

function openHistory() {
    document.getElementById("historyDrawer").classList.add("open");
    document.getElementById("drawerOverlay").classList.add("active");
    refreshHistory();
    updateStorageMeter();
}

function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

async function updateStorageMeter() {
    const label = document.getElementById("storageLabel");
    const fill = document.getElementById("storageFill");
    if (!navigator.storage || !navigator.storage.estimate) {
        label.textContent = "Storage API not available in this browser";
        return;
    }
    try {
        const est = await navigator.storage.estimate();
        const used = est.usage || 0;
        const quota = est.quota || 0;
        const pct = quota ? (used / quota) * 100 : 0;
        fill.style.width = Math.min(pct, 100) + "%";
        fill.className = "storage-fill" + (pct > 90 ? " danger" : pct > 70 ? " warn" : "");
        label.textContent = quota
            ? `${formatBytes(used)} used of ${formatBytes(quota)} available (${pct.toFixed(2)}%)`
            : `${formatBytes(used)} used`;
    } catch (e) {
        label.textContent = "Storage usage unavailable";
    }
}

function closeHistory() {
    document.getElementById("historyDrawer").classList.remove("open");
    document.getElementById("drawerOverlay").classList.remove("active");
}


// ============================================================
// Helpers
// ============================================================
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
}

function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}


// ============================================================
// Wire up events
// ============================================================
document.getElementById("runBtn").addEventListener("click", submitTask);
document.getElementById("stopBtn").addEventListener("click", stopTask);
document.getElementById("downloadBtn").addEventListener("click", downloadZip);

document.getElementById("taskInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitTask();
});

document.querySelectorAll(".template-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const task = btn.dataset.task;
        if (task) useTemplate(task);
    });
});

document.querySelectorAll(".panel-tab[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// History drawer
document.getElementById("historyBtn").addEventListener("click", openHistory);
document.getElementById("historyCloseBtn").addEventListener("click", closeHistory);
document.getElementById("drawerOverlay").addEventListener("click", closeHistory);
document.getElementById("newProjectBtn").addEventListener("click", startNewProject);
document.getElementById("indicatorCloseBtn").addEventListener("click", startNewProject);
document.getElementById("historyClearAllBtn").addEventListener("click", async () => {
    const projects = await DB.listProjects();
    if (!projects.length) return;
    if (!confirm(`Delete all ${projects.length} projects from this browser? This cannot be undone.`)) return;
    await DB.clearAll();
    if (currentProject) startNewProject();
    await refreshHistory();
});

// Settings
document.getElementById("modelBadge").addEventListener("click", openSettings);
document.getElementById("modalCloseBtn").addEventListener("click", closeSettings);
document.getElementById("settingsModal").addEventListener("click", (e) => {
    if (e.target.id === "settingsModal") closeSettings();
});

document.getElementById("keyToggleBtn").addEventListener("click", () => {
    const input = document.getElementById("keyApiKey");
    input.type = input.type === "password" ? "text" : "password";
});

document.getElementById("keySaveBtn").addEventListener("click", () => {
    const api_key = document.getElementById("keyApiKey").value.trim();
    const base_url = document.getElementById("keyBaseUrl").value.trim();
    const model = document.getElementById("keyModel").value.trim();
    if (!api_key) { setKeyStatus("API key is required", "error"); return; }
    if (!base_url) { setKeyStatus("Base URL is required", "error"); return; }
    if (!model) { setKeyStatus("Model name is required", "error"); return; }
    saveLLMConfig({ api_key, base_url, model });
    setKeyStatus("Saved to your browser. Never sent to our database.", "ok");
    updateModelBadge();
});

document.getElementById("keyClearBtn").addEventListener("click", () => {
    if (!confirm("Clear your API key and config from this browser?")) return;
    clearLLMConfig();
    document.getElementById("keyApiKey").value = "";
    document.getElementById("keyBaseUrl").value = "";
    document.getElementById("keyModel").value = "";
    setKeyStatus("Cleared.", "ok");
    updateModelBadge();
});

document.getElementById("sessionOnlyToggle").addEventListener("change", (e) => {
    setSessionOnly(e.target.checked);
    if (e.target.checked) {
        setKeyStatus("Key is now session-only. It will be cleared when you close this tab.", "ok");
    } else {
        setKeyStatus("Key now persists across sessions.", "ok");
    }
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeSettings();
        closeHistory();
    }
});


// ============================================================
// Init
// ============================================================
loadServerConfig();
refreshHistory();
connect();
