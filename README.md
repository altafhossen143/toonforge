# ToonForge

> **Paste a story → get a finished cartoon episode.**
> 100–400 words in, 60–90 s of fully-voiced vertical animation (1080×1920) out.

🎬 **Demo video:** [coming soon — recorded live run, ≤3 min](https://www.youtube.com/placeholder)

*Built for the Meta Global AI Developer Hackathon 2026 — Indie Dev track, theme "Build for Your World".*

## What it does

ToonForge compresses a week of manual cartoon production into one automated run.
A Bangla or English short story goes through a five-stage agentic pipeline —
**Muse Spark directs** (script + character bible), **Muse Image paints**
(reference-locked scenes), a **vision-QA loop** scores and regenerates weak
scenes, **TTS voices** act every line, and a deterministic **ffmpeg renderer**
assembles the episode. Every run writes a `run_report.json` with QA scores,
API cost, and wall time — the numbers below come straight from those logs.

```
                    ┌─────────────────────────────────────────────┐
 story.txt (100-400 words, bn/en)                                 │
                    ▼                                             │
 ┌──────────────────────────────────────────────────────────┐    │
 │ [1] DIRECTOR — Muse Spark 1.3 (structured output)        │    │
 │ story → script.json (scenes, dialogue, hook+cliffhanger) │    │
 │       → character_bible.json (appearance tokens, voices) │    │
 └────────────────────────────┬─────────────────────────────┘    │
                              ▼                                  │
 ┌──────────────────────────────────────────────────────────┐    │
 │ [2] ART — Muse Image 1.0                                 │    │
 │ reference sheet per character → scenes via image-EDIT    │    │
 │ with character reference + locked appearance tokens      │    │
 └────────────────────────────┬─────────────────────────────┘    │
                              ▼                                  │
 ┌──────────────────────────────────────────────────────────┐    │
 │ [3] QA LOOP — Muse Spark 1.3 vision                      │    │
 │ score every scene 0–1 (character/content/emotion/artif.) │    │
 │ < 0.80 → regenerate, max 2 retries, all scores logged    │    │
 └────────────────────────────┬─────────────────────────────┘    │
                              ▼                                  │
 ┌──────────────────────────────────────────────────────────┐    │
 │ [4] VOICE — TTS (one MP3 per line, gender-matched)       │    │
 │ burst-aligned line boundaries → per-scene timing plan    │    │
 └────────────────────────────┬─────────────────────────────┘    │
                              ▼                                  │
 ┌──────────────────────────────────────────────────────────┐    │
 │ [5] ASSEMBLY — ffmpeg (plan-driven Ken Burns renderer)   │    │
 │ scenes → dialogue spans → concat → CC-BY music mix       │    │
 │ → 1080×1920 H.264/AAC faststart MP4                      │    │
 └────────────────────────────┬─────────────────────────────┘    │
                              ▼                                  │
              episode.mp4 + run_report.json                       │
              (duration · QA scores · API cost · wall time)        │
                    └─────────────────────────────────────────────┘
```

Where Meta's API is irreplaceable: Spark is the director *and* the QA judge;
Muse Image is the art department. The consistency loop only exists because both
live behind one API. TTS and ffmpeg are used where Meta offers nothing.

## Metrics (from `run_report.json` logs — updated after final runs)

| Metric | Value |
|---|---|
| Consistency (scenes passing QA ≥ 0.80) | _TBD — from Gate-3 logs_ |
| API cost / finished episode | _TBD — target $0.50–1.00_ |
| Wall time / finished episode | _TBD_ |
| Output | 1080×1920, H.264 + AAC, faststart, 60–90 s |

## Quickstart

```bash
# 1. Python 3.12 + system ffmpeg
python3 --version   # 3.12.x
ffmpeg -version

# 2. Install deps
pip install -r requirements.txt

# 3. Put your Meta Model API key in the environment (never commit it)
export MODEL_API_KEY="sk-..."

# 4a. Launch the one-page UI
python toonforge/ui/app.py
# → paste a 100–400 word story, pick Bangla/English, hit Generate.

# 4b. Or run the CLI pipeline
python -m toonforge.pipeline --story stories/story1.md --lang bn --out runs/ep1/
```

Each run writes `runs/<name>/run_report.json` (schema: `run_report.schema.json`).

## Repo layout

```
toonforge/
  director/    # stage 1 — story → script.json + character_bible.json
  art/         # stage 2 — reference sheets + scene images (Muse Image)
  qa/          # stage 3 — vision scoring + regenerate loop
  voice/       # stage 4 — line-by-line TTS + timing plan
  assemble/    # stage 5 — ffmpeg plan-driven renderer → episode.mp4
  ui/          # one-page Gradio app (app.py)
  prompts/     # the four Spark prompts + JSON schemas (reviewed pre-window)
  stories/     # 3 test-story fixtures (100–400 words, bn/en)
  tests/       # schema + contract smoke tests
```

## Credits

- Music: Kevin MacLeod (incompetech.com), licensed CC-BY 4.0.
- Built on the Meta Model API: Muse Spark 1.3 (director + vision QA),
  Muse Image 1.0 (art).

## License

MIT — see [LICENSE](LICENSE).
