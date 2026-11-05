#!/usr/bin/env python3
"""ToonForge stage 5 — MOTION + ASSEMBLY (Phase 3: implemented).

Adapts the TEST-PASSED plan-driven renderer
(../renderer/render.py — 89.73s, 1080x1920, faststart verified) instead of
rewriting it. This module translates pipeline assets into a motion-plan
JSON and delegates the ffmpeg work to render.render().

    assemble(plan, out_path) -> (path, duration_s, size_bytes)

plan = {
  "scenes": [{"scene_id", "image", "duration", "ken_burns", "dialogue_audio"}],
  "music":  [{"file", "start", "duration", "volume"}],   # optional
  "width": 1080, "height": 1920, "fps": 30,             # optional
}
durations are the MEASURED dialogue spans from the voice stage — the
assembler builds each scene to its exact span, never an estimate.
No subtitles (house style). Output is H.264+AAC with +faststart.

Music: production recipe from the Diamond series — monkeys.mp3 0-45s @ 0.10,
sneaky.mp3 45s+ @ 0.14 (Kevin MacLeod, incompetech.com, CC-BY — credited in
README + video).

Proven numbers (renderer/ep1-test-render.mp4): 89.73 s output, 17.2 MB,
audio mean -23.7 dB / max -2.3 dB (no clipping), ~8.5 min wall on 2 cores.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent
                       / "renderer"))
from render import render  # noqa: E402  (TEST-PASSED plan-driven renderer)


class AssembleError(RuntimeError):
    """Raised when ffmpeg fails or the motion plan is invalid."""


MUSIC_DIR = Path("/home/hatch/workspace/youtube/music")
MUSIC_RECIPE = [
    {"file": str(MUSIC_DIR / "monkeys.mp3"), "start": 0.0,
     "duration": 45.0, "volume": 0.10},
    {"file": str(MUSIC_DIR / "sneaky.mp3"), "start": 45.0,
     "duration": None, "volume": 0.14},
]


def default_music(total_s: float) -> list[dict]:
    """Production music recipe clipped to the episode length."""
    segs: list[dict] = []
    for seg in MUSIC_RECIPE:
        if seg["start"] >= total_s:
            break
        s = dict(seg)
        if s["duration"] is None or s["start"] + s["duration"] > total_s:
            s["duration"] = round(total_s - s["start"], 3)
        if s["duration"] > 0:
            segs.append(s)
    return segs


def build_motion_plan(plan: dict, out_path: str | Path,
                      plan_path: str | Path) -> dict:
    """Translate pipeline assets -> render.py motion-plan JSON."""
    scenes = []
    for sc in plan["scenes"]:
        for key in ("scene_id", "image", "duration", "ken_burns",
                    "dialogue_audio"):
            if key not in sc:
                raise AssembleError(f"scene missing {key!r}")
        scenes.append({
            "scene_id": sc["scene_id"],
            "image": sc["image"],
            "duration": float(sc["duration"]),
            "ken_burns": sc["ken_burns"],
            "dialogue_audio": sc["dialogue_audio"],
        })
    if not scenes:
        raise AssembleError("plan has no scenes")
    total = sum(s["duration"] for s in scenes)
    motion_plan = {
        "scenes": scenes,
        "music": {"segments": plan.get("music") or default_music(total)},
        "episode": {
            "width": int(plan.get("width", 1080)),
            "height": int(plan.get("height", 1920)),
            "fps": int(plan.get("fps", 30)),
            "dialogue_volume": 1.0,
        },
        "output": str(out_path),
    }
    plan_path = Path(plan_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(motion_plan, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return motion_plan


def assemble(plan: dict, out_path: str | Path,
             workdir: str | Path | None = None) -> tuple[str, float, int]:
    """Render the episode MP4. Returns (path, duration_s, size_bytes)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path = out_path.with_suffix("").as_posix() + ".motionplan.json"
    build_motion_plan(plan, out_path, plan_path)
    return render(plan_path,
                  workdir=str(workdir) if workdir else None, keep=False)
