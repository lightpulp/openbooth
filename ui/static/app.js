const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SCREENS = ["idle", "shoot", "review", "confirm", "printing", "thanks", "error"];
let cfg = null, cameraReady = false, busy = false, skipThanks = () => {};

// Focusing the primary button lets Enter / Space (or a USB clicker) drive the booth.
function show(name) {
  SCREENS.forEach((s) => $(s).classList.toggle("active", s === name));
  $(name).querySelector("[data-primary]:not(:disabled)")?.focus({ preventScroll: true });
}
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

// ---------------- PIXEL BUDDY: the dragon mascot ----------------
// 24x24 maps, 3/4 view facing right. r red, s dark red, y yellow, h belly lines, w eye white, g eye shade,
// k ink, m mouth, p tongue, b tear, o outline, . empty. Colors live in style.css.
const BUDDY = [
  "..........ooo.oooo......",
  ".........owwsoswwwo.....",
  "........owwwwowwwwwo....",
  "........owwwwowwwwwo....",
  "........owwkwowkwwwo....",
  "........owwkwowkwwwo....",
  ".......orwwwwowwwwwro...",
  "......orrrggrorgggrrro..",
  ".....osrrrrrrrrrrrrrrro.",
  ".....orrrrrrrrrrrrrkrkro",
  ".....orrrrrrrrrrrrrrrrro",
  "...oosrrrrmrrrrrrrrrrrro",
  "..osyssrrrrmmmmmmmmmmmmo",
  ".osyyyssssryyyyyyyyyyro.",
  ".osyyyyrrrrrryyyyyyooo..",
  "..oyyyrrrrrryyyyyrso....",
  ".o.ossrrrrrryyyyyrrro...",
  "oyoossrrrrrryhhhhyrrro..",
  "orrsssrrrrrryyyyyyrrro..",
  "orrrssrrrrrryhhhhyroo...",
  ".orrrrsrrrrryyyyyro.....",
  "..ooooorrrrrryyyro......",
  "......osssooossso.......",
  ".......ooo...ooo........",
];
const face = (rows) => BUDDY.map((r, y) => rows[y] ?? r);
const FACES = {
  idle: BUDDY,
  blink: face({ 1: ".........orrsosrrro.....", 2: "........orrrrorrrrro....", 3: "........orrrrorrrrro....", 4: "........orrrrorrrrro....", 5: "........oooooooooooo....", 6: ".......orrrrrorrrrrro...", 7: "......orrrrrrorrrrrrro.." }),
  happy: face({ 4: "........owwkwowwkwwo....", 5: "........owkwkowkwkwo....", 13: ".osyyyssssryyyyppppppro.", 14: ".osyyyyrrrrrryyypppooo.." }),
  sad: face({ 4: "........owwwwowwwwwo....", 5: "........owwwwowwwwwo....", 6: ".......orwkwwowkwwwro...", 7: "......orrrkgrorkggrrro..", 8: ".....osrrrrrrrrrbrrrrro.", 9: ".....orrrrrrrrrrbrrkrkro", 13: ".osyyyssssryyyyyyyyyyrmo", 14: ".osyyyyrrrrrryyyyyyoooo." }),
};
// One <path> per color: no hairline seams between pixels (they showed up in the countdown's shadow).
const pixelArt = (rows) => {
  const runs = {};
  rows.forEach((row, y) => row.replace(/([^.])*/g, (run, ch, x) => {
    (runs[ch] ??= []).push(`M${x} ${y}h${run.length}v1h-${run.length}z`);
  }));
  return `<svg viewBox="0 0 ${rows[0].length} ${rows.length}" shape-rendering="crispEdges" aria-hidden="true">${
    Object.entries(runs).map(([ch, d]) => `<path class="${ch}" d="${d.join("")}"/>`).join("")}</svg>`;
};
document.querySelectorAll(".buddy").forEach((el) => {
  el.innerHTML = pixelArt(FACES[el.dataset.face]) + (el.classList.contains("buddy--blink") ? pixelArt(FACES.blink) : "");
});

