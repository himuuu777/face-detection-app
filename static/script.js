/* ==========================================================
   script.js  -  WHAT HAPPENS WHEN YOU CLICK (runs in the browser)
   ----------------------------------------------------------
   1. Starts the webcam and sends a picture to the server a few
      times per second.
   2. Draws green boxes on the faces the server finds.
   3. Handles "Save Snapshot" and "Upload Photo".
   4. Fills the dashboard (stats, chart, history table).
   ========================================================== */

// Shortcut: $("faceCount") instead of document.getElementById("faceCount")
const $ = (id) => document.getElementById(id);

const video = $("video");
const overlay = $("overlay");                    // transparent layer for the boxes
const overlayCtx = overlay.getContext("2d");
const frameCanvas = document.createElement("canvas");   // hidden canvas used to grab frames

const LIVE_WIDTH = 480;          // live frames are shrunk to this width (faster)
const LIVE_INTERVAL_MS = 300;    // how often a frame is checked
const SENSITIVITY_LABELS = ["", "Very low", "Low", "Medium", "High", "Very high"];

let stream = null;     // the camera stream
let timer = null;      // the repeating timer for live detection
let busy = false;      // true while waiting for the server (avoids sending too many)


/* ---------------------------------------------------------
   SMALL HELPERS
   --------------------------------------------------------- */
function setStatus(message, type = "info") {
  const el = $("status");
  el.textContent = message;
  el.className = "status " + type;       // type: "ok" (green), "error" (red), "info" (grey)
}

function setCount(number) {
  $("faceCount").textContent = number;
}

function getSensitivity() {
  return Number($("sensitivity").value);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

// Sends JSON to the server and returns the JSON answer
async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Server error");
  return data;
}


/* ---------------------------------------------------------
   TABS (Live Webcam / Upload Photo)
   --------------------------------------------------------- */
document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    button.classList.add("active");
    $("tab-" + button.dataset.tab).classList.add("active");
  });
});

// Sensitivity slider label
$("sensitivity").addEventListener("input", (event) => {
  $("sensLabel").textContent = SENSITIVITY_LABELS[event.target.value];
});


/* ---------------------------------------------------------
   WEBCAM
   --------------------------------------------------------- */

// Copies the current video picture into a canvas and returns it as text (base64 JPEG)
function captureFrame(targetWidth, quality) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;

  const width = Math.min(targetWidth, vw);
  const height = Math.round(vh * (width / vw));
  frameCanvas.width = width;
  frameCanvas.height = height;
  frameCanvas.getContext("2d").drawImage(video, 0, 0, width, height);

  return { dataUrl: frameCanvas.toDataURL("image/jpeg", quality), width, height };
}

// Draws a green box and label on every face
function drawBoxes(faces, width, height) {
  overlay.width = width;      // also clears the old boxes
  overlay.height = height;

  overlayCtx.lineWidth = 3;
  overlayCtx.strokeStyle = "#22c55e";
  overlayCtx.font = "bold 15px sans-serif";

  faces.forEach((face, index) => {
    // The video is shown mirrored, so we flip the box position too
    const x = width - (face.x + face.w);
    overlayCtx.strokeRect(x, face.y, face.w, face.h);

    const label = "Face " + (index + 1);
    const labelWidth = overlayCtx.measureText(label).width + 12;
    const labelY = face.y >= 22 ? face.y - 22 : face.y;
    overlayCtx.fillStyle = "#22c55e";
    overlayCtx.fillRect(x, labelY, labelWidth, 22);
    overlayCtx.fillStyle = "#ffffff";
    overlayCtx.fillText(label, x + 6, labelY + 16);
  });
}

async function startCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus("This browser cannot use the camera. Open http://127.0.0.1:8000 in Chrome or Edge.", "error");
    return;
  }

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
  } catch (err) {
    setStatus("Could not open the camera (" + err.message + "). Please allow camera permission.", "error");
    return;
  }

  video.srcObject = stream;
  await video.play();

  // Make the box exactly match the camera's shape so boxes line up with faces
  $("videoWrap").style.aspectRatio = video.videoWidth + " / " + video.videoHeight;
  $("videoPlaceholder").hidden = true;

  $("startBtn").disabled = true;
  $("stopBtn").disabled = false;
  $("snapBtn").disabled = false;
  setStatus("Camera is on. Detecting faces live...", "ok");

  timer = setInterval(detectLiveFrame, LIVE_INTERVAL_MS);
}

function stopCamera() {
  clearInterval(timer);
  timer = null;
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;

  overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  $("videoPlaceholder").hidden = false;
  $("startBtn").disabled = false;
  $("stopBtn").disabled = true;
  $("snapBtn").disabled = true;
  setCount(0);
  setStatus("Camera stopped.", "info");
}

