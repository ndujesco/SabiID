/**
 * Drives the real SabiID UI end to end and records it to a single silent video,
 * with an on-screen section banner so voice notes can be recorded and synced
 * against it afterward. Writes demo/out/sections.json with the timecodes.
 *
 *   node demo/record_demo.mjs            (server must be running on :8099)
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync, readdirSync, renameSync, rmSync } from "fs";
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const BASE = "http://127.0.0.1:8099";
const CIT = "SID-NG-17665553"; // Adaeze Chioma Nwosu, adult, Lagos, consistent records
mkdirSync(OUT, { recursive: true });

const SECTIONS_TOTAL = 8;
const timeline = [];
let t0 = 0;

const bannerInit = `
  (function () {
    function paint() {
      var seg = localStorage.getItem("__seg");
      if (!seg) return;
      var b = document.getElementById("demo-banner");
      if (!b) { b = document.createElement("div"); b.id = "demo-banner"; document.body.appendChild(b); }
      var p = JSON.parse(seg);
      b.innerHTML = '<span class="n">' + p.n + ' / ${SECTIONS_TOTAL}</span><span>' + p.title + '</span>';
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paint);
    else paint();
    setInterval(paint, 400);
  })();
`;

async function section(page, n, title) {
  await page.evaluate(([n, title]) => localStorage.setItem("__seg", JSON.stringify({ n, title })), [n, title]);
  const atMs = t0 ? Date.now() - t0 : 0;
  if (timeline.length) timeline[timeline.length - 1].endMs = atMs;
  timeline.push({ n, title, startMs: atMs, endMs: null });
  console.log(`  [${n}/${SECTIONS_TOTAL}] ${title}`);
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const jpost = (p, b) => fetch(BASE + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }).then(r => r.json());

async function main() {
  await jpost("/api/reseed");

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    recordVideo: { dir: OUT, size: { width: 1280, height: 800 } },
    deviceScaleFactor: 2,
  });
  await context.addInitScript(bannerInit);
  const page = await context.newPage();
  t0 = Date.now();

  // 1 -------------------------------------------------------- the problem
  await page.goto(BASE + "/");
  await section(page, 1, "The problem: one question, the whole ID card");
  await wait(12000);
  await page.hover("text=Citizen wallet");
  await wait(4000);
  await page.hover("text=Partner console");
  await wait(4000);
  await page.hover("text=Auditor and proof-of-check log");
  await wait(5000);

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
  // a hospital asks for something nobody has verified
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

  timeline[timeline.length - 1].endMs = Date.now() - t0;

  const videoPath = await page.video().path();
  await context.close();
  await browser.close();

  renameSync(videoPath, path.join(OUT, "demo.webm"));
  for (const f of readdirSync(OUT).filter((f) => /^page.*\.webm$/.test(f))) {
    rmSync(path.join(OUT, f));
  }

  // transcode to a widely playable mp4
  try {
    execFileSync("ffmpeg", ["-y", "-i", path.join(OUT, "demo.webm"),
      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
      "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", path.join(OUT, "demo.mp4")],
      { stdio: "ignore" });
    console.log("transcoded demo/out/demo.mp4");
  } catch (e) {
    console.log("ffmpeg transcode skipped:", e.message);
  }

  const sections = timeline.map((s) => ({
    section: s.n, title: s.title,
    start: +(s.startMs / 1000).toFixed(2),
    end: +(s.endMs / 1000).toFixed(2),
    seconds: +((s.endMs - s.startMs) / 1000).toFixed(2),
  }));
  writeFileSync(path.join(OUT, "sections.json"), JSON.stringify({ sections, total_seconds: sections.at(-1).end }, null, 2));
  console.log("\nwrote demo/out/demo.webm and demo/out/sections.json");
  console.table(sections);
}

main().catch((e) => { console.error(e); process.exit(1); });
