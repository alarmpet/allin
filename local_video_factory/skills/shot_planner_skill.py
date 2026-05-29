"""shot_planner_skill: script_segments → shots.json

문장을 6초 이하 컷으로 그룹핑(LLM) → 타이밍/파일경로는 코드가 결정(결정론적).
LLM이 흔들려도 길이·번호·파일명이 깨지지 않도록 분리했다.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List

from core import llm_client, validate_json
from . import _common


def _shot_seconds(project: Dict[str, Any]) -> float:
    fps = project.get("fps", 24) or 24
    frames = project.get("frames_per_shot", 141) or 141
    return round(frames / fps, 3)  # 141/24 = 5.875


def _target_shot_count(project: Dict[str, Any], segments: List[Dict[str, Any]],
                       shot_seconds: float) -> int:
    target_duration = project.get("target_duration", 0) or 0
    if target_duration > 0:
        return max(1, round(target_duration / shot_seconds))
    # '자동'이면 문장 수 기준 (너무 많으면 뒤에서 합쳐짐)
    return max(1, len(segments))


def plan_shots(cfg: Dict[str, Any], pm, project: Dict[str, Any],
               segments_data: Dict[str, Any]) -> Dict[str, Any]:
    segments: List[Dict[str, Any]] = segments_data["segments"]
    shot_seconds = _shot_seconds(project)
    max_shot = project.get("max_shot_duration", cfg["default_max_shot_seconds"])
    target_shots = _target_shot_count(project, segments, shot_seconds)

    system = _common.load_prompt("system_director.md")
    template = _common.load_prompt("shot_planner.md")
    ctx = _common.style_context(project.get("input_mode", ""), project.get("style_preset", ""))

    user = (
        template
        .replace("{shot_seconds}", str(shot_seconds))
        .replace("{max_shot_seconds}", str(max_shot))
        .replace("{target_shots}", str(target_shots))
        .replace("{target_duration}", str(project.get("target_duration", 0)))
        .replace("{style_context}", ctx)
        .replace("{segments_json}", json.dumps(segments, ensure_ascii=False, indent=2))
    )

    log_path = pm.path("logs", "ollama.log")
    data = llm_client.chat_json(cfg, system, user, log_path=log_path)
    data = validate_json.validate_shots(data)

    seg_by_id = {s["segment_id"]: s for s in segments}
    enriched: List[Dict[str, Any]] = []
    start = 0.0
    for idx, shot in enumerate(data["shots"], start=1):
        src = shot.get("source_sentences") or []
        if isinstance(src, int):
            src = [src]
        src = [int(s) for s in src if str(s).isdigit() or isinstance(s, int)]
        # source 문장들의 tts_text를 이어 붙여 컷 나레이션을 만든다 (결정론적)
        tts_parts = [seg_by_id[s]["tts_text"] for s in src if s in seg_by_id]
        tts_text = " ".join(tts_parts).strip() or str(shot.get("tts_text", "")).strip()

        duration = shot_seconds
        end = round(start + duration, 3)
        num = idx
        # 장면 설명이 비면 컷 보드 카드가 허전해진다 → 키워드/나레이션으로 보강
        kdesc = str(shot.get("korean_description", "")).strip()
        if not kdesc:
            kws_ko = ", ".join(str(k) for k in (shot.get("keywords") or []))
            kdesc = kws_ko or (tts_text[:40] if tts_text else f"{num}번째 장면")
        enriched.append({
            "shot_number": num,
            "chapter_id": int(shot.get("chapter_id", 1) or 1),
            "start_time": round(start, 3),
            "end_time": end,
            "duration": duration,
            "source_sentences": src,
            "korean_description": kdesc,
            "keywords": [str(k).strip() for k in (shot.get("keywords") or []) if str(k).strip()],
            "emotion": str(shot.get("emotion", "neutral")).strip() or "neutral",
            "camera": str(shot.get("camera", "slow push-in")).strip(),
            "lighting": str(shot.get("lighting", "soft natural light")).strip(),
            "motion": str(shot.get("motion", "gentle motion")).strip(),
            # 아래 두 칸은 prompt_director가 채운다
            "english_video_prompt": "",
            "negative_prompt": "",
            "tts_text": tts_text,
            "tts_file": f"audio/audio_{num:03d}.wav",
            "subtitle_ko": tts_text,
            "video_file": f"outputs/shot_{num:03d}.mp4",
            "status": "planned",
        })
        start = end

    total_duration = round(start, 3)
    result = {
        "project_title": project.get("project_title", ""),
        "target_platform": "YouTube Shorts, TikTok, Instagram Reels",
        "target_duration": total_duration,
        "max_shot_duration": max_shot,
        "estimated_total_shots": len(enriched),
        "style_preset": project.get("style_preset", ""),
        "fps": project.get("fps", cfg["default_fps"]),
        "frames_per_shot": project.get("frames_per_shot", cfg["default_frames_per_shot"]),
        "shots": enriched,
    }
    pm.save_json("shots.json", result)
    return result
