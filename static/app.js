const form = document.getElementById("convert-form");
const urlInput = document.getElementById("url");
const fmtButtons = document.querySelectorAll(".fmt-btn");
const qualitySelect = document.getElementById("quality");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("status");
const progressBar = document.getElementById("progress-bar");
const statusText = document.getElementById("status-text");
const resultBox = document.getElementById("result");
const resultTitle = document.getElementById("result-title");
const saveBtn = document.getElementById("save-btn");
const saveNote = document.getElementById("save-note");
const revealBtn = document.getElementById("reveal-btn");
const errorBox = document.getElementById("error");
const resetBtn = document.getElementById("reset-btn");

const QUALITY_OPTIONS = {
  mp4: [
    { value: "best", label: "Best available" },
    { value: "1080", label: "Up to 1080p" },
    { value: "720", label: "Up to 720p" },
    { value: "480", label: "Up to 480p" },
  ],
  mp3: [
    { value: "320", label: "320 kbps" },
    { value: "192", label: "192 kbps" },
    { value: "128", label: "128 kbps" },
  ],
};

let currentFormat = "mp4";
let pollTimer = null;
let currentJobId = null;
let maxSeenPct = 0;

function renderQualityOptions() {
  qualitySelect.innerHTML = "";
  for (const opt of QUALITY_OPTIONS[currentFormat]) {
    const el = document.createElement("option");
    el.value = opt.value;
    el.textContent = opt.label;
    qualitySelect.appendChild(el);
  }
}

function setFormEnabled(enabled) {
  urlInput.disabled = !enabled;
  qualitySelect.disabled = !enabled;
  fmtButtons.forEach((b) => (b.disabled = !enabled));
  submitBtn.disabled = !enabled;
}

fmtButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    fmtButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentFormat = btn.dataset.format;
    renderQualityOptions();
  });
});

renderQualityOptions();

function showState(state) {
  statusBox.classList.toggle("hidden", state !== "status");
  resultBox.classList.toggle("hidden", state !== "result");
  errorBox.classList.toggle("hidden", state !== "error");
}

function setProgress(pct, text) {
  const clamped = Math.max(maxSeenPct, pct);
  maxSeenPct = clamped;
  progressBar.style.width = `${clamped}%`;
  statusText.textContent = text;
}

function resetSaveState() {
  saveBtn.disabled = false;
  saveBtn.textContent = "Save File…";
  saveNote.classList.add("hidden");
  saveNote.textContent = "";
  revealBtn.classList.add("hidden");
}

resetBtn.addEventListener("click", () => {
  form.reset();
  showState(null);
  setFormEnabled(true);
  resetSaveState();
  maxSeenPct = 0;
  currentJobId = null;
  if (pollTimer) clearInterval(pollTimer);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (pollTimer) clearInterval(pollTimer);

  const url = urlInput.value.trim();
  if (!url) return;

  setFormEnabled(false);
  maxSeenPct = 0;
  showState("status");
  setProgress(0, "Starting…");

  try {
    const res = await fetch("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        format: currentFormat,
        quality: qualitySelect.value,
      }),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Something went wrong");
    }

    currentJobId = data.job_id;
    pollTimer = setInterval(() => pollStatus(data.job_id), 900);
  } catch (err) {
    setFormEnabled(true);
    showState("error");
    errorBox.textContent = err.message;
  }
});

async function pollStatus(jobId) {
  try {
    const res = await fetch(`/api/status/${jobId}`);
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Lost track of job");
    }

    if (data.status === "checking") {
      setProgress(0, "Checking clip length…");
    } else if (data.status === "downloading") {
      setProgress(data.progress || 0, `Downloading… ${data.progress || 0}%`);
    } else if (data.status === "converting") {
      setProgress(data.progress || 95, "Converting…");
    } else if (data.status === "done") {
      clearInterval(pollTimer);
      setProgress(100, "Done!");
      resetSaveState();
      resultTitle.textContent = data.title || "Your file is ready";
      showState("result");
    } else if (data.status === "error") {
      clearInterval(pollTimer);
      setFormEnabled(true);
      showState("error");
      errorBox.textContent = data.error || "Conversion failed";
    } else {
      setProgress(0, "Queued…");
    }
  } catch (err) {
    clearInterval(pollTimer);
    setFormEnabled(true);
    showState("error");
    errorBox.textContent = err.message;
  }
}

saveBtn.addEventListener("click", async () => {
  if (!currentJobId) return;

  if (!(window.pywebview && window.pywebview.api)) {
    // Fallback for running in a plain browser during development.
    window.location.href = `/api/download/${currentJobId}`;
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = "Waiting for save location…";

  try {
    const result = await window.pywebview.api.save_file(currentJobId);

    if (result.ok) {
      saveBtn.textContent = "Saved";
      saveNote.textContent = `Saved to ${result.path}`;
      saveNote.classList.remove("hidden");
      revealBtn.classList.remove("hidden");
      revealBtn.onclick = () => window.pywebview.api.reveal_file(result.path);
      setFormEnabled(true);
    } else if (result.cancelled) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save File…";
    } else {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save File…";
      saveNote.textContent = result.error || "Couldn't save that file.";
      saveNote.classList.remove("hidden");
    }
  } catch (err) {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save File…";
    saveNote.textContent = err.message;
    saveNote.classList.remove("hidden");
  }
});
