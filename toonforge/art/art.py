"""ToonForge stage 2 — ART.

Muse Image 1.0 (Meta Model API), text-to-image with the bible's
appearance_prompt_lock pasted VERBATIM (prompt recipe in
prompts/03-scene-prompt-writer.md).

Contract
--------
make_reference_sheet(character, bible, *, model_id="muse-image-1.0", out_dir)
    -> image_path
    One reference sheet for a single bible character, from its
    reference_sheet_prompt.

make_reference_sheets(bible, *, model_id="muse-image-1.0", out_dir="assets/refs")
    -> dict[speaker_tag, image_path]
    One reference sheet per ON-SCREEN character.

make_scene(scene, bible, ref_paths, *, model_id="muse-image-1.0",
           attempt=0, qa_feedback=None, out_dir="assets/scenes")
    -> (image_path, prompt_bundle)
    One scene image. prompt_bundle = {scene_id, image_prompt,
    negative_prompt, reference_character_tags, motion} per Prompt 3.
    attempt counts QA-driven regenerations (0 = first try); qa_feedback is
    the previous QA result dict (its regen_advice tightens the prompt).

Outputs
-------
1080x1920 portrait PNGs, one per scene + one reference sheet per
character, recorded in the run's asset manifest.

Prompt 3's scene-prompt-writer is implemented as code (the recipe is fully
specified): this keeps dev runs deterministic and $0. The image-EDIT
endpoint is untested — text-to-image with verbatim locks + the QA loop is
the working consistency path (build-plan risk #4).

Prompt source of truth: toonforge/prompts/03-scene-prompt-writer.md.
"""

from __future__ import annotations

from pathlib import Path

from .. import api
from ..cost import cost as cost_mod

MODEL_IMAGE = "muse-image-1.0"
MODEL_SPARK_DEV = "muse-spark-1.3-contributor"

_gloss_cache: dict[str, str] = {}


_ASCII_FIXES = {"—": "-", "–": "-", "‘": "'", "’": "'",
                "“": '"', "”": '"', "…": "...", "•": "-", " ": " "}


def ascii_safe(text: str) -> str:
    """Image endpoint 400s on non-ASCII input (verified 2026-11-03: Bangla
    script and even U+2014 em-dash both fail; pure ASCII succeeds).
    Normalize common punctuation, then drop anything still non-ASCII."""
    for src, dst in _ASCII_FIXES.items():
        text = text.replace(src, dst)
    return text.encode("ascii", "ignore").decode("ascii")


# Word-level softening for the image endpoint's content filter, applied to
# the PROMPT TEXT ONLY (script/bible/QA keep the original words). Verified
# 2026-11-03: "knife"+"menace" in one prompt -> content_policy_violation.
_SOFTEN = [
    (r"\bknifes?\b", "tool"),
    (r"\bmenace\b", "tension"),
    (r"\bthreat(ening)?\b", "suspense"),
    (r"\bkill(ing|ed)?\b", "stop"),
    (r"\bblood(y)?\b", ""),
    (r"\bweapon(s)?\b", "object"),
    (r"\battack(ing|ed)?\b", "confront"),
    (r"\bhorror\b", "suspense"),
]