// 5x7 countdown digits, drawn like the buddy (pixel fonts make 2 look like S at this size)
const DIGITS = {
  0: [".www.", "w...w", "w...w", "w...w", "w...w", "w...w", ".www."],
  1: ["..w..", ".ww..", "..w..", "..w..", "..w..", "..w..", ".www."],
  2: [".www.", "w...w", "....w", "...w.", "..w..", ".w...", "wwwww"],
  3: ["wwww.", "....w", "....w", ".www.", "....w", "....w", "wwww."],
  4: ["...w.", "..ww.", ".w.w.", "w..w.", "wwwww", "...w.", "...w."],
  5: ["wwwww", "w....", "wwww.", "....w", "....w", "w...w", ".www."],
  6: ["..ww.", ".w...", "w....", "wwww.", "w...w", "w...w", ".www."],
  7: ["wwwww", "....w", "...w.", "..w..", ".w...", ".w...", ".w..."],
  8: [".www.", "w...w", "w...w", ".www.", "w...w", "w...w", ".www."],
  9: [".www.", "w...w", "w...w", ".wwww", "....w", "...w.", ".ww.."],
};
const number = (n) => DIGITS[0].map((_, y) => [...String(n)].map((d) => DIGITS[d][y]).join("."));

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
// Resolves with the id of whichever button is clicked first.
function waitClick(...ids) {
  return new Promise((resolve) => {
    const undo = [];
    ids.forEach((id) => {
      const el = $(id);
      const h = () => { undo.forEach((f) => f()); resolve(id); };
      el.addEventListener("click", h);
      undo.push(() => el.removeEventListener("click", h));
    });
  });
}

async function countdown() {
  const c = $("count");
  for (let s = cfg.countdown_seconds; s > 0; s--) {
    c.innerHTML = pixelArt(number(s));
    c.classList.remove("pop"); void c.offsetWidth; c.classList.add("pop");   // restart the pop animation
    await sleep(1000);
  }
  $("count").textContent = "";
  $("flash").classList.add("on"); setTimeout(() => $("flash").classList.remove("on"), 80);
}

async function runSession() {
  if (busy || !cameraReady) return;
  busy = true; $("start").disabled = true;
  try {
    const { session_id: sid } = await api("/session", { method: "POST" });
    $("thumbs").innerHTML = Array.from({ length: cfg.photos }, (_, k) => `<li class="px" data-n="${k + 1}"></li>`).join("");
    const slots = $("thumbs").children;
    const urls = [];

    for (let i = 1; i <= cfg.photos; i++) {
      [...slots].forEach((s, k) => s.classList.toggle("now", k === i - 1));
      while (true) {                                   // loops again only on "Retake"
        $("shotlabel").textContent = $("reviewLabel").textContent = `Photo ${i} of ${cfg.photos}`;
        show("shoot");
        await countdown();
        await withRetry(() => capturePhoto(sid, i)); // same slot -> a retake replaces this photo
        const url = `/camera/photo/${sid}/${i}?t=${Date.now()}`;
        $("reviewImg").src = url;
        $("next").textContent = i === cfg.photos ? "Done" : "Next photo";
        show("review");
        if ((await waitClick("retake", "next")) === "next") {
          urls[i - 1] = url;
          slots[i - 1].innerHTML = `<img src="${url}" alt="Photo ${i}">`;
          break;
        }
      }
    }

    $("grid").innerHTML = urls.map((u, k) => `<img src="${u}" alt="Photo ${k + 1}">`).join("");
    show("confirm");
    const wantPrint = (await waitClick("yes", "no")) === "yes";

    $("printMsg").textContent = wantPrint ? "Printing your strip…" : "Saving your photos…";
    $("printSub").textContent = wantPrint ? "This takes about a minute." : "Just a moment.";
    show("printing");
    const res = await api(`/printing/finish/${sid}?print_it=${wantPrint}`, { method: "POST" });

    $("thanksSub").textContent = res.printed ? "Your photos are printing. Please wait nearby!"
      : wantPrint ? "Test mode: saved as a PDF (printer is off)."
      : "Thanks! Ask the staff if you'd like a digital copy.";
    const link = $("pdfLink");
    link.hidden = cfg.printer_mode !== "pdf" || !res.pdf_url;
    if (!link.hidden) link.href = res.pdf_url;
    show("thanks");
    await new Promise((r) => { skipThanks = r; setTimeout(r, 8000); });   // 8 s also drives the bar on Done (style.css)
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
    $("howto").textContent = `Take ${cfg.photos} photos with a ${cfg.countdown_seconds}-second countdown each, then print your strip.`;
    $("start").disabled = false;
  } catch (e) { fail(e.message); }
}

$("start").addEventListener("click", runSession);
$("done").addEventListener("click", () => skipThanks());
$("retry").addEventListener("click", () => { if (!cfg) location.reload(); else reset(); });
window.addEventListener("unhandledrejection", (e) => fail(e.reason?.message || "Unexpected error"));
init();
