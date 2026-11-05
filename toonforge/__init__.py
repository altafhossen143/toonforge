"""ToonForge — paste a story, get a finished cartoon episode.

Five-stage agentic pipeline (see build-plan §2):
    director → art → qa → voice → assemble

Each stage lives in its own subpackage and exposes one narrow contract.
Stage modules are pure functions over JSON-serializable plans so the whole
run is resumable from cache and every API call lands in run_report.json.
"""

__version__ = "0.1.0-phase1"
__all__ = ["director", "art", "qa", "voice", "assemble", "ui"]

# Stage order of the pipeline; ui/ and tests/ are not pipeline stages.
STAGES = ("director", "art", "qa", "voice", "assemble")
