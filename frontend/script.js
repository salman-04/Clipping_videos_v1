/* AI Clip Studio — Frontend v2 */

const STATE_KEY = "ai_clip_studio_last_job";

function saveLastJob(jobId) {
  try { localStorage.setItem(STATE_KEY, jobId); } catch {}
}

function loadLastJob() {
  try { return localStorage.getItem(STATE_KEY); } catch { return null; }
}

function clearLastJob() {
  try { localStorage.removeItem(STATE_KEY); } catch {}
}

const API = "";
let state = { currentJobId: null, pollInterval: null };

/* Sidebar */
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "pinned") loadPinned();
  });
});

/* Source toggle */
document.querySelectorAll(".seg-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".seg-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const isUrl = btn.dataset.src === "url";
    document.getElementById("urlGroup").classList.toggle("hidden", !isUrl);
    document.getElementById("fileGroup").classList.toggle("hidden", isUrl);
  });
});

/* Mode toggle */
let currentMode = "find-clips";
document.querySelectorAll(".mode-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentMode = btn.dataset.mode;

    const isCaptions = currentMode === "captions-only";
    const isFind = currentMode !== "captions-only";

    document.getElementById("rangesGroup").classList.toggle("hidden", !isCaptions);
    document.getElementById("detectionGroup").classList.toggle("hidden", !isFind);
    document.getElementById("clipCountGroup").classList.toggle("hidden", !isFind);
    document.getElementById("burnGroup").classList.toggle("hidden", !isFind);
    document.getElementById("styleGroup").classList.toggle("hidden", !isFind);
    
  });
});

/* File upload */
let uploadedFilePath = null;
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const fileInfo = document.getElementById("fileInfo");
const uploadProgress = document.getElementById("uploadProgress");
const uploadBarFill = document.getElementById("uploadBarFill");
const uploadLabel = document.getElementById("uploadLabel");

dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", e => { if (e.target.files.length) uploadFile(e.target.files[0]); });
["dragenter","dragover"].forEach(evt => dropZone.addEventListener(evt, e => {
  e.preventDefault(); e.stopPropagation(); dropZone.classList.add("dragover");
}));
["dragleave","drop"].forEach(evt => dropZone.addEventListener(evt, e => {
  e.preventDefault(); e.stopPropagation(); dropZone.classList.remove("dragover");
}));
dropZone.addEventListener("drop", e => { if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]); });
document.getElementById("clearFile").addEventListener("click", e => {
  e.stopPropagation();
  uploadedFilePath = null; fileInput.value = "";
  fileInfo.classList.add("hidden"); dropZone.style.display = "";
});

