/**
 * Fixes video/audio/subtitle drift left over from build_final.mjs.
 *
 * The recording's actions take slightly longer, wall-clock, than the padding
 * math assumed (page loads and clicks have real network/DOM latency that
 * wasn't fully budgeted for), so each section's video runs a little longer
 * than its matching voice note. That overrun is small per section (0.1-0.5s)
 * but it accumulates, so by the later sections the video is visibly behind
 * where the narration and captions (which follow the voice notes exactly)
 * have got to.
 *
 * The fix: take the exact section boundaries the recording actually hit
 * (demo/out/sections_final.json), retime each section's video to precisely the
 * length of its own voice note (a sub-1% speed change, imperceptible), then
 * concatenate and remux. Every section boundary then lands on the same
 * instant in video, audio and subtitles.
 *
 *   node demo/sync_final.mjs      (after build_final.mjs has already run once)
 *
 * Overwrites demo/out/demo_final.mp4.
 */
import { readFileSync, writeFileSync, mkdirSync, rmSync } from "fs";
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const NARR_CLEAN = path.join(HERE, "narration_clean");
const NARR_RAW = path.join(HERE, "narration");
const PARTS = path.join(OUT, "sync_parts");
rmSync(PARTS, { recursive: true, force: true });
mkdirSync(PARTS, { recursive: true });

function ffprobeDuration(p) {
  const out = execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]);
  return parseFloat(out.toString().trim());
}
function findVN(n) {
  for (const dir of [NARR_CLEAN, NARR_RAW]) {
    for (const ext of [".m4a", ".mp3", ".wav", ".aac", ".opus"]) {
      const p = path.join(dir, `VN${String(n).padStart(2, "0")}${ext}`);
      try { readFileSync(p); return p; } catch { /* keep looking */ }
    }
  }
  throw new Error(`missing demo/narration(_clean)/VN${String(n).padStart(2, "0")}.*`);
}

const sections = JSON.parse(readFileSync(path.join(OUT, "sections_final.json"), "utf8")).sections;
const vnDurations = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ffprobeDuration(findVN(n)));

console.log("sec   actual(A)  target(T)   speed(T/A)");
const segFiles = [];
sections.forEach((s, i) => {
  const A = s.seconds;
  const T = vnDurations[i];
  const k = T / A; // setpts multiplier: <1 speeds the clip up, >1 slows it down
  console.log(`${String(s.section).padStart(2)}    ${A.toFixed(3).padStart(8)}   ${T.toFixed(3).padStart(8)}   ${k.toFixed(4)}`);

  // two passes, kept separate so the -to trim point is never read off an
  // already-retimed timeline (that ordering bug is why the first attempt at
  // this script silently produced untouched-duration segments)
  const raw = path.join(PARTS, `raw${String(s.section).padStart(2, "0")}.mp4`);
  execFileSync("ffmpeg", ["-y",
    "-i", path.join(OUT, "demo_captioned_silent.mp4"),
    "-ss", String(s.start), "-to", String(s.end),
    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
    raw], { stdio: "ignore" });

  const seg = path.join(PARTS, `seg${String(s.section).padStart(2, "0")}.mp4`);
  execFileSync("ffmpeg", ["-y",
    "-i", raw,
    "-vf", `setpts=(PTS-STARTPTS)*${k.toFixed(6)},fps=25`,
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
    seg], { stdio: "ignore" });
  segFiles.push(seg);
});

const listPath = path.join(PARTS, "list.txt");
writeFileSync(listPath, segFiles.map((f) => `file '${f.replace(/'/g, "'\\''")}'`).join("\n") + "\n");
const videoSynced = path.join(PARTS, "video_synced.mp4");
execFileSync("ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", listPath,
  "-c", "copy", videoSynced], { stdio: "ignore" });

const finalOut = path.join(OUT, "demo_final.mp4");
execFileSync("ffmpeg", ["-y",
  "-i", videoSynced,
  "-i", path.join(OUT, "audio_concat.m4a"),
  "-i", path.join(OUT, "demo.srt"),
  "-map", "0:v", "-map", "1:a", "-map", "2:s",
  "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
  "-movflags", "+faststart",
  finalOut], { stdio: "ignore" });

const finalDur = ffprobeDuration(finalOut);
const audioDur = ffprobeDuration(path.join(OUT, "audio_concat.m4a"));
console.log(`\nfinal video: ${finalDur.toFixed(3)}s, narration: ${audioDur.toFixed(3)}s, ` +
  `difference: ${(finalDur - audioDur).toFixed(3)}s`);
console.log("wrote demo/out/demo_final.mp4 (retimed, section boundaries now match the narration exactly)");
