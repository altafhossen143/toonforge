"""ToonForge stage 3 — QA LOOP.

Muse Spark 1.3 vision (Meta Model API). The technical-ambition centerpiece:
every generated scene is scored against the bible + script, and weak scenes
are regenerated with tightened prompts — the loop is what makes character
consistency measurable instead of hoped-for.

Contract
--------
score_scene(image_path, scene, bible, *, model_id) -> dict
    {scene_id, scores{character_match, content_match, emotion_match,
     artifact_freedom, total}, pass: bool, failures: [tags],
     regen_advice: str}
    Rubric (prompts/04-vision-qa-scorer.md):
        character match 0.45 / content 0.25 / emotion 0.15 / artifacts 0.15.
    Pass mark 0.80.

qa_loop(scene, bible, generate_fn, *, pass_mark=0.80, max_retries=2,
        score_fn=score_scene) -> dict
    {final_image: path, scores: [result...], retries: int, passed: bool}
    Score the scene; if score < pass_mark, call generate_fn again with the
    previous result as qa_feedback (tightened prompt), up to max_retries.
    generate_fn contract: fn(scene, bible, references, *, attempt, qa_feedback)
    -> (image_path, prompt_bundle).
    EVERY score — passes and failures — is returned for run_report.json
    scenes[] {index, qa_score, retries}.

Failure taxonomy (14 tags, see prompt 04): wrong_species, wrong_outfit,
wrong_colors, missing_prop, missing_character, extra_character,
wrong_setting, wrong_action, flat_emotion, text_artifact, extra_limbs,
face_distortion, framing_error, style_drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import api
from ..cost import cost as cost_mod

PASS_MARK = 0.80
MAX_RETRIES = 2
MODEL_SPARK_DEV = "muse-spark-1.3-contributor"

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

WEIGHTS = {"character_match": 0.45, "content_match": 0.25,
           "emotion_match": 0.15, "artifact_freedom": 0.15}


class QAError(RuntimeError):
    """Raised when the vision scorer itself fails (not a low score)."""


def _bible_entries(bible: dict, tags: list[str]) -> list[dict]:
    out = []
    for t in tags:
        for c in bible["characters"]:
            if c["speaker_tag"] == t:
                out.append(c)
                break
    return out


def score_scene(image_path: str, scene: dict, bible: dict, *,
                model_id: str = MODEL_SPARK_DEV,
                cost_log: str | None = None,
                pass_mark: float = PASS_MARK) -> dict:
    """One scene image -> QA result dict. See module docstring."""
    system = (PROMPTS_DIR / "04-vision-qa-scorer.md").read_text(encoding="utf-8")
    entries = _bible_entries(bible, scene["characters_present"])
    user = ("SCENE:\n" + json.dumps(scene, ensure_ascii=False)
            + "\n\nBIBLE_ENTRIES:\n" + json.dumps(entries, ensure_ascii=False))
    try:
        content, usage = api.chat_vision(user, [image_path], system=system,
                                         model=model_id)
    except Exception as e:
        raise QAError(f"vision call failed for scene {scene['scene_id']}: {e}") from e
    if cost_log:
        cost_mod.log_call("qa/score", model_id, usage, log_path=cost_log,
                          note=f"scene={scene['scene_id']}")
    try:
        result = api.extract_json(content)
    except ValueError as e:
        raise QAError(f"scorer returned no JSON for scene {scene['scene_id']}: {e}") from e

    scores = result.get("scores", {})
    # Recompute the weighted total defensively; clamp every sub-score.
    total = 0.0
    for k, w in WEIGHTS.items():
        v = scores.get(k, 0.0)
        try:
            v = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            v = 0.0
        scores[k] = round(v, 2)
        total += v * w
    scores["total"] = round(total, 2)
    passed = total >= pass_mark
    return {
        "scene_id": scene["scene_id"],
        "scores": scores,
        "pass": passed,
        "failures": list(result.get("failures", [])),
        "regen_advice": str(result.get("regen_advice", "") or ""),
    }


def qa_loop(scene: dict, bible: dict, generate_fn, *,
            pass_mark: float = PASS_MARK, max_retries: int = MAX_RETRIES,
            score_fn=score_scene) -> dict:
    """Score -> regenerate (max 2) -> QA report dict. See module docstring."""
    from functools import partial as _partial
    score_fn = _partial(score_fn, pass_mark=pass_mark)
    scores: list[dict] = []
    image_path, _bundle = generate_fn(scene, bible, attempt=0, qa_feedback=None)
    result = score_fn(image_path, scene, bible)
    scores.append(result)
    retries = 0
    while not result["pass"] and retries < max_retries:
        retries += 1
        image_path, _bundle = generate_fn(
            scene, bible, attempt=retries, qa_feedback=result)
        result = score_fn(image_path, scene, bible)
        scores.append(result)
    return {
        "final_image": image_path,
        "scores": scores,
        "retries": retries,
        "passed": scores[-1]["pass"],
    }