async function uploadFile(file) {
  const validExts = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"];
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!validExts.includes(ext)) return alert("Unsupported type: " + ext);
  if (file.size > 2 * 1024 * 1024 * 1024) return alert("Max 2 GB");

  uploadProgress.classList.remove("hidden");
  uploadBarFill.style.width = "0%";
  uploadLabel.textContent = `Uploading ${file.name}...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const xhr = new XMLHttpRequest();
    const result = await new Promise((resolve, reject) => {
      xhr.upload.addEventListener("progress", e => {
        if (e.lengthComputable) {
          const pct = (e.loaded / e.total) * 100;
          uploadBarFill.style.width = pct + "%";
          uploadLabel.textContent = `Uploading... ${pct.toFixed(0)}%`;
        }
      });
      xhr.addEventListener("load", () => xhr.status === 200
        ? resolve(JSON.parse(xhr.responseText))
        : reject(new Error(xhr.responseText)));
      xhr.addEventListener("error", () => reject(new Error("Network error")));
      xhr.open("POST", "/api/upload");
      xhr.send(formData);
    });

    uploadedFilePath = result.path;
    document.getElementById("fileName").textContent = file.name;
    document.getElementById("fileSize").textContent = `(${result.size_mb} MB)`;
    fileInfo.classList.remove("hidden");
    dropZone.style.display = "none";
    uploadProgress.classList.add("hidden");
  } catch (err) {
    alert("Upload failed: " + err.message);
    uploadProgress.classList.add("hidden");
  }
}

/* Start */
document.getElementById("startBtn").addEventListener("click", async () => {
  const isUrl = document.querySelector(".seg-btn.active").dataset.src === "url";
  let source;
  if (isUrl) {
    source = document.getElementById("sourceUrl").value.trim();
    if (!source) return alert("Enter a URL");
  } else {
    if (!uploadedFilePath) return alert("Select a file");
    source = uploadedFilePath;
  }

  const [minDur, maxDur] = document.getElementById("durationPreset").value.split("-").map(Number);

  const payload = {
    source, is_url: isUrl, mode: currentMode,
    detection: document.getElementById("detection").value,
    burn_captions: document.getElementById("burnCaptions").checked,
    ranges: document.getElementById("ranges").value,
    style: document.getElementById("style").value,
    num_clips: parseInt(document.getElementById("numClips").value) || 10,
    min_duration: minDur, max_duration: maxDur,
    api_keys: {},
  };

  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("progressBody").classList.remove("hidden");
  document.getElementById("results").classList.add("hidden");
  document.getElementById("logView").textContent = "";
  document.getElementById("startBtn").disabled = true;
  document.getElementById("startBtn").textContent = "⏳ Running...";

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed");
    state.currentJobId = data.job_id;
    pollJob();
  } catch (e) {
    document.getElementById("statusText").textContent = "Error: " + e.message;
    document.getElementById("startBtn").disabled = false;
    document.getElementById("startBtn").textContent = "⚡ Start";
  }
});

function pollJob() {
  if (state.pollInterval) clearInterval(state.pollInterval);
  state.pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${state.currentJobId}`);
      const data = await res.json();
      const log = (data.log || []).slice(-8).join("\n");
      document.getElementById("logView").textContent = log;
      document.getElementById("jobBarFill").style.width = (data.progress || 0) + "%";

      let status = "Running...";
      if (data.status === "running") status = `${data.stage} (${data.progress}%)`;
      else if (data.status === "completed") status = "Completed";
      else if (data.status === "error") status = "Error: " + (data.error || "");

      const pill = document.getElementById("statusPill");
      document.getElementById("statusText").textContent = status;
      pill.className = "status-pill " +
        (data.status === "completed" ? "completed" : data.status === "error" ? "error" : "");

      if (data.status === "completed") {
        clearInterval(state.pollInterval);
        renderClips(data.clips || []);
        resetButton();
        refreshStats();
        saveLastJob(state.currentJobId);
      } else if (data.status === "error") {
        clearInterval(state.pollInterval);
        resetButton();
      }
    } catch (e) { console.error(e); }
  }, 1500);
}

function resetButton() {
  document.getElementById("startBtn").disabled = false;
  document.getElementById("startBtn").textContent = "⚡ Start";
}

function renderClips(clips) {
  const grid = document.getElementById("clipGrid");
  document.getElementById("clipCountBadge").textContent = clips.length;
  document.getElementById("results").classList.remove("hidden");

  if (!clips.length) {
    grid.innerHTML = '<p class="muted">No clips found.</p>';
    return;
  }

  grid.innerHTML = clips.map((c, i) => `
    <div class="clip-card">
      <div class="clip-preview">
        <video src="${c.video_url}" controls preload="metadata"></video>
      </div>
      <div class="clip-title">${escapeHtml(c.title)}</div>
      <div class="clip-meta">
        ${c.score ? `<span class="score-badge">${c.score}</span>` : ""}
        <span>${c.duration}s</span>
      </div>
      <div class="clip-actions">
        <a href="${c.video_url}" target="_blank" download>⬇ MP4</a>
        <a href="${c.srt_url}" target="_blank">⬇ SRT</a>
        <a href="${c.txt_url}" target="_blank">⬇ TXT</a>
      </div>
      ${c.clip_id ? `
      <div class="clip-actions" style="margin-top:6px;">
        <button onclick="togglePin(${c.clip_id}, '${escapeAttr(c.filename)}', this)">📌 Pin</button>
      </div>` : ""}
    </div>
  `).join("");
}

window.togglePin = async function(clipId, filename, btn) {
  const pin = !btn.classList.contains("pinned");
  const res = await fetch("/api/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      clip_id: clipId, pin, job_id: state.currentJobId, filename,
    }),
  });
  const data = await res.json();
  if (data.ok) {
    btn.classList.toggle("pinned", pin);
    btn.textContent = pin ? "📌 Pinned" : "📌 Pin";
  } else {
    alert("Pin failed: " + (data.error || ""));
  }
};

