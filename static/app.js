let ws = null;
let isRunning = false;
let currentFiles = {};
let streamingMessages = {};  // msg_id -> element

const PROGRESS_MAP = {
    pending: 5, planning: 20, coding: 45, reviewing: 65,
    fixing: 55, testing: 85, debugging: 70,
    completed: 100, failed: 100,
};

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
        const event = JSON.parse(e.data);
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
    const displayContent = content.length > 800
        ? content.substring(0, 800) + "\n... (truncated)"
        : content;

    const msg = document.createElement("div");
    msg.className = "message";
    msg.innerHTML = `
        <div class="message-header">
            <span class="message-sender sender-${sender}">${sender}</span>
            <span class="message-arrow">&#10132;</span>
            <span class="message-receiver">${receiver}</span>
        </div>
        <div class="message-body"></div>
    `;
    msg.querySelector(".message-body").textContent = displayContent;
    stream.appendChild(msg);
    stream.scrollTop = stream.scrollHeight;
}

function startStreamingMessage(sender, receiver, msgId) {
    const stream = ensureStream();
    const msg = document.createElement("div");
    msg.className = "message streaming";
    msg.innerHTML = `
        <div class="message-header">
            <span class="message-sender sender-${sender}">${sender}</span>
            <span class="message-arrow">&#10132;</span>
            <span class="message-receiver">${receiver}</span>
        </div>
        <div class="message-body"></div>
    `;
    stream.appendChild(msg);
    stream.scrollTop = stream.scrollHeight;
    streamingMessages[msgId] = {
        element: msg,
        body: msg.querySelector(".message-body"),
        text: "",
    };
}

function appendToStreamingMessage(msgId, chunk) {
    const msg = streamingMessages[msgId];
    if (!msg) return;
    msg.text += chunk;
    // Truncate live display to last 800 chars to avoid huge DOM
    msg.body.textContent = msg.text.length > 800
        ? "..." + msg.text.slice(-800)
        : msg.text;
    const stream = document.getElementById("messagesStream");
    stream.scrollTop = stream.scrollHeight;
}

function endStreamingMessage(msgId) {
    const msg = streamingMessages[msgId];
    if (!msg) return;
    msg.element.classList.remove("streaming");
    delete streamingMessages[msgId];
}

function updateProgress(status) {
    const bar = document.getElementById("progressBar");
    const fill = document.getElementById("progressFill");
    const label = document.getElementById("progressLabel");

    bar.classList.add("active");
    fill.style.width = (PROGRESS_MAP[status] || 0) + "%";
    label.textContent = status.replace("_", " ");

    if (status === "completed") {
        fill.style.background = "linear-gradient(90deg, #4ecdc4, #6bff6b)";
        label.style.color = "#4ecdc4";
        resetUI();
    } else if (status === "failed") {
        fill.style.background = "#ff4444";
        label.style.color = "#ff4444";
        resetUI();
    }
}

