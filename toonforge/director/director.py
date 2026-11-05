"""ToonForge stage 1 — DIRECTOR.

Muse Spark 1.3 (Meta Model API, structured output, non-streaming calls).

Contract
--------
direct(story_text, language, *, model_id="muse-spark-1.3-contributor")
    -> (script: dict, bible: dict)

Inputs
------
story_text : str   100-400 words, Bangla or English.
language   : "bn" | "en".

Outputs
-------
script : dict matching toonforge/prompts/script.schema.json
    characters[] ; scenes[] of {scene_id, setting, action, emotion,
    characters_present, lines[{speaker, text}], target_seconds};
    opening mega-hook + twist every ~25-30 s + cliffhanger ending;
    total target 75-95 s, 6-10 scenes.
bible : dict matching toonforge/prompts/bible.schema.json
    per character: appearance tokens (species, colors, outfit, props),
    appearance_prompt_lock (verbatim string reused by ART), personality,
    voice_id (gender-matched house voice).

Errors
------
DirectorError — malformed model output or schema validation failure
after one retry.

Cost
----
Every API call is logged via toonforge.cost. Dev-tier model for
iterations, standard tier for finals.

Prompt source of truth: toonforge/prompts/01-director-story-to-script.md
and toonforge/prompts/02-character-bible.md (reviewed pre-window).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .. import api
from ..cost import cost as cost_mod

MODEL_ID_DEV = "muse-spark-1.3-contributor"
MODEL_ID_FINAL = "muse-spark-1.3"  # standard tier for demo/final runs

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class DirectorError(RuntimeError):
    """Raised when the director's output fails schema validation."""


