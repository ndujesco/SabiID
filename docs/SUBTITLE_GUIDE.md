# Narration and subtitles

The recorded walkthrough is silent and split into eight sections, guided by
`docs/VIDEO_SCRIPT.md`. Here is how it gets narration and captions that are
measured against your voice, not estimated.

## Step 1: record eight voice notes

Record one voice note per section, in your own words, and save them as:

```
demo/narration/VN01.m4a
demo/narration/VN02.m4a
...
demo/narration/VN08.m4a
```

`.mp3`, `.wav`, `.aac` and `.opus` all work too.

## Step 2: measure real caption timing

```bash
brew install whisper-cpp
curl -L -o ggml-base.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
python3 docs/transcribe_srt.py --model ggml-base.en.bin
```

This is the part worth explaining, because the first version of this pipeline
got it wrong. It used to estimate caption timing by splitting the written
script proportionally across each voice note's length, weighted by character
count. The section *totals* matched, but the estimate did not track pauses or
a reader going faster or slower than average in the middle of a section, so a
caption could show text a sentence or two ahead of or behind what was actually
being said at that moment.

`transcribe_srt.py` fixes that by measuring instead of guessing. It runs each
voice note through a local speech-to-text model (whisper.cpp, with word-level
timestamps) and uses the real timestamp of the real word spoken. Plain
transcription alone is not accurate enough to put on screen verbatim (it
mishears "SabiID" as "cyber ID", "over 18" as "overeating", and so on), so the
caption text stays the clean, correct wording from `docs/VIDEO_SCRIPT.md`: each
script word is aligned against the transcript by position, borrows that word's
measured timestamp, and only the short stretches where the transcript disagrees
with the script (a misheard word, not a mistimed one) fall back to proportional
placement between the nearest two measured anchors either side. The script
prints how much of each section was directly measured versus interpolated, so
this is checkable, not just asserted:

```
sec  source          len(s)  words   measured
  1  VN01.m4a         33.40    102     81/102 ( 79%)
  ...
```

It also, in the same pass, denoises and loudness-normalises each voice note
into `demo/narration_clean/`, which is what actually gets muxed into the final
video (a gentle chain only: a highpass to cut handling rumble, a touch of
presence EQ, then loudness normalising to -16 LUFS. An earlier, heavier
denoise pass measurably hurt both intelligibility and the speech-to-text
accuracy above, which is how that was caught; light and clean beat aggressive
here).

## Step 3: build the base video and mux narration

```bash
python3 -m backend.app &          # server must be running
node demo/build_final.mjs
node demo/sync_final.mjs
```

`build_final.mjs` re-drives the real UI, the same walkthrough as
`demo/record_demo.mjs`, padding each section toward its voice note's length,
then concatenates your eight (cleaned) voice notes into one track and muxes
them plus a subtitle track onto the recording. It does not burn captions into
the picture at this stage.

`sync_final.mjs` corrects the drift that padding alone cannot: a real browser
click or page load takes a slightly different amount of wall-clock time each
run, so a section can end up a little longer than planned, and that does not
cancel out between sections, it adds up. This script reads the exact section
boundaries the recording actually hit and retimes each section's video, on its
own, to the exact length of its own voice note, a speed change under 2% in
every section observed so far, imperceptible on playback. Check the numbers it
prints: it reports the final video length and the narration length, and they
should match to the millisecond.

## Step 4: burn in the captions

```bash
node demo/overlay_captions.mjs
```

This is the step that actually delivers exact audio-to-caption sync, and it
deliberately does not reuse the live recording for it. A live browser's wall
clock, even after step 3's correction, is still only *approximately* right
relative to the narration in the middle of a section (see step 3). Burning
captions in from a live recording inherits that approximation.

Instead, `overlay_captions.mjs` renders each caption line once, offline, as its
own transparent image (this machine's ffmpeg has no libass or drawtext, which
is why this goes through the browser for text rendering and plain `overlay`
for compositing rather than the `subtitles` filter), then tells ffmpeg to show
each one for exactly the `[start, end)` window `demo.srt` gives it, nothing
approximated, no wall clock involved. Since `demo.srt`'s timestamps are the
same ones measured against the same audio that got muxed in during step 3, the
captions and the narration are tied to the same measurement, not to two
separate approximations of it.

Overwrites `demo/out/demo_final.mp4` in place. That file is the one to submit.

### Verifying it, not just trusting it

Pick a handful of timestamps from `demo/out/demo.srt` scattered through the
video, including some late inside the longest sections (that is where drift
would show up worst), and pull a frame from `demo_final.mp4` at each one:

```bash
ffmpeg -ss 208.55 -i demo/out/demo_final.mp4 -frames:v 1 check.png
```

The caption burned into that frame should be exactly the cue whose `[start,
end)` window in `demo.srt` contains that timestamp. That is how this was
checked before calling it done, not assumed from the pipeline being correct in
theory.

## If whisper.cpp is not available

`python3 docs/build_srt.py` is the original, proportional-estimate fallback.
It still works end to end (steps 3 and 4 read whatever is in `demo/out/demo.srt`
regardless of which script wrote it), but the mid-section timing will be a
guess again, not a measurement. Prefer `transcribe_srt.py` whenever whisper.cpp
is available.

## Regenerating the silent, unnarrated recording

```bash
python3 -m backend.app &          # server on :8099
node demo/record_demo.mjs         # rewrites demo/out/demo.mp4 and sections.json
```

This is the version without narration or captions, useful for re-checking the
UI walkthrough on its own. The pacing lives in the `wait(...)` calls; the same
calls, plus per-section padding, are duplicated in `demo/build_final.mjs`, so a
change to the walkthrough should be made in both files.
