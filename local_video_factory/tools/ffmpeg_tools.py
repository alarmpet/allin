"""ffmpeg_tools: 컷 영상 + 나레이션 + 자막 → 9:16 final.mp4

문서 05/06/08:
- 컷 영상 합치기, 컷별 TTS 오디오 매칭, 자막 입히기, 9:16 변환
- h264_nvenc 가능 시 사용, 실패 시 libx264 대체
- 누락 컷 검사, 준비된 컷만 합치기, 검은 화면 임시 대체
- 실패 시 자막 없이 / 오디오 없이 재시도 옵션

처리 흐름:
  1) 컷마다 9:16 캔버스로 정규화한 클립 생성(영상+오디오, 길이=timeline used_duration)
  2) concat 데먹서로 이어붙임
  3) captions.srt 번인(맑은고딕). 실패 시 자막 없이 출력.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, Iterator, List, Optional, Tuple

# 9:16 세로 캔버스 (쇼츠 표준)
CANVAS_W, CANVAS_H = 720, 1280
_SUB_FREEZE_PAD = 600  # tpad clone 최대 길이(초) — -t로 잘리므로 넉넉히


class FFmpegError(Exception):
    """ffmpeg 실패. message는 사용자에게 보여줄 쉬운 문장."""


# ── 기본 점검 ──────────────────────────────────────────────────
def check_ffmpeg(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    ff = cfg.get("ffmpeg_path", "ffmpeg")
    try:
        r = subprocess.run([ff, "-version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=15)
        if r.returncode == 0:
            first = (r.stdout or "").splitlines()[0] if r.stdout else "ffmpeg"
            return True, f"ffmpeg 사용 가능: {first}"
    except (OSError, subprocess.SubprocessError):
        pass
    return False, "ffmpeg를 찾지 못했어요. config.yaml의 ffmpeg_path를 확인해 주세요."


def _run(cmd: List[str], *, cwd: Optional[str] = None, log_path: Optional[str] = None,
         timeout: int = 1800) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n$ " + " ".join(cmd) + "\n")
                f.write((proc.stderr or "")[-4000:] + "\n")
        except Exception:  # noqa: BLE001
            pass
    return proc


def _probe_encoder(cfg: Dict[str, Any], log_path: Optional[str]) -> str:
    """nvenc가 실제로 동작하면 'h264_nvenc', 아니면 'libx264'."""
    ff = cfg.get("ffmpeg_path", "ffmpeg")
    test = _run(
        [ff, "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.2",
         "-c:v", "h264_nvenc", "-f", "null", os.devnull],
        log_path=log_path, timeout=60,
    )
    return "h264_nvenc" if test.returncode == 0 else "libx264"


def _venc_args(encoder: str) -> List[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p"]


# ── 누락 검사 (문서 08) ────────────────────────────────────────
def missing_check(pm, shots_data: Dict[str, Any]) -> Dict[str, Any]:
    shots = shots_data["shots"]
    total = len(shots)
    videos, audio, zero = [], [], []
    for s in shots:
        num = s["shot_number"]
        vf = s.get("video_file", "")
        if not vf or not os.path.isfile(pm.path(vf)):
            videos.append(num)
        af = s.get("tts_file", "")
        if not af or not os.path.isfile(pm.path(af)):
            audio.append(num)
        if float(s.get("duration", 0) or 0) <= 0 and float(s.get("tts_duration", 0) or 0) <= 0:
            zero.append(num)
    return {
        "total": total,
        "videos_ready": total - len(videos),
        "audio_ready": total - len(audio),
        "missing_videos": videos,
        "missing_audio": audio,
        "zero_duration": zero,
        "subtitles": os.path.isfile(pm.path("captions.srt")),
    }


# ── 클립 길이 ──────────────────────────────────────────────────
def _durations(project, shots_data, timeline) -> Dict[int, float]:
    """컷별 사용할 길이 (timeline 우선, 없으면 video/frames 기반)."""
    fps = project.get("fps", 24) or 24
    frames = project.get("frames_per_shot", 141) or 141
    video_dur = round(frames / fps, 3)
    tl = {e["shot_number"]: e for e in (timeline or {}).get("shots", [])}
    out = {}
    for s in shots_data["shots"]:
        num = s["shot_number"]
        if num in tl:
            out[num] = max(0.5, float(tl[num]["used_duration"]))
        else:
            tts = float(s.get("tts_duration", 0) or 0)
            out[num] = max(0.5, tts if tts > 0 else video_dur)
    return out


# ── 핵심: 최종 합성 ────────────────────────────────────────────
def build_final(cfg: Dict[str, Any], pm, project: Dict[str, Any],
                shots_data: Dict[str, Any], timeline: Dict[str, Any], *,
                include: str = "ready", with_audio: bool = True,
                with_subtitles: bool = True, black_for_missing: bool = False
                ) -> Iterator[Tuple]:
    """final.mp4를 만든다. 진행상황을 yield 하고 마지막에 ("done", result).

    include: 'ready'(영상 있는 컷만) | 'all'(전부, 영상 없으면 검은화면 필요)
    """
    ff = cfg.get("ffmpeg_path", "ffmpeg")
    log_path = pm.path("logs", "ffmpeg.log")
    fps = project.get("fps", cfg["default_fps"]) or cfg["default_fps"]
    durs = _durations(project, shots_data, timeline)

    # 포함할 컷 선정
    shots = shots_data["shots"]
    selected = []
    for s in shots:
        has_video = bool(s.get("video_file")) and os.path.isfile(pm.path(s["video_file"]))
        if has_video or black_for_missing:
            selected.append((s, has_video))
        elif include == "all":
            # all 인데 영상 없고 검은화면도 아니면 건너뜀
            continue
    if not selected:
        yield ("done", {"ok": False, "path": "",
                        "message": "합칠 수 있는 컷이 없어요. 먼저 컷 영상을 만들어 주세요."})
        return

    yield ("progress", 0, len(selected) + 1, "영상 인코더를 준비하고 있어요...")
    encoder = _probe_encoder(cfg, log_path)

    clips_dir = pm.path("outputs", "_clips")
    os.makedirs(clips_dir, exist_ok=True)
    clip_paths: List[str] = []

    try:
        for i, (s, has_video) in enumerate(selected, start=1):
            num = s["shot_number"]
            dur = durs.get(num, round(fps and project.get("frames_per_shot", 141) / fps or 5.875, 3))
            yield ("progress", i, len(selected) + 1, f"컷 {num:03d} 영상을 9:16으로 다듬고 있어요...")

            clip = os.path.join(clips_dir, f"clip_{num:03d}.mp4")
            audio_rel = s.get("tts_file", "")
            audio_ok = with_audio and audio_rel and os.path.isfile(pm.path(audio_rel))

            cmd = [ff, "-hide_banner", "-y"]
            # 비디오 입력
            if has_video:
                cmd += ["-i", pm.path(s["video_file"])]
            else:  # 검은 화면 대체
                cmd += ["-f", "lavfi", "-i",
                        f"color=c=black:s={CANVAS_W}x{CANVAS_H}:r={fps}:d={dur}"]
            # 오디오 입력
            if audio_ok:
                cmd += ["-i", pm.path(audio_rel)]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]

            vfilter = (
                f"[0:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease,"
                f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"tpad=stop_mode=clone:stop_duration={_SUB_FREEZE_PAD}[v];"
                f"[1:a]apad[a]"
            )
            cmd += [
                "-filter_complex", vfilter, "-map", "[v]", "-map", "[a]",
                "-t", f"{dur:.3f}", "-r", str(fps),
                *_venc_args(encoder), "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
                clip,
            ]
            proc = _run(cmd, log_path=log_path)
            if proc.returncode != 0 or not os.path.isfile(clip):
                # nvenc 실패 시 libx264로 1회 폴백
                if encoder != "libx264":
                    encoder = "libx264"  # 이후 컷부터는 libx264로
                    proc2 = _run(_rebuild_with_libx264(cmd), log_path=log_path)
                    if proc2.returncode != 0 or not os.path.isfile(clip):
                        raise FFmpegError(f"컷 {num:03d} 영상 변환에 실패했어요.")
                else:
                    raise FFmpegError(f"컷 {num:03d} 영상 변환에 실패했어요.")
            clip_paths.append(clip)

        # concat
        yield ("progress", len(selected) + 1, len(selected) + 1, "컷들을 이어붙이고 자막을 입히고 있어요...")
        list_file = os.path.join(clips_dir, "concat.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for c in clip_paths:
                f.write(f"file '{c.replace(os.sep, '/')}'\n")
        concat_path = os.path.join(clips_dir, "concat.mp4")
        proc = _run([ff, "-hide_banner", "-y", "-f", "concat", "-safe", "0",
                    "-i", list_file, "-c", "copy", concat_path], log_path=log_path)
        if proc.returncode != 0 or not os.path.isfile(concat_path):
            # copy 실패 시 재인코딩 concat
            proc = _run([ff, "-hide_banner", "-y", "-f", "concat", "-safe", "0",
                        "-i", list_file, *_venc_args(encoder), "-c:a", "aac",
                        concat_path], log_path=log_path)
            if proc.returncode != 0 or not os.path.isfile(concat_path):
                raise FFmpegError("컷들을 이어붙이는 데 실패했어요.")

        final_path = pm.path("outputs", "final.mp4")
        srt_ok = with_subtitles and os.path.isfile(pm.path("captions.srt"))
        subtitle_burned = False
        if srt_ok:
            # cwd를 프로젝트 폴더로 두고 상대경로 'captions.srt' 사용 → Windows 경로 이스케이프 회피
            style = "FontName=Malgun Gothic,FontSize=28,Outline=2,Shadow=0,MarginV=120,Alignment=2,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"
            sub_cmd = [ff, "-hide_banner", "-y", "-i", concat_path,
                       "-vf", f"subtitles=captions.srt:force_style='{style}'",
                       *_venc_args(encoder), "-c:a", "copy", final_path]
            proc = _run(sub_cmd, cwd=pm.dir, log_path=log_path)
            subtitle_burned = proc.returncode == 0 and os.path.isfile(final_path)

        if not subtitle_burned:
            shutil.copyfile(concat_path, final_path)

        # 정리
        _cleanup(clips_dir)

        msg = f"최종 영상이 완성됐어요! (컷 {len(selected)}개"
        msg += ", 자막 포함)" if subtitle_burned else ", 자막 없이)" if with_subtitles else ")"
        yield ("done", {
            "ok": True, "path": final_path,
            "subtitle_burned": subtitle_burned,
            "shots_used": len(selected),
            "encoder": encoder,
            "message": msg,
        })

    except FFmpegError as e:
        _cleanup(clips_dir)
        yield ("done", {"ok": False, "path": "", "message": str(e),
                        "hint": "‘자막 없이’ 또는 ‘준비된 컷만’ 옵션으로 다시 시도해 보세요."})
    except subprocess.TimeoutExpired:
        _cleanup(clips_dir)
        yield ("done", {"ok": False, "path": "", "message": "영상 합치기가 너무 오래 걸려 멈췄어요."})


def _rebuild_with_libx264(cmd: List[str]) -> List[str]:
    """nvenc 인자를 libx264로 치환한 새 명령 반환."""
    out: List[str] = []
    skip = 0
    nvenc_flags = {"-preset", "-rc", "-cq"}
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == "-c:v":
            out += ["-c:v", "libx264", "-preset", "medium", "-crf", "21"]
            i += 2  # skip '-c:v' and its value
            continue
        if tok in nvenc_flags:
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def _cleanup(clips_dir: str) -> None:
    try:
        shutil.rmtree(clips_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def open_result_folder(pm) -> bool:
    try:
        os.startfile(pm.outputs_dir)  # type: ignore[attr-defined]
        return True
    except Exception:  # noqa: BLE001
        return False
