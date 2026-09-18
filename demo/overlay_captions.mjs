/**
 * Burns the captions into the picture, positioned directly from demo.srt's
 * own timestamps, frame-accurate against the narration.
 *
 * Nothing here is a live recording, so there is no wall-clock drift to worry
 * about: each cue is rendered once, offline, as its own transparent PNG (same
 * bar styling as the rest of the site), and ffmpeg overlays each one for
 * exactly the [start, end) window demo.srt gives it. This machine's ffmpeg
 * has no libass or drawtext, which is why this goes through the browser for
 * rendering and plain `overlay` for compositing instead of the `subtitles`
 * filter.
 *
 *   node demo/overlay_captions.mjs      (after build_final.mjs + sync_final.mjs)
 *
 * Overwrites demo/out/demo_final.mp4 in place with the captioned version.
 */
import { chromium } from "playwright";
import { readFileSync, writeFileSync, mkdirSync, rmSync } from "fs";
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const PNG_DIR = path.join(OUT, "captions_png");
rmSync(PNG_DIR, { recursive: true, force: true });
mkdirSync(PNG_DIR, { recursive: true });

const W = 1280, H = 800;

function parseSrt(text) {
  const toMs = (t) => {
    const [, h, m, s, ms] = t.match(/(\d\d):(\d\d):(\d\d),(\d\d\d)/);
    return ((+h * 60 + +m) * 60 + +s) * 1000 + +ms;
  };
  const blocks = text.trim().split(/\n\s*\n/).filter(Boolean);
  return blocks.map((b) => {
    const lines = b.split("\n");
    const [start, end] = lines[1].split(" --> ").map(toMs);
    return { start: start / 1000, end: end / 1000, text: lines.slice(2).join(" ") };
  });
}

const cues = parseSrt(readFileSync(path.join(OUT, "demo.srt"), "utf8"));
console.log(`${cues.length} cues to render`);

const page_html = `<!doctype html><meta charset="utf-8"><style>
  html, body { margin: 0; width: ${W}px; height: ${H}px; background: transparent; }
  #caption-bar {
    position: absolute; left: 6%; right: 6%; bottom: 22px;
    background: rgba(10,12,11,0.82); color: #fff; text-align: center;
    font: 600 19px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 10px 18px; border-radius: 8px;
  }
</style><div id="caption-bar"></div>`;
const htmlPath = path.join(OUT, "_caption_bar.html");
writeFileSync(htmlPath, page_html);

async function renderPngs() {
  const browser = await chromium.launch();
  // deviceScaleFactor 1: the screenshot must come out at exactly W x H pixels
  // to overlay onto the video frame with no scaling, at (0,0)
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await page.goto("file://" + htmlPath);
  const bar = page.locator("#caption-bar");
  const files = [];
  for (let i = 0; i < cues.length; i++) {
    await bar.evaluate((el, text) => { el.textContent = text; }, cues[i].text);
    const file = path.join(PNG_DIR, `cue${String(i).padStart(3, "0")}.png`);
    await page.screenshot({ path: file, omitBackground: true });
    files.push(file);
  }
  await browser.close();
  return files;
}

function buildOverlayGraph(files) {
  const lines = [];
  let prev = "[0:v]";
  cues.forEach((c, i) => {
    const out = i === cues.length - 1 ? "[vout]" : `[v${i}]`;
    // a hair of pad on the end so a cue doesn't blink off one frame early
    const end = (c.end + 0.04).toFixed(3);
    lines.push(`${prev}[${i + 1}:v]overlay=0:0:enable='between(t,${c.start.toFixed(3)},${end})'${out}`);
    prev = out;
  });
  return lines.join(";\n");
}

async function main() {
  const files = await renderPngs();
  console.log("rendered caption images");

  const graphPath = path.join(OUT, "_overlay_graph.txt");
  writeFileSync(graphPath, buildOverlayGraph(files));

  const args = ["-y", "-i", path.join(OUT, "demo_final.mp4")];
  for (const f of files) args.push("-i", f);
  args.push(
    "-filter_complex_script", graphPath,
    "-map", "[vout]", "-map", "0:a", "-map", "0:s",
    "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-c:a", "copy", "-c:s", "mov_text",
    "-movflags", "+faststart",
    path.join(OUT, "demo_final_captioned.mp4"),
  );
  console.log(`compositing ${files.length} caption layers onto the video (this takes a while)...`);
  execFileSync("ffmpeg", args, { stdio: "inherit" });

  rmSync(path.join(OUT, "demo_final.mp4"));
  execFileSync("mv", [path.join(OUT, "demo_final_captioned.mp4"), path.join(OUT, "demo_final.mp4")]);
  rmSync(PNG_DIR, { recursive: true, force: true });
  rmSync(htmlPath, { force: true });
  rmSync(graphPath, { force: true });

  console.log("\nwrote demo/out/demo_final.mp4 with captions burned in from demo.srt's own timestamps");
}

main().catch((e) => { console.error(e); process.exit(1); });