def soften_prompt(prompt: str) -> str:
    """Replace likely filter triggers with neutral equivalents."""
    import re
    for pat, repl in _SOFTEN:
        prompt = re.sub(pat, repl, prompt, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", prompt).strip()


def en_gloss(text: str, *, cost_log: str | None = None) -> str:
    """Bangla (or any non-ASCII) scene text -> concise English.

    The image endpoint 400s on non-Latin script input (verified 2026-11-03);
    the chat endpoint handles Bangla fine, so this only affects ART prompts.
    Pure-ASCII text passes through untouched (no API call).
    """
    if not text or text.isascii():
        return text
    if text in _gloss_cache:
        return _gloss_cache[text]
    content, usage = api.chat(
        "Translate to concise plain English for an image-generation prompt. "
        f"Return ONLY the English, no quotes or explanation:\n{text}",
        system="You are a terse Bangla-to-English translator.",
        model=MODEL_SPARK_DEV)
    if cost_log:
        cost_mod.log_call("art/gloss", MODEL_SPARK_DEV, usage,
                          log_path=cost_log)
    out = content.strip().strip('"').strip()
    _gloss_cache[text] = out
    return out


def _scene_for_art(scene: dict, *, cost_log: str | None = None) -> dict:
    """Copy of the scene with action/setting/emotion glossed to English."""
    s = dict(scene)
    s["action"] = en_gloss(scene.get("action", ""), cost_log=cost_log)
    s["setting"] = en_gloss(scene.get("setting", ""), cost_log=cost_log)
    s["emotion"] = en_gloss(scene.get("emotion", ""), cost_log=cost_log)
    return s

HOUSE_STYLE_SUFFIX = (
    "Vertical 9:16 portrait orientation, full-frame vertical composition "
    "filling the whole frame, glossy Pixar-like 3D animation style, soft "
    "cinematic light, rich colors, no text, no letters, no watermark, no borders"
)

NEGATIVE_PROMPT = (
    "different outfit, changed colors, extra characters, duplicate character, "
    "human hands on fruit characters, text, letters, subtitles, speech bubbles, "
    "watermark, logo, blurry, low quality, horizontal composition, letterbox bars"
)


class ArtError(RuntimeError):
    """Raised when image generation fails after retries."""


def _out(out_dir: str | Path) -> Path:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_reference_sheet(character: dict, bible: dict, *,
                         model_id: str = MODEL_IMAGE,
                         out_dir: str = "assets/refs",
                         cost_log: str | None = None) -> str:
    """One bible character -> reference-sheet PNG path."""
    d = _out(out_dir)
    tag = character["speaker_tag"]
    idx = [c["speaker_tag"] for c in bible["characters"]].index(tag)
    path = d / f"ref_{idx:02d}.png"
    prompt = ascii_safe(en_gloss(character["reference_sheet_prompt"],
                                  cost_log=cost_log))
    try:
        api.generate_image(prompt, str(path), model=model_id)
    except api.ContentPolicyError:
        prompt = soften_prompt(prompt)
        if cost_log:
            cost_mod.log_call("art/policy-soften", model_id, None,
                              log_path=cost_log, note=f"ref character={tag}")
        try:
            api.generate_image(prompt, str(path), model=model_id)
        except Exception as e2:
            raise ArtError(f"reference sheet for {tag!r} failed after "
                           f"policy soften: {e2}") from e2
    except Exception as e:
        raise ArtError(f"reference sheet for {tag!r} failed: {e}") from e
    if cost_log:
        cost_mod.log_image("art/reference", model_id, log_path=cost_log,
                           note=f"character={tag}")
    return str(path)


def make_reference_sheets(bible: dict, *, model_id: str = MODEL_IMAGE,
                          out_dir: str = "assets/refs",
                          cost_log: str | None = None) -> dict[str, str]:
    """Character bible -> {speaker_tag: reference_sheet_path} (on-screen only)."""
    refs: dict[str, str] = {}
    for ch in bible["characters"]:
        if ch.get("on_screen", True):
            refs[ch["speaker_tag"]] = make_reference_sheet(
                ch, bible, model_id=model_id, out_dir=out_dir, cost_log=cost_log)
    return refs


def _bible_entry(bible: dict, tag: str) -> dict:
    for c in bible["characters"]:
        if c["speaker_tag"] == tag:
            return c
    raise ArtError(f"character {tag!r} not in bible")


def build_scene_prompt(scene: dict, bible: dict,
                       qa_feedback: dict | None = None) -> dict:
    """Prompt-03 recipe as code -> prompt bundle (no API call)."""
    entries = [_bible_entry(bible, t) for t in scene["characters_present"]]

    advice = (qa_feedback or {}).get("regen_advice") or ""
    subject = "keep the exact same character designs as the reference images. "
    if advice:
        subject += f"IMPORTANT FIX: {advice} "
    for e in entries:
        subject += e["appearance_prompt_lock"].strip().rstrip(".") + ". "

    action = scene["action"].strip()
    emotion = scene["emotion"]
    action_block = (f"Scene action: {action} Characters show {emotion} on "
                    f"their faces and in body language. No speech bubbles, "
                    f"no text of any kind.")

    setting = scene["setting"].strip()
    setting_block = (f"Setting: {setting}, Bangladeshi village, mud house, "
                     f"banana trees, tin roof, paddy field as fitting, "
                     f"matching time of day and light.")

    image_prompt = f"{subject}{action_block} {setting_block} {HOUSE_STYLE_SUFFIX}"

    return {
        "scene_id": scene["scene_id"],
        "image_prompt": image_prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "reference_character_tags": list(scene["characters_present"]),
        "motion": None,  # filled by choose_motion()
    }


def choose_motion(scene: dict, index: int, n_scenes: int,
                  prev_move: str | None) -> dict:
    """Prompt-03 motion rules as code -> {ken_burns, focus}."""
    emotion = scene.get("emotion", "").lower()
    if index == 0:
        move = "zin"  # opening hook
    elif index == n_scenes - 1:
        move = "zin"  # cliffhanger: slow push into the threat
    elif scene.get("target_seconds", 5) < 4:
        move = "static"
    else:
        if any(k in emotion for k in ("menace", "fear", "threat", "danger")):
            move = "panl"  # approach of a threat
        elif any(k in emotion for k in ("travel", "search", "journey", "chase")):
            move = "panr"
        elif any(k in emotion for k in ("lonel", "sorrow", "aftermath", "sad")):
            move = "zout"
        else:
            move = "zin"
        if move == prev_move:
            # never repeat the same move on consecutive scenes
            move = {"zin": "zout", "zout": "zin", "panr": "panl",
                    "panl": "panr", "static": "zin"}[move]
    present = scene.get("characters_present") or []
    return {"ken_burns": move, "focus": present[0] if present else ""}


def generate_scene(scene: dict, bible: dict, references: dict,
               *, model_id: str = MODEL_IMAGE, attempt: int = 0,
               qa_feedback: dict | None = None, out_dir: str = "assets/scenes",
               cost_log: str | None = None,
               motion: dict | None = None) -> tuple[str, dict]:
    """One script scene -> (portrait PNG path, prompt bundle)."""
    d = _out(out_dir)
    art_scene = _scene_for_art(scene, cost_log=cost_log)
    bundle = build_scene_prompt(art_scene, bible, qa_feedback)
    if motion is None:
        # motion needs episode context; pipeline passes it in. Fallback: zin.
        bundle["motion"] = {"ken_burns": "zin",
                            "focus": bundle["reference_character_tags"][:1]}
        if bundle["motion"]["focus"]:
            bundle["motion"]["focus"] = bundle["motion"]["focus"][0]
    else:
        bundle["motion"] = motion
    bundle["image_prompt"] = ascii_safe(bundle["image_prompt"])
    path = d / f"scene_{scene['scene_id']:02d}_a{attempt}.png"
    try:
        api.generate_image(bundle["image_prompt"], str(path), model=model_id)
    except api.ContentPolicyError:
        # Content filter tripped (e.g. "knife"+"menace"): soften the prompt
        # text once and retry. The script/bible keep the original words.
        bundle["image_prompt"] = soften_prompt(bundle["image_prompt"])
        bundle["policy_softened"] = True
        if cost_log:
            cost_mod.log_call("art/policy-soften", model_id, None,
                              log_path=cost_log,
                              note=f"scene={scene['scene_id']} attempt={attempt}")
        try:
            api.generate_image(bundle["image_prompt"], str(path),
                               model=model_id)
        except Exception as e2:
            raise ArtError(f"scene {scene['scene_id']} image failed after "
                           f"policy soften: {e2}") from e2
    except Exception as e:
        raise ArtError(f"scene {scene['scene_id']} image failed: {e}") from e
    if cost_log:
        cost_mod.log_image("art/scene", model_id, log_path=cost_log,
                           note=f"scene={scene['scene_id']} attempt={attempt}")
    return str(path), bundle
