const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SCREENS = ["idle", "shoot", "printing", "thanks", "error"];
let cfg = null, cameraReady = false, busy = false;

function show(name) { SCREENS.forEach((s) => $(s).classList.toggle("active", s === name)); }
function fail(msg) { console.error(msg); $("errMsg").textContent = msg; show("error"); }

// fetch wrapper: turns network + server errors into readable messages
async function api(url, opts) {
  let res;
  try { res = await fetch(url, opts); }
  catch { throw new Error("Can't reach the booth server. Is it running?"); }
  if (!res.ok) {
    let msg = `Server error (${res.status})`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

async function withRetry(fn, tries = 2) {
  let last;
  for (let t = 0; t < tries; t++) {
    try { return await fn(); } catch (e) { last = e; await sleep(500); }
  }
  throw last;
}

// ---------------- CAMERA ----------------
// To switch cameras later, edit config.yaml (camera.mode / browser_device_hint / index).
async function startCamera() {
  if (cfg.camera_mode === "opencv") {            // Python owns the camera, we show its stream
    const img = $("mjpeg");
    img.style.display = "block"; $("video").style.display = "none";
    img.src = "/camera/stream";
    cameraReady = true;
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia)
    throw new Error("Camera access needs http://localhost or HTTPS.");
  const open = (video) => navigator.mediaDevices.getUserMedia({ video, audio: false });
  try {
    let s = await open({ width: { ideal: 1920 }, height: { ideal: 1080 } });
    const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    console.log("Available cameras:", cams.map((c) => c.label));   // handy to find your DSLR's name
    const hint = (cfg.browser_device_hint || "").toLowerCase();
    const match = hint && cams.find((c) => c.label.toLowerCase().includes(hint));
    if (match) {                                  // switch to the DSLR/phone "webcam"
      s.getTracks().forEach((t) => t.stop());
      s = await open({ deviceId: { exact: match.deviceId }, width: { ideal: 1920 }, height: { ideal: 1080 } });
    } else if (hint) {
      console.warn(`No camera matching "${cfg.browser_device_hint}", using default.`);
    }
    $("video").srcObject = s;
    await $("video").play();
    cameraReady = true;
  } catch (e) {
    const msgs = {
      NotAllowedError: "Camera permission was denied. Allow camera access and try again.",
      NotFoundError: "No camera found. Check that it's connected.",
      NotReadableError: "The camera is being used by another app. Close it and try again.",
    };
    throw new Error(msgs[e.name] || `Camera error: ${e.message}`);
  }
}

async function capturePhoto(sid, i) {
  if (cfg.camera_mode === "opencv") return api(`/camera/capture/${sid}/${i}`, { method: "POST" });
  const v = $("video");
  if (!v.videoWidth) throw new Error("Camera preview isn't running.");
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);               // un-mirrored frame
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.95));
  if (!blob) throw new Error("Couldn't grab a frame from the camera.");
  const fd = new FormData(); fd.append("file", blob, `photo_${i}.jpg`);
  return api(`/camera/upload/${sid}/${i}`, { method: "POST", body: fd });
}

// ---------------- FLOW ----------------
async function runSession() {
  if (busy || !cameraReady) return;
  busy = true; $("start").disabled = true;
  try {
    const { session_id: sid } = await api("/session", { method: "POST" });
    $("thumbs").innerHTML = ""; show("shoot");

    for (let i = 1; i <= cfg.photos; i++) {
      $("shotlabel").textContent = `Photo ${i} of ${cfg.photos}`;
      for (let s = cfg.countdown_seconds; s > 0; s--) { $("count").textContent = s; await sleep(1000); }
      $("count").textContent = "";
      $("flash").classList.add("on"); setTimeout(() => $("flash").classList.remove("on"), 80);
      await withRetry(() => capturePhoto(sid, i));
      const t = new Image(); t.src = `/camera/photo/${sid}/${i}?t=${Date.now()}`;
      $("thumbs").appendChild(t);
      await sleep(700);
    }

    show("printing");
    const res = await api(`/printing/print/${sid}`, { method: "POST" });
    const link = $("pdfLink");
    link.hidden = cfg.printer_mode !== "pdf" || !res.pdf_url;
    if (!link.hidden) link.href = res.pdf_url;
    show("thanks");
    await sleep(8000);
    reset();
  } catch (e) { fail(e.message || String(e)); }
}

async function reset() {
  try {
    if (!cameraReady) await startCamera();
    busy = false; $("start").disabled = false; show("idle");
  } catch (e) { fail(e.message); }
}

async function init() {
  try {
    cfg = await api("/config");
    $("title").textContent = cfg.event_text;
    $("thanksText").textContent = cfg.event_text + "!";
    await startCamera();
    $("start").disabled = false;
  } catch (e) { fail(e.message); }
}

$("start").addEventListener("click", runSession);
$("retry").addEventListener("click", () => { if (!cfg) location.reload(); else reset(); });
window.addEventListener("unhandledrejection", (e) => fail(e.reason?.message || "Unexpected error"));
init();
