"""ToonForge pipeline orchestrator — story text in, assets + run_report out.

    run_pipeline(story_text, language, work_dir, ...) -> run_report dict

Stages wired in Phase 2: director -> art -> qa loop.
Downstream hooks (Phase 3): voice -> assemble. They are marked HOOK below
and skipped by default; the run_report notes field records what is pending.

Layout of work_dir:
    assets/script.json, assets/bible.json
    assets/refs/ref_NN.png            (one per on-screen character)
    assets/scenes/scene_NN.png        (final QA-passed still per scene)
    assets/scenes/scene_NN_aK.png     (all attempts incl. QA rejects)
    assets/manifest.json              (refs, prompt bundles, QA scores)
    cost_log.jsonl
    run_report.json                   (validates run_report.schema.json)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import time
from functools import partial
from pathlib import Path

from .art.art import choose_motion, en_gloss, generate_scene, make_reference_sheets
from .cost import cost as cost_mod
from .director.director import direct
from .qa.qa import qa_loop, score_scene

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "run_report.schema.json"


def _canonical_copy(src: str, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if Path(src).resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return str(dst)


def run_pipeline(story_text: str, language: str, work_dir: str | Path,
                 *, title: str = "", finale: bool = False,
                 model_id: str = "muse-spark-1.3-contributor",
                 run_voice: bool = True, run_assemble: bool = True) -> dict:
    """Full story->episode run: director->art->qa->voice->assemble."""
    t0 = time.monotonic()
    work = Path(work_dir)
    assets = work / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    cost_log = str(work / "cost_log.jsonl")
    model_ids: list[str] = []

    # ---- Stage 1: DIRECTOR ----
    script, bible = direct(story_text, language, model_id=model_id,
                           title=title, finale=finale, cost_log=cost_log)
    model_ids.append(model_id)
    (assets / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (assets / "bible.json").write_text(
        json.dumps(bible, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- Stage 2+3: ART + QA LOOP ----
    refs_dir = assets / "refs"
    refs = make_reference_sheets(bible, out_dir=str(refs_dir), cost_log=cost_log)
    model_ids.append("muse-image-1.0")

    scenes_dir = assets / "scenes"
    scenes_report: list[dict] = []
    manifest_scenes: list[dict] = []
    prev_move: str | None = None
    n = len(script["scenes"])
    for i, scene in enumerate(script["scenes"]):
        motion_scene = dict(scene)
        motion_scene["emotion"] = en_gloss(scene.get("emotion", ""),
                                           cost_log=cost_log)
        motion = choose_motion(motion_scene, i, n, prev_move)
        prev_move = motion["ken_burns"]
        generate_fn = partial(generate_scene, references=refs,
                              out_dir=str(scenes_dir), cost_log=cost_log,
                              motion=motion)
        score_fn = partial(score_scene, cost_log=cost_log, model_id=model_id)
        qa = qa_loop(scene, bible, generate_fn, score_fn=score_fn)
        final = _canonical_copy(qa["final_image"],
                                scenes_dir / f"scene_{scene['scene_id']:02d}.png")
        scenes_report.append({
            "index": i,
            "qa_score": qa["scores"][-1]["scores"]["total"],
            "retries": qa["retries"],
        })
        manifest_scenes.append({
            "scene_id": scene["scene_id"],
            "final_image": final,
            "motion": motion,
            "qa": qa["scores"],
            "passed": qa["passed"],
        })

    manifest = {"refs": refs, "scenes": manifest_scenes}
    (assets / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- Stage 4: VOICE (Phase 3 — wired) ----
    episode_path: str | None = None
    episode_dur = 0.0
    voice_note = ""
    if run_voice:
        from .voice.voice import build_dialogue_track
        dialogue = build_dialogue_track(script, bible,
                                        out_dir=str(assets / "audio"))
        (assets / "dialogue.json").write_text(
            json.dumps(dialogue, ensure_ascii=False, indent=2),
            encoding="utf-8")
        voice_note = (f"voice: {sum(len(s['lines']) for s in dialogue['scenes'])} "
                      f"lines, {dialogue['total_duration']:.1f}s measured")

        # ---- Stage 5: ASSEMBLE (Phase 3 — wired) ----
        if run_assemble:
            from .assemble.assemble import assemble
            motion_by_id = {m["scene_id"]: m["motion"]
                            for m in manifest_scenes}
            dlg_by_id = {d["scene_id"]: d for d in dialogue["scenes"]}
            asm_scenes = []
            for m in manifest_scenes:
                sid = m["scene_id"]
                asm_scenes.append({
                    "scene_id": sid,
                    "image": m["final_image"],
                    "duration": dlg_by_id[sid]["duration"],
                    "ken_burns": motion_by_id[sid]["ken_burns"],
                    "dialogue_audio": dlg_by_id[sid]["dialogue_audio"],
                })
            episode_path, episode_dur, episode_size = assemble(
                {"scenes": asm_scenes}, work / "episode.mp4",
                workdir=str(work / "render_tmp"))
            voice_note += (f"; assemble: episode.mp4 {episode_dur:.1f}s, "
                           f"{episode_size / 1e6:.1f} MB")

    # ---- run_report.json ----
    spend = cost_mod.estimate_cost(cost_log)
    status = "ok" if episode_path else "partial"
    report = {
        "story_title": title or script.get("title", "untitled"),
        "language": language,
        "duration_s": round(episode_dur, 2) if episode_path
        else float(script.get("total_target_seconds", 0)),
        "scenes": scenes_report,
        "api_cost_usd": spend["total_usd"],
        "wall_time_s": round(time.monotonic() - t0, 1),
        "model_ids": sorted(set(model_ids)),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status,
        "episode": episode_path,
        "notes": (f"Full pipeline run. {voice_note}" if episode_path
                  else "director+art+qa only (voice/assemble skipped)"),
    }
    (work / "run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="ToonForge pipeline (Phase 2: director+art+qa)")
    ap.add_argument("story", help="story markdown/txt file (100-400 words)")
    ap.add_argument("language", choices=["bn", "en"])
    ap.add_argument("work_dir", help="output directory for assets + run_report.json")
    ap.add_argument("--title", default="")
    ap.add_argument("--finale", action="store_true")
    args = ap.parse_args()
    story_text = Path(args.story).read_text(encoding="utf-8")
    report = run_pipeline(story_text, args.language, args.work_dir,
                          title=args.title, finale=args.finale)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