function getLang(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    const map = {
        py: "python", js: "javascript", html: "markup",
        css: "css", json: "json", sh: "bash", bash: "bash",
        md: "markdown", txt: "none",
    };
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
        header.innerHTML = `
            <span class="code-filename">${escapeHtml(filename)}</span>
            <button class="code-copy-btn">Copy</button>
        `;
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

    const fileNames = Object.keys(files);
    const indexName = fileNames.find(f => /^(index|main)\.html?$/i.test(f));
    const anyHtml = fileNames.find(f => /\.html?$/i.test(f));
    const htmlName = indexName || anyHtml;
    const htmlFile = htmlName ? files[htmlName] : null;

    if (!htmlFile) {
        preview.innerHTML = `
            <div class="empty-state">
                <span>&#128196;</span>
                <p>No HTML file to preview<br><small>Preview works when generated code includes an .html file</small></p>
            </div>
        `;
        return;
    }

    let inlinedHtml = htmlFile;
    for (const [fname, content] of Object.entries(files)) {
        if (fname === htmlName) continue;
        if (fname.endsWith(".css")) {
            const linkRegex = new RegExp(`<link[^>]*href=["']?${escapeRegex(fname)}["']?[^>]*>`, "gi");
            inlinedHtml = inlinedHtml.replace(linkRegex, `<style>${content}</style>`);
        } else if (fname.endsWith(".js")) {
            const scriptRegex = new RegExp(`<script[^>]*src=["']?${escapeRegex(fname)}["']?[^>]*>\\s*</script>`, "gi");
            inlinedHtml = inlinedHtml.replace(scriptRegex, `<script>${content}<\/script>`);
        }
    }

    const blob = new Blob([inlinedHtml], { type: "text/html" });
    const url = URL.createObjectURL(blob);

    preview.innerHTML = `
        <div class="preview-toolbar">
            <span class="preview-url">&#128279; ${escapeHtml(htmlName)}</span>
            <button class="code-copy-btn" id="openNewTabBtn">Open in new tab</button>
        </div>
        <iframe class="preview-frame" src="${url}" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>
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
        const response = await fetch("/download-zip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentFiles),
        });
        if (!response.ok) throw new Error("Download failed");
        const blob = await response.blob();
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

function submitTask() {
    const input = document.getElementById("taskInput");
    const task = input.value.trim();
    if (!task) { alert("Please enter a task"); return; }
    if (!ws || ws.readyState !== WebSocket.OPEN) { alert("Not connected. Check that the Python server is running."); return; }
    if (isRunning) { alert("A task is already running. Click Stop first."); return; }

    isRunning = true;
    document.getElementById("runBtn").style.display = "none";
    document.getElementById("stopBtn").style.display = "flex";
    document.getElementById("downloadBtn").style.display = "none";
    currentFiles = {};
    streamingMessages = {};

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

    ws.send(JSON.stringify({ action: "run", task }));
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

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

document.getElementById("taskInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitTask();
});

// Wire up template buttons via data-task attribute
document.querySelectorAll(".template-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const task = btn.dataset.task;
        if (task) useTemplate(task);
    });
});

// ============================================
// Provider Settings
// ============================================
const PROVIDERS = [
    {
        name: "Cerebras",
        badge: "free", badgeLabel: "FREE",
        desc: "Fastest inference. Llama, Qwen, GPT-OSS.",
        keyUrl: "https://cloud.cerebras.ai/platform/api-keys",
        modelsUrl: "https://inference-docs.cerebras.ai/introduction",
        baseUrl: "https://api.cerebras.ai/v1",
    },
    {
        name: "Groq",
        badge: "free", badgeLabel: "FREE",
        desc: "Very fast. Llama, Mixtral. Daily token limit.",
        keyUrl: "https://console.groq.com/keys",
        modelsUrl: "https://console.groq.com/docs/models",
        baseUrl: "https://api.groq.com/openai/v1",
    },
    {
        name: "Google Gemini",
        badge: "free", badgeLabel: "FREE",
        desc: "1500 req/day on Gemini 2.0 Flash.",
        keyUrl: "https://aistudio.google.com/apikey",
        modelsUrl: "https://ai.google.dev/gemini-api/docs/models/gemini",
        baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
    {
        name: "OpenRouter",
        badge: "free", badgeLabel: "FREE TIER",
        desc: "Aggregator for many models. Some marked :free.",
        keyUrl: "https://openrouter.ai/keys",
        modelsUrl: "https://openrouter.ai/models",
        baseUrl: "https://openrouter.ai/api/v1",
    },
    {
        name: "Mistral",
        badge: "free", badgeLabel: "FREE TIER",
        desc: "Mistral Large, Codestral, Mixtral.",
        keyUrl: "https://console.mistral.ai/api-keys/",
        modelsUrl: "https://docs.mistral.ai/getting-started/models/models_overview/",
        baseUrl: "https://api.mistral.ai/v1",
    },
    {
        name: "Together AI",
        badge: "free", badgeLabel: "$25 CREDIT",
        desc: "Llama, Qwen, DeepSeek, and more open models.",
        keyUrl: "https://api.together.xyz/settings/api-keys",
        modelsUrl: "https://docs.together.ai/docs/serverless-models",
        baseUrl: "https://api.together.xyz/v1",
    },
    {
        name: "SambaNova",
        badge: "free", badgeLabel: "FREE TIER",
        desc: "Fast inference on Llama models.",
        keyUrl: "https://cloud.sambanova.ai/apis",
        modelsUrl: "https://docs.sambanova.ai/cloud/docs/get-started/supported-models",
        baseUrl: "https://api.sambanova.ai/v1",
    },
    {
        name: "DeepSeek",
        badge: "paid", badgeLabel: "CHEAP",
        desc: "DeepSeek V3 & R1. ~$0.14 per 1M tokens.",
        keyUrl: "https://platform.deepseek.com/api_keys",
        modelsUrl: "https://api-docs.deepseek.com/quick_start/pricing",
        baseUrl: "https://api.deepseek.com/v1",
    },
    {
        name: "OpenAI",
        badge: "paid", badgeLabel: "PAID",
        desc: "GPT-4o, o1, o3-mini. Pay as you go.",
        keyUrl: "https://platform.openai.com/api-keys",
        modelsUrl: "https://platform.openai.com/docs/models",
        baseUrl: "https://api.openai.com/v1",
    },
    {
        name: "Ollama",
        badge: "local", badgeLabel: "LOCAL",
        desc: "Run models on your own machine. Unlimited, offline.",
        keyUrl: "https://ollama.com/download",
        modelsUrl: "https://ollama.com/library",
        baseUrl: "http://localhost:11434/v1",
    },
];

function buildConfig(p) {
    const apiKey = p.name === "Ollama" ? "ollama" : "<your-key>";
    return `LLM_API_KEY=${apiKey}\nLLM_BASE_URL=${p.baseUrl}\nMODEL_NAME=<pick-from-models-link>`;
}

async function loadConfig() {
    try {
        const res = await fetch("/api/config");
        const data = await res.json();
        const label = `${data.model} @ ${data.provider}`;
        document.getElementById("modelLabel").textContent = data.model;
        document.getElementById("modelBadge").title = label;
        document.getElementById("currentModelLabel").textContent = label;
        return data;
    } catch (e) {
        document.getElementById("modelLabel").textContent = "unknown";
        return null;
    }
}

function renderProviders(activeProvider) {
    const grid = document.getElementById("providersGrid");
    grid.innerHTML = "";
    PROVIDERS.forEach(p => {
        const isActive = activeProvider && p.name.toLowerCase() === activeProvider.toLowerCase();
        const card = document.createElement("div");
        card.className = "provider-card" + (isActive ? " active" : "");
        card.innerHTML = `
            <div class="provider-header">
                <span class="provider-name">${escapeHtml(p.name)}${isActive ? ' <span style="color:#4ecdc4;font-size:0.75rem">&check;</span>' : ''}</span>
                <span class="provider-badge-${p.badge}">${p.badgeLabel}</span>
            </div>
            <div class="provider-desc">${escapeHtml(p.desc)}</div>
            <div class="provider-actions">
                <a href="${p.keyUrl}" target="_blank" rel="noopener">Get Key</a>
                <a href="${p.modelsUrl}" target="_blank" rel="noopener">Models</a>
                <button class="copy-cfg-btn">Copy .env</button>
            </div>
        `;
        card.querySelector(".copy-cfg-btn").addEventListener("click", (e) => {
            const btn = e.target;
            navigator.clipboard.writeText(buildConfig(p)).then(() => {
                btn.classList.add("copied");
                btn.textContent = "Copied!";
                setTimeout(() => {
                    btn.classList.remove("copied");
                    btn.textContent = "Copy .env";
                }, 1500);
            });
        });
        grid.appendChild(card);
    });
}

async function openSettings() {
    const config = await loadConfig();
    renderProviders(config ? config.provider : null);
    document.getElementById("settingsModal").classList.add("active");
}

function closeSettings() {
    document.getElementById("settingsModal").classList.remove("active");
}

document.getElementById("modelBadge").addEventListener("click", openSettings);
document.getElementById("modalCloseBtn").addEventListener("click", closeSettings);
document.getElementById("settingsModal").addEventListener("click", (e) => {
    if (e.target.id === "settingsModal") closeSettings();
});
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSettings();
});

// Load initial config to populate the header badge
loadConfig();

connect();
