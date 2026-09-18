# SabiID

**Proving a fact without revealing the whole record.**
ICSC 2026 Universities Hackathon, Track B (Digital Identity, Trust and ICT).
Team Zer0Day Saints.

SabiID is a broker that sits between the identity sources (NIN, BVN, the Civil
Registration service) and the businesses that check identity. It answers one
narrow question at a time (is this person over 18, does this name match, is this
still a living matching person), signs the answer, and writes one line to a
tamper-evident log, without ever copying anyone's record. Because there is no
master database in the design, there is no single file to steal.

The memorable case it is built around is catching **ghost workers and ghost
pensioners**: the same prove-without-revealing check, asked on a payroll schedule
instead of once.

## What is in here

| Path | What it is |
|---|---|
| `backend/` | The gateway. Python standard library plus `cryptography` for Ed25519. |
| `backend/crypto.py` | Signed attestations, SD-JWT selective disclosure, scrypt biometric hashing. |
| `backend/gateway.py` | Scoped requests, per-field consent, predicate evaluation. |
| `backend/ledger.py` | The hash-chained proof-of-check log and its verifier. |
| `backend/payroll.py` | The ghost worker / ghost pensioner sweep. |
| `backend/data_gen.py` | Generates all synthetic data. Fixed seed. |
| `frontend/` | Four plain HTML pages: citizen, partner, auditor, USSD. No build step. |
| `tests/run_tests.py` | 34 assertions, no framework. |
| `demo/record_demo.mjs` | Playwright driver that records the silent walkthrough. |
| `demo/build_final.mjs` | Re-drives the walkthrough (no captions) and muxes your narration onto it. |
| `demo/sync_final.mjs` | Retimes each section so its video matches its voice note's length exactly. |
| `demo/overlay_captions.mjs` | Burns captions into the picture from demo.srt's own timestamps. |
| `docs/TECHNICAL_WRITEUP.md` | The four page write-up. |
| `docs/VIDEO_SCRIPT.md` | Per-section voiceover script. |
| `docs/transcribe_srt.py` | Builds demo.srt from measured speech (whisper.cpp), not estimated timing. |
| `docs/build_srt.py` | Fallback: estimates demo.srt by proportion, if whisper.cpp isn't installed. |
| `data/DATA_CARD.md` | Where the synthetic data came from and how it was made. |

## Run it

Requires Python 3.10 or newer and the `cryptography` package.

```bash
pip3 install -r requirements.txt          # just: cryptography
python3 -m backend.data_gen               # generate synthetic data, seed the database
python3 -m backend.app                    # serve on http://127.0.0.1:8099
```

Then open <http://127.0.0.1:8099>. Or use `./run.sh`.

Run the tests:

```bash
python3 tests/run_tests.py               # uses a throwaway database
```

## Re-record the demo

```bash
cd demo && npm install && npx playwright install chromium
cd .. && python3 -m backend.app &        # server must be up
node demo/record_demo.mjs                # writes demo/out/demo.mp4 and sections.json
```

## Add narration and subtitles

1. Record one voice note per section into `demo/narration/VN01.m4a` .. `VN08.m4a`.
   The script is in `docs/VIDEO_SCRIPT.md`.
2. `python3 docs/transcribe_srt.py --model /path/to/ggml-base.en.bin` measures
   real word timestamps from your voice notes (via whisper.cpp) and builds
   `demo/out/demo.srt` from them, not from a guess. Get a model with, for
   example, `curl -L -o ggml-base.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin`.
3. `node demo/build_final.mjs` (server must be running) re-drives the UI and
   muxes your narration and a subtitle track onto it. No captions yet.
4. `node demo/sync_final.mjs` retimes each section's video to the exact length
   of its matching voice note, so every section boundary lands on the same
   instant in video and audio.
5. `node demo/overlay_captions.mjs` burns the captions into the picture,
   positioned directly from demo.srt's own timestamps rather than approximated
   during a live recording, so they land frame-accurate against the narration.

See `docs/SUBTITLE_GUIDE.md` for why it works this way, including the fallback
path if whisper.cpp is not available.

## Scope, honestly

This is a three-week prototype of one slice, not the national gateway. The OTP is
simulated, the biometric is a stand-in string, and the identity sources are local
JSON files. `docs/TECHNICAL_WRITEUP.md` lists every place it breaks as clearly as
where it works.

All data is synthetic. No real person's NIN, BVN or record is used anywhere.
