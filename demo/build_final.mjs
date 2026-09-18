/**
 * Re-drives the real UI (same walkthrough as record_demo.mjs), padding each
 * section to approximately the length of its voice note, then concatenates
 * the eight (denoised, normalised) voice notes into one track and muxes it
 * onto the recording, plus an embeddable subtitle track carrying demo.srt.
 *
 * This pass does NOT burn captions into the picture. A live browser's wall
 * clock cannot be trusted to land on the exact word timestamps measured into
 * demo.srt; run demo/sync_final.mjs after this to correct the section-level
 * video/audio drift left by page-load and click overhead, then
 * demo/overlay_captions.mjs to burn the captions in afterward, positioned
 * directly from demo.srt's own timestamps so they land frame-accurate against
 * the narration rather than approximately, against wall-clock.
 *
 *   python3 docs/transcribe_srt.py --model ...   # build demo/out/demo.srt
 *   node demo/build_final.mjs                    # this (server on :8099)
 *   node demo/sync_final.mjs
 *   node demo/overlay_captions.mjs
 *
 * Writes demo/out/demo_final.mp4 (video + narration + soft subtitle track,
 * no burned-in captions yet).
 */
import { chromium } from "playwright";
import { readFileSync, writeFileSync, mkdirSync, readdirSync, renameSync, rmSync } from "fs";
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const NARR_CLEAN = path.join(HERE, "narration_clean");
const NARR_RAW = path.join(HERE, "narration");
const BASE = "http://127.0.0.1:8099";
const CIT = "SID-NG-17665553";
mkdirSync(OUT, { recursive: true });

// -------------------------------------------------------------- read inputs
function ffprobeDuration(p) {
  const out = execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]);
  return parseFloat(out.toString().trim());
}
function findVN(n) {
  // prefers demo/narration_clean (denoised/normalised, made by docs/transcribe_srt.py's
  // recipe) so the audio that ships matches the audio demo.srt was measured against
  for (const dir of [NARR_CLEAN, NARR_RAW]) {
    for (const ext of [".m4a", ".mp3", ".wav", ".aac", ".opus"]) {
      const p = path.join(dir, `VN${String(n).padStart(2, "0")}${ext}`);
      try { readFileSync(p); return p; } catch { /* keep looking */ }
    }
  }
  throw new Error(`missing demo/narration(_clean)/VN${String(n).padStart(2, "0")}.*`);
}
const vnPaths = [1, 2, 3, 4, 5, 6, 7, 8].map(findVN);
const vnDurationsMs = vnPaths.map((p) => Math.round(ffprobeDuration(p) * 1000));

// baseline duration (ms) of each section's interaction script below, so we
// know how much padding to add to hit the matching voice note's length
const BASELINE_MS = [25000, 28000, 24000, 28000, 33000, 27000, 34000, 39000];
const PAD_MS = BASELINE_MS.map((b, i) => Math.max(0, vnDurationsMs[i] - b));
console.log("voice note lengths (ms):", vnDurationsMs);
console.log("padding added per section (ms):", PAD_MS);

const SECTIONS_TOTAL = 8;
const timeline = [];
let t0 = 0;

// Only the small section badge is painted live here. Captions are NOT drawn
// during this recording: a live browser clock cannot be trusted to land on
// the exact measured word timestamps in demo.srt (see demo/overlay_captions.mjs,
// which burns them in afterward from demo.srt directly, so they land frame-
// accurate against the narration instead of approximately, against wall-clock).
const pageInit = `
  (function () {
    function paint() {
      var seg = localStorage.getItem("__seg");
      if (!seg) return;
      var p = JSON.parse(seg);
      var badge = document.getElementById("demo-badge");
      if (!badge) { badge = document.createElement("div"); badge.id = "demo-badge"; document.body.appendChild(badge); }
      badge.innerHTML = '<span class="n">' + p.n + ' / ${SECTIONS_TOTAL}</span><span>' + p.title + '</span>';
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paint);
    else paint();
    setInterval(paint, 400);
  })();
`;

const captionCss = `
#demo-badge {
  position: fixed; top: 62px; right: 10px; z-index: 9999; pointer-events: none;
  background: rgba(11,122,59,0.95); color: #fff; border-radius: 7px;
  font: 600 12px -apple-system, "Segoe UI", Roboto, sans-serif; padding: 6px 10px;
  display: flex; gap: 8px; align-items: center; max-width: 360px;
}
#demo-badge .n { background: #fff; color: #075c2c; border-radius: 4px; padding: 1px 6px; font-weight: 800; }
`;