async function loadPinned() {
  const res = await fetch("/api/pinned");
  const items = await res.json();
  const list = document.getElementById("pinnedList");
  if (!items.length) {
    list.innerHTML = '<p class="muted">No pinned clips yet. Pin clips from the Generate tab.</p>';
    return;
  }
  list.innerHTML = items.map(f => `
    <div class="clip-card">
      <div class="clip-title">${escapeHtml(f.name)}</div>
      <div class="clip-meta"><span>${f.size} MB</span></div>
    </div>
  `).join("");
}

document.getElementById("cleanBtn").addEventListener("click", async () => {
  if (!confirm("Delete all generated clips, SRTs, temp files, and uploads?\n\nPinned clips + learning DB are SAFE.")) return;
  const res = await fetch("/api/clean", { method: "POST" });
  const data = await res.json();
  const el = document.getElementById("cleanResult");
  if (data.ok) {
    el.textContent = `✅ Deleted: ${data.deleted.output} output items, ${data.deleted.temp} temp, ${data.deleted.uploads} uploads. Pinned items kept.`;
    refreshStats();
  } else {
    el.textContent = "❌ " + (data.error || "Failed");
  }
});

async function refreshStats() {
  try {
    const res = await fetch("/api/stats");
    const s = await res.json();
    document.getElementById("statJobs").textContent = s.total_jobs;
    document.getElementById("statClips").textContent = s.total_clips;
  } catch {}
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function escapeAttr(s) { return String(s).replace(/'/g, "\\'"); }

/* Init */
(async () => {
  await refreshStats();

  // Restore last job if page was reloaded
  const lastJobId = loadLastJob();
  if (lastJobId) {
    try {
      const res = await fetch(`/api/jobs/${lastJobId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.status === "completed" && data.clips?.length) {
          state.currentJobId = lastJobId;
          document.getElementById("emptyState").classList.add("hidden");
          document.getElementById("progressBody").classList.remove("hidden");
          document.getElementById("statusPill").className = "status-pill completed";
          document.getElementById("statusText").textContent = "Completed";
          document.getElementById("jobBarFill").style.width = "100%";
          renderClips(data.clips);
        } else if (data.status === "running") {
          state.currentJobId = lastJobId;
          document.getElementById("emptyState").classList.add("hidden");
          document.getElementById("progressBody").classList.remove("hidden");
          pollJob();
        }
      } else {
        clearLastJob();
      }
    } catch (e) {
      clearLastJob();
    }
  }
})();

/* ── Settings: API keys ── */
async function loadSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  // Prefill masked keys (only last 4 chars visible)
  ["groq", "cerebras", "gemini"].forEach(p => {
    const el = document.getElementById("key" + capitalize(p));
    if (el && data.api_keys?.[p]) el.value = data.api_keys[p];
  });
  if (data.ollama_model) {
    document.getElementById("ollamaModelManual").value = data.ollama_model;
  }
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

window.saveKey = async function(provider) {
  const inputId = "key" + capitalize(provider);
  const val = document.getElementById(inputId).value.trim();
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, api_key: val }),
  });
  const status = document.getElementById("status" + capitalize(provider));
  if (status) {
    status.textContent = " ✅ Saved";
    setTimeout(() => status.textContent = "", 2000);
  }
};

/* ── Settings: Ollama ── */
window.refreshOllama = async function() {
  const res = await fetch("/api/ollama/models");
  const data = await res.json();
  const sel = document.getElementById("ollamaModels");
  if (!data.installed?.length) {
    sel.innerHTML = '<option value="">No models found — is Ollama running?</option>';
    return;
  }
  sel.innerHTML = data.installed.map(m =>
    `<option value="${m}" ${m === data.current ? "selected" : ""}>${m}</option>`
  ).join("");
  sel.onchange = async () => {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ollama_model: sel.value }),
    });
    document.getElementById("statusOllama").textContent = " ✅ Saved";
  };
};

window.saveOllamaManual = async function() {
  const val = document.getElementById("ollamaModelManual").value.trim();
  if (!val) return;
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ollama_model: val }),
  });
  document.getElementById("statusOllama").textContent = " ✅ Saved";
};

// Load settings when Settings tab is opened
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab === "settings") {
      loadSettings();
    }
  });
});

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }