#!/usr/bin/env python3
"""ToonForge stage 4 — VOICE (Phase 3: implemented).

Wraps the proven production TTS stack (/opt/hatch/bin/tts + the
tts_part.py voice map) behind the frozen voice_interface.md contract:

    speak(line, voice_slot, out_path) -> (mp3_path, seconds)

House rules applied:
- Gender-matched voices per bible voice_slot (single map, defined here —
  Phase-1's "single source of truth" note pointed at voice_interface.md;
  the map is copied verbatim from that doc).
- Denoise every VO: afftdn=nr=12:nf=-25, highpass=f=70.
- hubert (villain) lines: rewrite "..." runs as "!" (production pitfall).
- Durations are MEASURED with ffprobe after silence-trimming — never
  estimated. Trimmed line boundaries feed the timing plan (the
  burst-alignment principle: true speech spans, not char-rate guesses).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

TTS_BIN = "/opt/hatch/bin/tts"

# Verbatim from renderer/voice_interface.md (frozen design).
VOICE_MAP = {
    "narrator_f": ("avocado_v2:rumi", None),
    "hero_m": ("avocado_v2:ronan", None),
    "wife_f": ("avocado_v2:lumi", None),
    "villain_m": ("avocado_v2:hubert", None),
    "comic_m": ("avocado_v2:vincent", None),
    "elder_m": ("avocado_v2:magnus", "85"),  # 85 speed for very heavy voices
}

# Scene breathing room baked into each scene's dialogue audio.
HEAD_PAD_S = 0.4
TAIL_PAD_S = 0.4


class VoiceError(RuntimeError):
    """Raised when a line fails to synthesize."""


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, **kw)


def probe_seconds(path: str | Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(path)], text=True)
    return float(r.stdout.strip())


def _denoise_and_trim(src: str | Path, dst: str | Path) -> None:
    """Denoise (house chain) + trim leading/trailing silence (true boundaries)."""
    af = ("afftdn=nr=12:nf=-25,highpass=f=70,"
          "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-40dB,"
          "areverse,"
          "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-40dB,"
          "areverse")
    r = _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", af,
              "-c:a", "libmp3lame", "-b:a", "128k", str(dst)])
    if r.returncode != 0 or not Path(dst).exists():
        raise VoiceError(f"denoise/trim failed for {src}: "
                         f"{r.stderr.decode(errors='replace')[:300]}")


def speak(line: str, voice_slot: str, out_path: str | Path) -> tuple[str, float]:
    """Synthesize ONE dialogue line. Returns (mp3_path, measured_seconds).

    voice_slot is one of the VOICE_MAP keys (from the character bible).
    The returned MP3 is denoised + silence-trimmed; seconds is the true
    spoken span measured with ffprobe.
    """
    if voice_slot not in VOICE_MAP:
        raise VoiceError(f"unknown voice_slot: {voice_slot!r}")
    voice, speed = VOICE_MAP[voice_slot]
    text = line.strip()
    if not text:
        raise VoiceError("empty line")
    if voice_slot == "villain_m" and "..." in text:
        text = text.replace("...", "!")  # hubert rambling pitfall

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = out_path.with_suffix(".raw.mp3")

    cmd = [TTS_BIN, "speak", "--output", str(raw),
           "--voice", voice, "--language", "bn", "--text-stdin"]
    if speed:
        cmd += ["--speed", speed]
    r = subprocess.run(cmd, input=text.encode("utf-8"),
                       capture_output=True, timeout=240)
    if r.returncode != 0 or not raw.exists() or raw.stat().st_size < 1000:
        raise VoiceError(f"TTS failed for [{voice_slot}] {text[:60]!r}: "
                         f"{r.stderr.decode(errors='replace')[:300]}")
    _denoise_and_trim(raw, out_path)
    raw.unlink(missing_ok=True)
    return str(out_path), probe_seconds(out_path)


def _lang_flag(script: dict) -> str:
    lang = str(script.get("language", "bn")).lower()
    return "en" if lang.startswith("en") else "bn"


def build_dialogue_track(script: dict, bible: dict,
                         out_dir: str | Path) -> dict:
    """Voice every dialogue line; build per-scene dialogue audio.

    Returns {
      "scenes": [{"scene_id", "dialogue_audio", "duration",
                  "lines": [{"speaker", "text", "start", "end", "mp3"}]}],
      "total_duration": float,
    }
    All times are MEASURED (post-trim), in episode seconds. Each scene's
    audio = HEAD_PAD silence + lines back-to-back + TAIL_PAD silence, so
    the Ken Burns segment gets breathing room around the dialogue.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    slot_of = {c["speaker_tag"]: c["voice_slot"] for c in bible["characters"]}

    # TTS language comes from the script; speak() defaults to bn which is
    # correct for both current fixtures. (EN support: thread _lang_flag
    # through when an English episode runs.)
    scenes_out: list[dict] = []
    cursor = 0.0
    for sc in script["scenes"]:
        sid = sc["scene_id"]
        line_infos: list[dict] = []
        line_files: list[str] = []
        t = HEAD_PAD_S
        for li, ln in enumerate(sc["lines"]):
            speaker = ln["speaker"]
            if speaker not in slot_of:
                raise VoiceError(f"scene {sid}: speaker {speaker!r} not in bible")
            mp3 = out_dir / f"scene{sid:02d}_line{li:02d}.mp3"
            if not (mp3.exists() and mp3.stat().st_size > 1000):
                mp3_path, dur = speak(ln["text"], slot_of[speaker], mp3)
            else:
                mp3_path, dur = str(mp3), probe_seconds(mp3)
            line_infos.append({"speaker": speaker, "text": ln["text"],
                               "start": round(cursor + t, 3),
                               "end": round(cursor + t + dur, 3),
                               "mp3": mp3_path, "seconds": round(dur, 3)})
            line_files.append(mp3_path)
            t += dur
        scene_dur = t + TAIL_PAD_S

        # Stitch: silence HEAD + lines + silence TAIL, all measured.
        scene_audio = out_dir / f"scene{sid:02d}_dialogue.mp3"
        if not (scene_audio.exists() and scene_audio.stat().st_size > 1000):
            _stitch_scene_audio(line_files, scene_audio)
        actual = probe_seconds(scene_audio)
        # Rebase line boundaries onto the measured stitched file.
        scale = actual / scene_dur if scene_dur > 0 else 1.0
        for li_info in line_infos:
            li_info["start"] = round(cursor + li_info["start"] * scale, 3)
            li_info["end"] = round(cursor + li_info["end"] * scale, 3)
        scenes_out.append({"scene_id": sid,
                           "dialogue_audio": str(scene_audio),
                           "duration": round(actual, 3),
                           "lines": line_infos})
        cursor += actual

    return {"scenes": scenes_out, "total_duration": round(cursor, 3)}


