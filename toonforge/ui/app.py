"""ToonForge one-page UI — paste a story, Generate, preview, download.

Phase 1: backend stages are STUBS (director_stub, art_stub, qa_stub,
voice_stub, assemble_stub). The UI runs with NO API key; Generate walks the
stub pipeline and ends with a friendly "pipeline modules land in Phase 2"
message. Phase 2 replaces each stub with the real stage module behind the
same function signature (see the TODO markers).
"""

from __future__ import annotations

import time

try:
    import gradio as gr
except ImportError:  # pragma: no cover
    raise SystemExit(
        "gradio is not installed. From the repo root run:\n"
        "    pip install -r requirements.txt"
    )

MIN_WORDS, MAX_WORDS = 100, 400

PHASE2_MSG = (
    "⚠️ Pipeline modules land in Phase 2 — set MODEL_API_KEY and implement "
    "toonforge/{director, art, qa, voice, assemble} to generate real episodes."
)


# --------------------------------------------------------------------------
# Stub backends (Phase 1). Each mirrors the real stage contract; Phase 2
# swaps the body for the Meta API / TTS / ffmpeg implementation.
# --------------------------------------------------------------------------

def director_stub(story: str, language: str) -> dict:
    """TODO(Phase 2): replace with toonforge.director.direct(story, language).

    Real contract: story -> (script.json, character_bible.json)."""
    time.sleep(0.4)
    return {"scenes": 8, "characters": 3, "stub": True}


def art_stub(script: dict) -> dict:
    """TODO(Phase 2): replace with toonforge.art reference sheets + scenes."""
    time.sleep(0.4)
    return {"images": script["scenes"], "stub": True}


def qa_stub(images: dict) -> dict:
    """TODO(Phase 2): replace with toonforge.qa.qa_loop (vision scoring)."""
    time.sleep(0.4)
    return {"passed": images["images"], "scores": [0.9] * images["images"], "stub": True}


def voice_stub(script: dict, language: str) -> dict:
    """TODO(Phase 2): replace with toonforge.voice.build_dialogue_track."""
    time.sleep(0.4)
    return {"lines": 20, "stub": True}


def assemble_stub(qa_report: dict, audio: dict) -> dict:
    """TODO(Phase 2): replace with toonforge.assemble.assemble -> episode.mp4."""
    time.sleep(0.4)
    return {"video_path": None, "stub": True}


# --------------------------------------------------------------------------
# UI helpers
# --------------------------------------------------------------------------

def count_words(text: str) -> str:
    """Live word counter for the story box (whitespace split; Bangla-safe)."""
    n = len((text or "").split())
    ok = MIN_WORDS <= n <= MAX_WORDS
    mark = "✅" if ok else "⚠️"
    return f"{mark} {n} words (need {MIN_WORDS}–{MAX_WORDS})"


def run_pipeline(story: str, language: str, title: str):
    """Stub pipeline run, streaming status-log updates to the UI.

    Yields (log_text, video_value) tuples for Gradio streaming.
    """
    log_lines: list[str] = []

    def say(msg: str):
        log_lines.append(msg)
        yield "\n".join(log_lines), None

    n = len((story or "").split())
    if n < MIN_WORDS or n > MAX_WORDS:
        yield (
            f"⚠️ Story is {n} words — ToonForge needs {MIN_WORDS}–{MAX_WORDS} "
            f"words. Please adjust and try again.",
            None,
        )
        return

    lang_name = "Bangla" if language == "bn" else "English"
    yield from say(f"📖 Story received ({n} words, {lang_name})"
                  + (f" — '{title}'" if title.strip() else ""))
    yield from say("[1/5] DIRECTOR (stub): breaking story into scenes…")
    script = director_stub(story, language)
    yield from say(f"        → {script['scenes']} scenes, "
                   f"{script['characters']} characters drafted (stub).")
    yield from say("[2/5] ART (stub): painting reference sheets + scenes…")
    images = art_stub(script)
    yield from say(f"        → {images['images']} scene images (stub).")
    yield from say("[3/5] QA LOOP (stub): vision-scoring every scene…")
    qa_report = qa_stub(images)
    yield from say(f"        → {qa_report['passed']}/{qa_report['passed']} "
                   f"scenes pass ≥ 0.80 (stub scores).")
    yield from say("[4/5] VOICE (stub): voicing dialogue lines…")
    audio = voice_stub(script, language)
    yield from say(f"        → {audio['lines']} lines voiced (stub).")
    yield from say("[5/5] ASSEMBLY (stub): rendering 1080×1920 episode…")
    result = assemble_stub(qa_report, audio)
    yield from say("        → episode.mp4 (stub — no file produced).")
    yield from say("")
    yield from say(PHASE2_MSG)
    # video stays None in stub mode; the Download button stays hidden.


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

def build_app() -> "gr.Blocks":
    with gr.Blocks(title="ToonForge — story in, cartoon out") as app:
        gr.Markdown(
            "# 🎬 ToonForge\n"
            "**Paste a story → get a finished cartoon episode.**\n\n"
            "_Phase 1 UI shell — pipeline stages are stubs; "
            "real generation lands in Phase 2._"
        )
        with gr.Row():
            with gr.Column(scale=3):
                title = gr.Textbox(
                    label="Episode title (optional)",
                    placeholder="e.g. The Mango Who Shared",
                )
                story = gr.Textbox(
                    label="Your story",
                    placeholder="Paste 100–400 words — Bangla or English…",
                    lines=12,
                )
                word_label = gr.Markdown(f"⚠️ 0 words (need {MIN_WORDS}–{MAX_WORDS})")
                story.change(fn=count_words, inputs=story, outputs=word_label)
                language = gr.Radio(
                    ["bn", "en"],
                    value="bn",
                    label="Language",
                    info="bn = Bangla · en = English",
                )
                generate_btn = gr.Button("✨ Generate episode", variant="primary")
            with gr.Column(scale=2):
                video = gr.Video(
                    label="Episode preview",
                    interactive=False,
                )
                download_btn = gr.DownloadButton(
                    label="⬇️ Download episode.mp4",
                    visible=False,  # shown once a real video exists (Phase 2)
                )
                log = gr.Textbox(
                    label="Status log",
                    lines=12,
                    interactive=False,
                    value="Ready. Paste a story and hit Generate.",
                )
        generate_btn.click(
            fn=run_pipeline,
            inputs=[story, language, title],
            outputs=[log, video],
        )
    return app


if __name__ == "__main__":
    build_app().launch()
