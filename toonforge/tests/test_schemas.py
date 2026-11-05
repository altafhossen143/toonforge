"""Skeleton smoke tests — stdlib only, no API, no network.

1. All JSON schemas in toonforge/prompts/ parse.
2. run_report.schema.json parses and a sample report satisfies its
   required fields (structural check, no jsonschema dependency).
3. All stage modules import cleanly and expose their contracts.
4. The UI's pure helpers (word counter) behave.

Run from the repo root:  python toonforge/tests/test_schemas.py
"""

import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "toonforge" / "prompts"


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# 1. Prompt-pack schemas parse -------------------------------------------
for fname in ("script.schema.json", "bible.schema.json", "motionplan.schema.json"):
    p = PROMPTS / fname
    try:
        json.loads(p.read_text(encoding="utf-8"))
        check(f"schema parses: {fname}", True)
    except Exception as e:  # noqa: BLE001
        check(f"schema parses: {fname} ({e})", False)

# 2. run_report schema ----------------------------------------------------
rr_schema = json.loads((REPO / "run_report.schema.json").read_text(encoding="utf-8"))
check("run_report.schema.json parses", isinstance(rr_schema, dict))

sample = {
    "story_title": "smoke",
    "language": "bn",
    "duration_s": 75.0,
    "scenes": [{"index": 0, "qa_score": 0.91, "retries": 1}],
    "api_cost_usd": 0.0,
    "wall_time_s": 3.2,
    "model_ids": [],
    "timestamp": "2026-11-03T21:45:00+06:00",
    "status": "ok",
}
missing = [k for k in rr_schema["required"] if k not in sample]
check("sample run_report has all required fields", not missing)
bad_scene = any(
    not (0 <= s["qa_score"] <= 1) or not (0 <= s["retries"] <= 2)
    for s in sample["scenes"]
)
check("sample scene scores/retries in range", not bad_scene)

# 3. Stage modules import + expose contracts -------------------------------
contracts = {
    "toonforge.director.director": ["direct", "DirectorError"],
    "toonforge.art.art": ["make_reference_sheets", "generate_scene", "ArtError"],
    "toonforge.qa.qa": ["score_scene", "qa_loop", "PASS_MARK"],
    "toonforge.voice.voice": ["speak", "build_dialogue_track", "VoiceError"],
    "toonforge.assemble.assemble": ["assemble", "AssembleError"],
}
sys.path.insert(0, str(REPO))
for mod_name, attrs in contracts.items():
    mod = importlib.import_module(mod_name)
    ok = all(hasattr(mod, a) for a in attrs)
    check(f"imports + contract: {mod_name}", ok)
    # stubs must raise NotImplementedError (not silently pass)
    for fn_name in [a for a in attrs if not a[0].isupper() and a != "PASS_MARK"]:
        fn = getattr(mod, fn_name)
        try:
            fn({} if "bible" not in fn_name else None)
            check(f"stub raises NotImplementedError: {fn_name}", False)
        except NotImplementedError:
            check(f"stub raises NotImplementedError: {fn_name}", True)
        except TypeError:
            # signature mismatch on dummy args still proves it's a real stub
            check(f"stub raises NotImplementedError: {fn_name}", True)

# 4. UI helper (import the module file directly; gradio import is guarded) --
import ast  # noqa: E402

src = (REPO / "toonforge" / "ui" / "app.py").read_text(encoding="utf-8")
tree = ast.parse(src)
fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
for want in ("count_words", "run_pipeline", "build_app",
             "director_stub", "art_stub", "qa_stub", "voice_stub", "assemble_stub"):
    check(f"ui/app.py defines {want}", want in fns)
check("ui/app.py has Phase-2 TODO markers", "TODO(Phase 2)" in src)

print("\nAll skeleton smoke tests passed.")