async function section(page, n, title) {
  await page.evaluate(([n, title]) => localStorage.setItem("__seg", JSON.stringify({ n, title })), [n, title]);
  const atMs = t0 ? Date.now() - t0 : 0;
  if (timeline.length) timeline[timeline.length - 1].endMs = atMs;
  timeline.push({ n, title, startMs: atMs, endMs: null });
  console.log(`  [${n}/${SECTIONS_TOTAL}] ${title}`);
}
const wait = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));
const jpost = (p, b) => fetch(BASE + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }).then(r => r.json());

async function main() {
  await jpost("/api/reseed");

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    recordVideo: { dir: OUT, size: { width: 1280, height: 800 } },
    deviceScaleFactor: 2,
  });
  await context.addInitScript(pageInit);
  await context.addInitScript(`
    var s = document.createElement("style"); s.textContent = ${JSON.stringify(captionCss)};
    document.head ? document.head.appendChild(s) : document.addEventListener("DOMContentLoaded", function(){document.head.appendChild(s)});
  `);
  const page = await context.newPage();
  t0 = Date.now();

  // 1 -------------------------------------------------------- the problem
  await page.goto(BASE + "/");
  await page.evaluate((t0) => localStorage.setItem("__t0", String(t0)), t0);
  await section(page, 1, "The problem: one question, the whole ID card");
  await wait(12000);
  await page.hover("text=Citizen wallet");
  await wait(4000);
  await page.hover("text=Partner console");
  await wait(4000);
  await page.hover("text=Auditor and proof-of-check log");
  await wait(5000);
  await wait(PAD_MS[0]);

  // 2 -------------------------------------------------------- the wallet
  await page.goto(BASE + "/citizen");
  await section(page, 2, "Enrolled once. The values stay on the phone");
  await wait(4000);
  await page.selectOption("#sid", CIT);
  await wait(6000);
  const reveal = page.locator("button:has-text('Reveal to me')").first();
  await reveal.click();
  await wait(6000);
  await page.locator("button:has-text('Hide')").first().click();
  await wait(4000);
  await page.mouse.wheel(0, 260);
  await wait(6000);
  await page.mouse.wheel(0, -260);
  await wait(2000);
  await wait(PAD_MS[1]);

  // 3 -------------------------------------------------------- the bank asks
  await page.goto(BASE + "/partner");
  await section(page, 3, "A bank asks a narrow question");
  await wait(3500);
  await page.selectOption("#partner", "bank-firsttrust");
  await wait(3500);
  await page.selectOption("#qa select", CIT);
  await wait(5000);
  await page.mouse.wheel(0, 200);
  await wait(6000);
  await page.click("text=Send the request");
  await wait(6000);
  await wait(PAD_MS[2]);

  // 4 -------------------------------------------------------- the consent moment
  await page.goto(BASE + "/citizen");
  await section(page, 4, "The consent moment: approve field by field");
  await wait(3000);
  await page.selectOption("#sid", CIT);
  await wait(4000);
  await page.mouse.wheel(0, 380);
  await wait(5000);
  await page.locator("#view .checks .row", { hasText: "name_matches" }).locator("input").uncheck();
  await wait(5000);
  await page.fill("input[placeholder='6-digit OTP from your SIM']", "481920");
  await wait(4000);
  await page.click("text=Approve the ticked fields");
  await wait(7000);
  await wait(PAD_MS[3]);

  // 5 -------------------------------------------------------- the answer
  await page.goto(BASE + "/partner");
  await section(page, 5, "What the bank gets back: yes or no, and a signature");
  await wait(3000);
  await page.selectOption("#partner", "bank-firsttrust");
  await wait(2500);
  await page.click("text=Check for the answer");
  await wait(9000);
  await page.mouse.wheel(0, 240);
  await wait(6000);
  await page.mouse.wheel(0, -240);
  const hosp = await jpost("/api/requests", {
    partner_id: "hosp-lasg", sid: CIT, purpose: "Admit for a procedure",
    scope: ["is_verified", "genotype"],
  });
  await jpost(`/api/requests/${hosp.request_id}/consent`, { approved: ["is_verified", "genotype"], otp: "222222" });
  await page.evaluate((id) => localStorage.setItem("sabiid_last_req", id), hosp.request_id);
  await page.selectOption("#partner", "hosp-lasg");
  await wait(3500);
  await page.click("text=Check for the answer");
  await wait(9000);
  await wait(PAD_MS[4]);

  // 6 -------------------------------------------------------- the ledger and tampering
  await page.goto(BASE + "/auditor");
  await section(page, 6, "The proof-of-check log, and catching an edit");
  await wait(6000);
  await page.click("#verify");
  await wait(5000);
  await page.mouse.wheel(0, 220);
  await wait(4000);
  await page.mouse.wheel(0, -220);
  await page.click("#tamper");
  await wait(7000);
  await page.click("#restore");
  await wait(5000);
  await wait(PAD_MS[5]);

  // 7 -------------------------------------------------------- ghost workers
  await page.goto(BASE + "/partner");
  await section(page, 7, "Ghost workers and ghost pensioners");
  await wait(3000);
  await page.selectOption("#partner", "payroll-fmw");
  await wait(4000);
  await page.click("text=Run the monthly cycle");
  await wait(9000);
  await page.mouse.wheel(0, 420);
  await wait(9000);
  await page.mouse.wheel(0, 420);
  await wait(9000);
  await wait(PAD_MS[6]);

  // 8 -------------------------------------------------------- lights out, and USSD
  await page.mouse.wheel(0, -900);
  await section(page, 8, "When the lights go out, and the no-smartphone path");
  await wait(3000);
  await page.check("#opt-offline");
  await wait(4000);
  await page.click("text=Run the monthly cycle");
  await wait(7000);
  await page.click("text=Reconcile the queued cycle");
  await wait(8000);
  await page.goto(BASE + "/ussd");
  await wait(3500);
  await page.selectOption("#sid", CIT);
  await wait(2500);
  await page.click("#dial");
  await wait(6000);
  await page.click("[data-a='history']");
  await wait(5000);
  await wait(PAD_MS[7]);

  timeline[timeline.length - 1].endMs = Date.now() - t0;

  const videoPath = await page.video().path();
  await context.close();
  await browser.close();

  renameSync(videoPath, path.join(OUT, "demo_captioned.webm"));
  for (const f of readdirSync(OUT).filter((f) => /^page.*\.webm$/.test(f))) rmSync(path.join(OUT, f));

  execFileSync("ffmpeg", ["-y", "-i", path.join(OUT, "demo_captioned.webm"),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
    path.join(OUT, "demo_captioned_silent.mp4")], { stdio: "ignore" });
  console.log("rendered the captioned silent video");

  // concatenate the eight voice notes into one track
  const listPath = path.join(OUT, "audio_list.txt");
  writeFileSync(listPath, vnPaths.map((p) => `file '${p.replace(/'/g, "'\\''")}'`).join("\n") + "\n");
  execFileSync("ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", listPath,
    "-c:a", "aac", "-b:a", "160k", path.join(OUT, "audio_concat.m4a")], { stdio: "ignore" });
  console.log("concatenated narration");

  // mux video + narration + an embeddable subtitle track onto one file
  execFileSync("ffmpeg", ["-y",
    "-i", path.join(OUT, "demo_captioned_silent.mp4"),
    "-i", path.join(OUT, "audio_concat.m4a"),
    "-i", path.join(OUT, "demo.srt"),
    "-map", "0:v", "-map", "1:a", "-map", "2:s",
    "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
    "-movflags", "+faststart",
    path.join(OUT, "demo_final.mp4")], { stdio: "ignore" });

  const sections = timeline.map((s) => ({
    section: s.n, title: s.title,
    start: +(s.startMs / 1000).toFixed(2), end: +(s.endMs / 1000).toFixed(2),
    seconds: +((s.endMs - s.startMs) / 1000).toFixed(2),
    voice_note_seconds: +(vnDurationsMs[s.n - 1] / 1000).toFixed(2),
  }));
  writeFileSync(path.join(OUT, "sections_final.json"), JSON.stringify({ sections }, null, 2));
  console.log("\nwrote demo/out/demo_final.mp4\n");
  console.table(sections);
}

main().catch((e) => { console.error(e); process.exit(1); });
