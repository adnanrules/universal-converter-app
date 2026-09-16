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
const downloadLink = document.getElementById("download-link");
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

function renderQualityOptions() {
  qualitySelect.innerHTML = "";
  for (const opt of QUALITY_OPTIONS[currentFormat]) {
    const el = document.createElement("option");
    el.value = opt.value;
    el.textContent = opt.label;
    qualitySelect.appendChild(el);
  }
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
  progressBar.style.width = `${pct}%`;
  statusText.textContent = text;
}

resetBtn.addEventListener("click", () => {
  form.reset();
  showState(null);
  submitBtn.disabled = false;
  if (pollTimer) clearInterval(pollTimer);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (pollTimer) clearInterval(pollTimer);

  const url = urlInput.value.trim();
  if (!url) return;

  submitBtn.disabled = true;
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

    pollTimer = setInterval(() => pollStatus(data.job_id), 1000);
  } catch (err) {
    submitBtn.disabled = false;
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
      setProgress(95, "Converting…");
    } else if (data.status === "done") {
      clearInterval(pollTimer);
      setProgress(100, "Done!");
      submitBtn.disabled = false;
      resultTitle.textContent = data.title || "Your file is ready";
      downloadLink.href = `/api/download/${jobId}`;
      showState("result");
    } else if (data.status === "error") {
      clearInterval(pollTimer);
      submitBtn.disabled = false;
      showState("error");
      errorBox.textContent = data.error || "Conversion failed";
    } else {
      setProgress(0, "Queued…");
    }
  } catch (err) {
    clearInterval(pollTimer);
    submitBtn.disabled = false;
    showState("error");
    errorBox.textContent = err.message;
  }
}