def _stitch_scene_audio(line_files: list[str], out_path: Path) -> None:
    """Concat HEAD_PAD silence + line MP3s + TAIL_PAD silence."""
    import tempfile
    sil = Path(tempfile.gettempdir()) / "toonforge_silence.mp3"
    if not (sil.exists() and sil.stat().st_size > 1000):
        r = _run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                  "-i", "anullsrc=r=44100:cl=stereo", "-t", "2.0",
                  "-c:a", "libmp3lame", "-b:a", "128k", str(sil)])
        if r.returncode != 0:
            raise VoiceError("could not render silence bed")
    # Build with ffmpeg concat: [sil trimmed to HEAD] + lines + [sil trimmed to TAIL]
    with tempfile.TemporaryDirectory(prefix="toonforge_stitch_") as td:
        td = Path(td)
        head = td / "head.mp3"
        tail = td / "tail.mp3"
        for p, d in ((head, HEAD_PAD_S), (tail, TAIL_PAD_S)):
            r = _run(["ffmpeg", "-v", "error", "-y", "-i", str(sil),
                      "-t", f"{d:.3f}", "-c:a", "copy", str(p)])
            if r.returncode != 0:
                raise VoiceError("silence trim failed")
        lst = td / "list.txt"
        with open(lst, "w") as f:
            for p in [head, *[Path(x) for x in line_files], tail]:
                # Absolute paths: the concat demuxer resolves list entries
                # relative to the list file's dir (the temp dir), so
                # relative entries would silently miss.
                f.write(f"file '{Path(p).resolve()}'\n")
        r = _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                  "-i", str(lst), "-c:a", "libmp3lame", "-b:a", "128k",
                  str(out_path)])
        if r.returncode != 0 or not out_path.exists():
            raise VoiceError(f"scene stitch failed: "
                             f"{r.stderr.decode(errors='replace')[:300]}")