def _load(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _schema_text(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _validate(obj: dict, schema_name: str) -> None:
    schema = json.loads((PROMPTS_DIR / schema_name).read_text(encoding="utf-8"))
    jsonschema.validate(obj, schema)


# ---- Schema repair: the model paraphrases key names despite the prompt.
# Canonicalize known aliases / infer missing fields from the house voice map
# instead of burning another full-price call on a blind retry. ----
ROLE_ENUM = ["narrator", "hero", "wife", "villain", "comic", "elder", "other"]
VOICE_GENDER = {"narrator_f": "female", "wife_f": "female", "hero_m": "male",
                "villain_m": "male", "comic_m": "male", "elder_m": "male"}
SCRIPT_TOP_KEYS = ["title", "language", "finale", "characters", "scenes",
                   "hook_line", "total_target_seconds"]


def _repair_script(obj: dict, *, language: str | None = None,
                   title: str | None = None,
                   finale: bool | None = None) -> dict:
    if not isinstance(obj, dict):
        raise DirectorError("script output is not a JSON object")
    if "is_finale" in obj and "finale" not in obj:
        obj["finale"] = obj.pop("is_finale")
    lang = obj.get("language")
    if isinstance(lang, str):
        l = lang.strip().lower()
        if l in ("bn", "bangla", "bengali", "বাংলা"):
            obj["language"] = "bn"
        elif l in ("en", "english"):
            obj["language"] = "en"
    # Caller-known fields are authoritative fallbacks — the model sometimes
    # drops them in "corrected" retries; never fail on what we already know.
    if obj.get("language") not in ("bn", "en") and language in ("bn", "en"):
        obj["language"] = language
    if not obj.get("title") and title:
        obj["title"] = title
    if not isinstance(obj.get("finale"), bool) and isinstance(finale, bool):
        obj["finale"] = finale
    chars = []
    for c in obj.get("characters") or []:
        vs = c.get("voice_slot")
        tag = c.get("speaker_tag") or c.get("name")
        g = c.get("gender")
        if g not in ("female", "male"):
            g = VOICE_GENDER.get(vs, "male")
        chars.append({
            "speaker_tag": tag,
            "name": c.get("name") or tag,
            "role": c.get("role") if c.get("role") in ROLE_ENUM else "other",
            "gender": g,
            "voice_slot": vs,
        })
    obj["characters"] = chars
    scenes = []
    for s in obj.get("scenes") or []:
        lines = [{"speaker": ln.get("speaker"), "text": ln.get("text")}
                 for ln in s.get("lines") or []]
        scenes.append({
            "scene_id": s.get("scene_id", s.get("scene_number")),
            "setting": s.get("setting"),
            "action": s.get("action"),
            "emotion": s.get("emotion"),
            "characters_present": s.get("characters_present") or [],
            "lines": lines,
            "target_seconds": s.get("target_seconds"),
        })
    obj["scenes"] = scenes
    return {k: obj.get(k) for k in SCRIPT_TOP_KEYS}


BIBLE_CHAR_KEYS = ["speaker_tag", "name", "role", "gender", "voice_slot",
                   "on_screen", "appearance", "appearance_prompt_lock",
                   "personality", "reference_sheet_prompt", "qa_watchpoints"]
APPEARANCE_KEYS = ["species_form", "body_colors", "outfit", "props",
                   "face", "size_impression"]


def _repair_bible(obj: dict) -> dict:
    if not isinstance(obj, dict):
        raise DirectorError("bible output is not a JSON object")
    chars = []
    for c in obj.get("characters") or []:
        vs = c.get("voice_slot")
        role = c.get("role") if c.get("role") in ROLE_ENUM else "other"
        g = c.get("gender")
        if g not in ("female", "male"):
            g = VOICE_GENDER.get(vs, "male")
        ap = c.get("appearance") or {}
        body_colors = ap.get("body_colors") or []
        props = ap.get("props") or []
        watch = c.get("qa_watchpoints") or []
        chars.append({
            "speaker_tag": c.get("speaker_tag") or c.get("name"),
            "name": c.get("name"),
            "role": role,
            "gender": g,
            "voice_slot": vs,
            "on_screen": bool(c.get("on_screen", role != "narrator")),
            "appearance": {
                "species_form": ap.get("species_form"),
                "body_colors": list(body_colors)[:4],
                "outfit": ap.get("outfit"),
                "props": list(props)[:2],
                "face": ap.get("face"),
                "size_impression": ap.get("size_impression"),
            },
            "appearance_prompt_lock": c.get("appearance_prompt_lock"),
            "personality": c.get("personality"),
            "reference_sheet_prompt": c.get("reference_sheet_prompt"),
            "qa_watchpoints": list(watch)[:2],
        })
    return {
        "characters": chars,
        "world_style_lock": obj.get("world_style_lock") or
        "glossy Pixar-like 3D animation, Bangladeshi village, warm cinematic "
        "light, vertical 9:16 portrait composition, no text, no watermark",
    }


def _call_json(system: str, user: str, *, model_id: str,
               cost_log: str | None, stage: str) -> tuple[dict, dict]:
    """One Spark call -> (parsed_json, usage). Retries once on bad JSON."""
    last_err: Exception | None = None
    for attempt in range(2):
        content, usage = api.chat(user, system=system, model=model_id)
        if cost_log:
            cost_mod.log_call(stage, model_id, usage, log_path=cost_log,
                              note=f"attempt={attempt}")
        try:
            return api.extract_json(content), usage
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise DirectorError(f"model did not return parseable JSON after 1 retry: {last_err}")


def _validated_call(system: str, user: str, repair_fn, schema_name: str, *,
                    model_id: str, cost_log: str | None,
                    stage: str, what: str, repair_kwargs: dict | None = None) -> dict:
    """Call -> parse -> repair -> validate. One targeted retry with the
    schema errors fed back on failure."""
    rk = repair_kwargs or {}
    obj, _u = _call_json(system, user, model_id=model_id,
                         cost_log=cost_log, stage=stage)
    obj = repair_fn(obj, **rk)
    try:
        _validate(obj, schema_name)
        return obj
    except jsonschema.ValidationError as e1:
        fix_user = (f"Your previous output failed schema validation with these "
                    f"errors:\n- {e1.message}\n\nReturn the FULL corrected JSON "
                    f"object and nothing else. Keep every story beat, line and "
                    f"character identical — fix only the schema violations.")
        obj2, _u2 = _call_json(system, fix_user, model_id=model_id,
                               cost_log=cost_log, stage=stage + "/fix")
        obj2 = repair_fn(obj2, **rk)
        try:
            _validate(obj2, schema_name)
            return obj2
        except jsonschema.ValidationError as e2:
            raise DirectorError(
                f"{what} failed schema validation after repair + retry: "
                f"{e2.message}") from e2


def direct(story_text: str, language: str, *, model_id: str = MODEL_ID_DEV,
           title: str = "", finale: bool = False,
           cost_log: str | None = None) -> tuple[dict, dict]:
    """Story text -> (script, bible). See module docstring for the contract."""
    if language not in ("bn", "en"):
        raise DirectorError(f"language must be 'bn' or 'en', got {language!r}")
    words = len(story_text.split())
    if not 100 <= words <= 400:
        raise DirectorError(f"story must be 100-400 words, got {words}")

    # --- Call 1: story -> script (Prompt 1) ---
    system1 = _load("01-director-story-to-script.md")
    user1 = (f"TITLE: {title}\nFINALE: {str(finale).lower()}\nSTORY:\n{story_text}"
             f"\n\nOUTPUT CONTRACT — your JSON must validate against this schema "
             f"exactly (key names, enums, required fields):\n"
             f"{_schema_text('script.schema.json')}")
    script = _validated_call(system1, user1, _repair_script, "script.schema.json",
                             model_id=model_id, cost_log=cost_log,
                             stage="director/script", what="script.json",
                             repair_kwargs={"language": language,
                                            "title": title, "finale": finale})

    # Cross-checks the schema cannot express.
    if script["language"] != language:
        raise DirectorError(
            f"script language {script['language']!r} != input {language!r}")
    tags = {c["speaker_tag"] for c in script["characters"]}
    for sc in script["scenes"]:
        for ln in sc["lines"]:
            if ln["speaker"] not in tags:
                raise DirectorError(
                    f"scene {sc['scene_id']}: unknown speaker {ln['speaker']!r}")

    # --- Call 2: script -> character bible (Prompt 2) ---
    system2 = _load("02-character-bible.md")
    user2 = ("SCRIPT_JSON:\n" + json.dumps(script, ensure_ascii=False)
             + "\n\nOUTPUT CONTRACT — your JSON must validate against this schema "
             "exactly (key names, enums, required fields):\n"
             + _schema_text("bible.schema.json"))
    bible = _validated_call(system2, user2, _repair_bible, "bible.schema.json",
                            model_id=model_id, cost_log=cost_log,
                            stage="director/bible", what="bible.json")

    bible_tags = {c["speaker_tag"] for c in bible["characters"]}
    if bible_tags != tags:
        raise DirectorError(
            f"bible speaker_tags {sorted(bible_tags)} != script {sorted(tags)}")

    return script, bible
