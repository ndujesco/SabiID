"""
Builds demo/out/demo.srt by measuring, not estimating, when each word of the
script is actually spoken.

Earlier this project estimated caption timing by splitting the written script
proportionally across each voice note's length, weighted by character count.
That is a guess: it does not know about pauses, filler words, or a reader
going faster or slower than average, and on inspection the guess was visibly
off inside a section even though the section *totals* matched.

This script measures it instead. It runs each voice note through a local
speech-to-text model (whisper.cpp, with token-level DTW timestamps) to get a
real timestamp for real speech. Plain transcription alone is not reliable
enough to put on screen verbatim (it mishears "SabiID" as "cyber ID", "over
18" as "overeating", and so on), so the on-screen text stays the clean,
correct wording from docs/VIDEO_SCRIPT.md: every script word is aligned
against the nearest matching transcribed word by position, borrows that
word's real timestamp, and only the (usually short, always tightly bounded)
stretches where the transcript disagrees with the script fall back to
proportional placement between the nearest two measured anchors either side.
The script reports how much of each section was directly measured versus
interpolated, so the result is checkable rather than assumed.

Requires whisper-cli (`brew install whisper-cpp`) and a ggml model on disk,
for example:
    curl -L -o ggml-base.en.bin \\
      https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin

Usage:
    python3 docs/transcribe_srt.py --model /path/to/ggml-base.en.bin
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_MD = ROOT / "docs" / "VIDEO_SCRIPT.md"
CLEAN_DIR = ROOT / "demo" / "narration_clean"
RAW_DIR = ROOT / "demo" / "narration"
OUT_DIR = ROOT / "demo" / "out"

MAX_WORDS_PER_CUE = 11
SECTION_RE = re.compile(
    r"<!--SECTION\s+(\d+)\s*\|\s*(.+?)\s*\|\s*target\s+(\d+)s-->(.*?)<!--/SECTION-->",
    re.DOTALL,
)


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


# ------------------------------------------------------------------- inputs

def parse_script() -> list[dict]:
    text = SCRIPT_MD.read_text()
    out = []
    for m in SECTION_RE.finditer(text):
        n, title, _target, body = m.groups()
        body = body.replace(">>>", " ").replace("\n", " ")
        body = re.sub(r"\s+", " ", body).strip()
        out.append({"n": int(n), "title": title, "words": body.split(" ")})
    return out


def find_vn(n: int) -> Path:
    for base in (CLEAN_DIR, RAW_DIR):
        for ext in (".m4a", ".mp3", ".wav", ".aac", ".opus"):
            p = base / f"VN{n:02d}{ext}"
            if p.exists():
                return p
    raise SystemExit(f"missing demo/narration(_clean)/VN{n:02d}.*")


def ffprobe_duration_ms(p: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out) * 1000


def to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)],
        check=True,
    )


# --------------------------------------------------------------- ASR + words

def transcribe_words(model: str, wav: Path, tmp: Path) -> list[dict]:
    """
    Full-quality decode with token-level DTW timestamps, then merged back into
    whole words (a mis-heard word can span more than one BPE token). Returns
    [{text, start_ms, end_ms}, ...] in order.
    """
    out_base = tmp / wav.stem
    subprocess.run(
        ["whisper-cli", "-m", model, "-l", "en", "-dtw", "base.en",
         "-oj", "-ojf", "-of", str(out_base), str(wav)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads((tmp / f"{wav.stem}.json").read_text())
    words: list[dict] = []
    for seg in data["transcription"]:
        for t in seg["tokens"]:
            txt = t["text"]
            if re.fullmatch(r"\[_[A-Z]+(_\d+)?\]", txt):
                continue  # [_BEG_], [_TT_238], etc: not text
            start, end = float(t["offsets"]["from"]), float(t["offsets"]["to"])
            if txt.startswith(" ") or not words:
                words.append({"text": txt.strip(), "start_ms": start, "end_ms": end})
            else:
                words[-1]["text"] += txt
                words[-1]["end_ms"] = end
    return [w for w in words if w["text"]]


# ---------------------------------------------------------- forced alignment

def align(ref_words: list[str], heard: list[dict], section_ms: float) -> list[dict]:
    """
    Returns one timed entry per ref word: {"text", "start_ms", "end_ms",
    "measured": bool}. Matched stretches borrow the transcript's timestamp
    directly; everything else is placed proportionally between the measured
    anchors immediately either side (or the section edges, at the ends).
    """
    import difflib

    ref_norm = [norm(w) for w in ref_words]
    heard_norm = [norm(w["text"]) for w in heard]
    sm = difflib.SequenceMatcher(None, ref_norm, heard_norm, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]

    timed: list[dict | None] = [None] * len(ref_words)
    for b in blocks:
        for k in range(b.size):
            h = heard[b.b + k]
            timed[b.a + k] = {"start_ms": h["start_ms"], "end_ms": h["end_ms"], "measured": True}

    # fill the gaps between (and around) measured anchors proportionally
    i = 0
    n = len(ref_words)
    while i < n:
        if timed[i] is not None:
            i += 1
            continue
        j = i
        while j < n and timed[j] is None:
            j += 1
        left = timed[i - 1]["end_ms"] if i > 0 else 0.0
        right = timed[j]["start_ms"] if j < n else section_ms
        span = ref_words[i:j]
        weights = [max(len(w), 3) for w in span]
        total = sum(weights) or 1
        t = left
        for k, w in zip(range(i, j), weights):
            dur = (right - left) * (w / total)
            timed[k] = {"start_ms": t, "end_ms": t + dur, "measured": False}
            t += dur
        i = j

    return [{"text": w, **timed[k]} for k, w in enumerate(ref_words)]


def group_cues(timed_words: list[dict], offset_ms: float) -> list[dict]:
    cues, current = [], []

    def flush():
        if not current:
            return
        cues.append({
            "text": " ".join(w["text"] for w in current),
            "start_ms": offset_ms + current[0]["start_ms"],
            "end_ms": offset_ms + current[-1]["end_ms"],
        })
        current.clear()

    for w in timed_words:
        current.append(w)
        if re.search(r"[.?!]$", w["text"]) or len(current) >= MAX_WORDS_PER_CUE:
            flush()
    flush()

    merged: list[dict] = []
    for c in cues:
        if merged and len(c["text"].split()) < 3:
            merged[-1]["text"] += " " + c["text"]
            merged[-1]["end_ms"] = c["end_ms"]
        else:
            merged.append(c)
    return merged


def srt_ts(ms: float) -> str:
    ms = int(round(ms))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# -------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="path to a ggml whisper.cpp model")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sections = parse_script()
    srt_lines, cue_no = [], 0
    offset_ms = 0.0
    report = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for sec in sections:
            n = sec["n"]
            src = find_vn(n)
            wav = tmp / f"vn{n:02d}.wav"
            to_wav(src, wav)
            section_ms = ffprobe_duration_ms(src)

            heard = transcribe_words(args.model, wav, tmp)
            timed = align(sec["words"], heard, section_ms)
            cues = group_cues(timed, offset_ms)
            for c in cues:
                cue_no += 1
                srt_lines.append(f"{cue_no}\n{srt_ts(c['start_ms'])} --> {srt_ts(c['end_ms'])}\n{c['text']}\n")

            measured = sum(1 for w in timed if w["measured"])
            report.append((n, src.name, section_ms / 1000, len(sec["words"]), measured))
            offset_ms += section_ms

    (OUT_DIR / "demo.srt").write_text("\n".join(srt_lines))

    print(f"{'sec':>3}  {'source':<14} {'len(s)':>7}  {'words':>5}  {'measured':>9}")
    for n, name, secs, wc, measured in report:
        pct = 100 * measured / wc if wc else 0
        print(f"{n:>3}  {name:<14} {secs:>7.2f}  {wc:>5}  {measured:>6}/{wc} ({pct:4.0f}%)")
    print(f"\ntotal narration {offset_ms/1000:.1f}s, {cue_no} cues")
    print(f"wrote {OUT_DIR / 'demo.srt'}")


if __name__ == "__main__":
    main()
