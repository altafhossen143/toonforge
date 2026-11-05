#!/usr/bin/env python3
"""ToonForge stage 5b — FLOW-CLIP re-assembly (episode 1 v2).

Gojo rejected the Ken Burns-only v1: scenes need REAL character animation.
Per scene: if a Google Flow image-to-video clip exists in flow_clips/,
use it; otherwise fall back to the Ken Burns still path (same recipes as
render.py). Audio spans are sacred — the dialogue track is never stretched.

Flow clips are 720x1280 H.264 (~8s). They are upscaled to 1080x1920 with
lanczos (plain ffmpeg; OpenMontage's Real-ESRGAN needs a GPU we don't have),
looped with -stream_loop to cover the measured dialogue span, then trimmed.
Clip audio is dropped (-an): dialogue + music bed carry all sound.

Usage:
    python3 flow_assemble.py <motionplan.json> <flow_clips_dir> <out.mp4>
        [--workdir DIR] [--keep]

Pure ffmpeg + stdlib. No network, no API, no accounts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent
                       / "renderer"))
from render import run, probe_duration, resolve, zoompan_expr  # noqa: E402

RENDER_W, RENDER_H = 2160, 3840  # Ken Burns supersample, matches render.py
OUT_W, OUT_H, FPS = 1080, 1920, 30


def build_flow_segment(clip: str, dur: float, seg: str) -> None:
    """Upscale a Flow clip and loop/trim it to the exact scene duration."""
    run(["ffmpeg", "-v", "error", "-y",
         "-stream_loop", "-1", "-i", clip,
         "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos,fps={FPS}",
         "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-an", seg])


def build_kenburns_segment(img: str, kind: str, dur: float, seg: str) -> None:
    """Same Ken Burns path as render.py (supersampled, then scaled down)."""
    frames = max(1, int(round(dur * FPS)))
    vf = f"{zoompan_expr(kind, frames)},scale={OUT_W}:{OUT_H}"
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", img,
         "-vf", vf, "-t", f"{dur:.3f}", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-r", str(FPS), seg])


def flow_assemble(plan_path: str | Path, flow_dir: str | Path,
                  out_path: str | Path, workdir: str | Path | None = None,
                  keep: bool = False) -> tuple[str, float, int, list[str]]:
    """Render the v2 episode. Returns (path, duration, bytes, flow_scenes)."""
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    base = os.path.dirname(os.path.abspath(plan_path))
    flow_dir = Path(flow_dir)
    scenes = plan["scenes"]
    assert scenes, "plan has no scenes"

    import tempfile
    tmp = str(workdir) if workdir else tempfile.mkdtemp(prefix="toonforge_flow_")
    os.makedirs(tmp, exist_ok=True)

    # ---- video: one segment per scene (Flow clip or Ken Burns still) --------
    seg_paths, starts, flow_used, t = [], [], [], 0.0
    for i, sc in enumerate(scenes):
        dur = float(sc["duration"])
        sid = sc.get("scene_id", i + 1)
        clip = flow_dir / f"scene_{int(sid):02d}.mp4"
        seg = os.path.join(tmp, f"seg{i:02d}.mp4")
        if clip.exists():
            build_flow_segment(str(clip), dur, seg)
            flow_used.append(f"scene_{int(sid):02d}")
            print(f"scene {sid}: FLOW      {dur:6.2f}s -> {os.path.basename(seg)}",
                  flush=True)
        else:
            img = resolve(sc["image"], base)
            assert os.path.exists(img), f"scene {sid}: image missing: {img}"
            build_kenburns_segment(img, sc["ken_burns"], dur, seg)
            print(f"scene {sid}: kenburns  {dur:6.2f}s -> {os.path.basename(seg)}",
                  flush=True)
        seg_paths.append(seg)
        starts.append(t)
        t += dur
    total = t

    listfile = os.path.join(tmp, "concat.txt")
    with open(listfile, "w") as f:
        for s in seg_paths:
            f.write(f"file '{s}'\n")
    video_only = os.path.join(tmp, "video.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", listfile, "-c", "copy", video_only])

    # ---- audio: per-scene dialogue at scene starts + music bed --------------
    # (same mix shape as render.py: dialogue @ 1.0 over the music recipe)
    ep = plan.get("episode", {})
    dlg_vol = float(ep.get("dialogue_volume", 1.0))
    inputs = ["-i", video_only]
    fc, idx = [], 1
    dlg_labels = []
    for i, sc in enumerate(scenes):
        da = sc.get("dialogue_audio")
        if not da:
            continue
        p = resolve(da, base)
        assert os.path.exists(p), f"scene {sc.get('scene_id')}: dialogue missing: {p}"
        inputs += ["-i", p]
        ms = int(round(starts[i] * 1000))
        fc.append(f"[{idx}:a]adelay={ms}|{ms},volume={dlg_vol}[d{i}]")
        dlg_labels.append(f"[d{i}]")
        idx += 1
    mus_labels = []
    for j, segm in enumerate((plan.get("music") or {}).get("segments", [])):
        p = resolve(segm["file"], base)
        assert os.path.exists(p), f"music file missing: {p}"
        inputs += ["-i", p]
        d = segm.get("duration")
        atrim = f"atrim=0:{float(d):.3f}," if d else ""
        ms = int(round(float(segm["start"]) * 1000))
        fc.append(f"[{idx}:a]{atrim}asetpts=PTS-STARTPTS,adelay={ms}|{ms},"
                  f"volume={float(segm['volume'])}[m{j}]")
        mus_labels.append(f"[m{j}]")
        idx += 1
    if dlg_labels:
        fc.append(f"{''.join(dlg_labels)}amix=inputs={len(dlg_labels)}"
                  f":duration=longest:normalize=0[dlg]")
    if mus_labels:
        fc.append(f"{''.join(mus_labels)}amix=inputs={len(mus_labels)}"
                  f":duration=longest:normalize=0[mus]")
    if dlg_labels and mus_labels:
        fc.append("[dlg][mus]amix=inputs=2:duration=first:normalize=0[aout]")
    elif dlg_labels:
        fc.append("[dlg]anull[aout]")
    elif mus_labels:
        fc.append("[mus]anull[aout]")

    out = os.path.abspath(str(out_path))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs]
    if fc:
        cmd += ["-filter_complex", ";".join(fc),
                "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-map", "0:v", "-an"]
    cmd += ["-c:v", "copy", "-movflags", "+faststart", "-shortest", out]
    run(cmd)

    dur = probe_duration(out)
    size = os.path.getsize(out)
    print(f"WROTE {out}  duration={dur:.2f}s (planned {total:.2f}s)  "
          f"size={size / 1e6:.1f} MB  flow_scenes={flow_used}")
    if not keep and not workdir:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return out, dur, size, flow_used


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ToonForge Flow-clip re-assembly")
    ap.add_argument("plan", help="motion-plan JSON (v1 episode.motionplan.json)")
    ap.add_argument("flow_dir", help="dir with scene_NN.mp4 Flow clips")
    ap.add_argument("out", help="output MP4 path")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    flow_assemble(a.plan, a.flow_dir, a.out, a.workdir, a.keep)