// Runs again and again while the camera is on
async function detectLiveFrame() {
  if (busy) return;                       // still waiting for the previous answer
  const frame = captureFrame(LIVE_WIDTH, 0.7);
  if (!frame) return;

  busy = true;
  try {
    const data = await postJSON("/api/detect", {
      image: frame.dataUrl,
      sensitivity: getSensitivity(),
    });
    drawBoxes(data.faces, frame.width, frame.height);
    setCount(data.count);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    busy = false;
  }
}

// Shows the saved, marked picture in the Result panel
function showResult(data) {
  setCount(data.count);
  $("resultImage").src = data.image_url;
  $("resultImage").hidden = false;
  $("resultHint").hidden = true;
}

async function saveSnapshot() {
  const frame = captureFrame(960, 0.9);   // higher quality than the live frames
  if (!frame) return;

  $("snapBtn").disabled = true;
  try {
    const data = await postJSON("/api/snapshot", {
      image: frame.dataUrl,
      sensitivity: getSensitivity(),
    });
    showResult(data);
    setStatus("Snapshot saved. " + data.count + " face(s) found.", "ok");
    loadHistory();
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    $("snapBtn").disabled = false;
  }
}

$("startBtn").addEventListener("click", startCamera);
$("stopBtn").addEventListener("click", stopCamera);
$("snapBtn").addEventListener("click", saveSnapshot);


/* ---------------------------------------------------------
   PHOTO UPLOAD
   --------------------------------------------------------- */
const photoInput = $("photoInput");
const dropzone = $("dropzone");

function showChosenFile() {
  const file = photoInput.files[0];
  $("dropText").textContent = file ? "Selected: " + file.name : "Click to choose a photo, or drag and drop it here";
}
photoInput.addEventListener("change", showChosenFile);

["dragenter", "dragover"].forEach((name) =>
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((name) =>
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  })
);
dropzone.addEventListener("drop", (event) => {
  if (event.dataTransfer.files.length) {
    photoInput.files = event.dataTransfer.files;
    showChosenFile();
  }
});

$("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = photoInput.files[0];
  if (!file) {
    setStatus("Please choose a photo first.", "error");
    return;
  }

  const form = new FormData();
  form.append("photo", file);
  form.append("sensitivity", getSensitivity());

  const button = $("detectBtn");
  button.disabled = true;
  button.textContent = "Detecting...";
  try {
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Server error");

    showResult(data);
    setStatus("Done. " + data.count + " face(s) found in your photo.", "ok");
    loadHistory();
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Detect Faces";
  }
});


/* ---------------------------------------------------------
   DASHBOARD (stats, chart, history table)
   --------------------------------------------------------- */
function renderStats(stats) {
  $("statScans").textContent = stats.total_scans;
  $("statFaces").textContent = stats.total_faces;
  $("statAvg").textContent = stats.average;
  $("statLast").textContent = stats.last_scan;
}

function renderChart(records) {
  const chart = $("chart");
  if (!records.length) {
    chart.innerHTML = '<span class="chart-empty">The chart will appear after your first scan.</span>';
    return;
  }

  // records come newest-first; the chart reads better oldest-to-newest
  const latest = records.slice(0, 12).reverse();
  const maxCount = Math.max(1, ...latest.map((r) => r.face_count));

  chart.innerHTML = latest
    .map((record) => {
      const barHeight = Math.max(4, Math.round((record.face_count / maxCount) * 100));
      return (
        '<div class="bar-col">' +
        '<span class="bar-value">' + record.face_count + "</span>" +
        '<div class="bar" style="height:' + barHeight + 'px"></div>' +
        '<span class="bar-label">#' + record.id + "</span>" +
        "</div>"
      );
    })
    .join("");
}

function renderTable(records) {
  $("emptyHistory").hidden = records.length > 0;

  $("historyBody").innerHTML = records
    .map((record) => {
      const source = record.source === "webcam" ? "Webcam" : "Upload";
      return (
        "<tr>" +
        "<td>" + escapeHtml(record.id) + "</td>" +
        "<td>" + escapeHtml(record.created_at) + "</td>" +
        '<td><span class="badge">' + source + "</span></td>" +
        "<td><strong>" + escapeHtml(record.face_count) + "</strong></td>" +
        '<td><a href="' + escapeHtml(record.image_url) + '" target="_blank">View</a></td>' +
        "</tr>"
      );
    })
    .join("");
}

async function loadHistory() {
  try {
    const response = await fetch("/api/history");
    const data = await response.json();
    renderStats(data.stats);
    renderChart(data.records);
    renderTable(data.records);
  } catch (err) {
    setStatus("Could not load the dashboard: " + err.message, "error");
  }
}

$("clearBtn").addEventListener("click", async () => {
  if (!confirm("Delete all saved results and pictures?")) return;
  try {
    await postJSON("/api/clear", {});
    $("resultImage").hidden = true;
    $("resultHint").hidden = false;
    setStatus("All saved results were deleted.", "info");
    loadHistory();
  } catch (err) {
    setStatus(err.message, "error");
  }
});

// Load the dashboard when the page opens
loadHistory();
