"""timeline_builder_skill: 영상/음성 타임라인 정렬 → timeline.json

문서 05:
- 전체 길이 계산, 컷별 start/end
- TTS 길이와 영상 길이 비교, 오디오가 길면 해결 옵션 안내
- timeline.json 생성

영상 컷 길이는 frames/fps로 고정(LTX2). 나레이션이 그보다 길면 over_limit으로 표시.
자막/최종 합성에서 쓸 '실제 사용 길이(used_duration)'를 함께 계산한다.
"""
from __future__ import annotations

from typing import Any, Dict, List


def build_timeline(cfg: Dict[str, Any], pm, project: Dict[str, Any],
                   shots_data: Dict[str, Any]) -> Dict[str, Any]:
    shots: List[Dict[str, Any]] = shots_data["shots"]
    fps = project.get("fps", cfg["default_fps"]) or cfg["default_fps"]
    frames = project.get("frames_per_shot", cfg["default_frames_per_shot"]) or cfg["default_frames_per_shot"]
    video_dur = round(frames / fps, 3)
    max_shot = project.get("max_shot_duration", cfg["default_max_shot_seconds"])

    entries: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    start = 0.0
    for shot in shots:
        num = shot["shot_number"]
        tts_dur = float(shot.get("tts_duration", 0) or 0)
        # 나레이션이 있으면 그 길이를 따르고, 없으면 영상 컷 길이 사용
        used = tts_dur if tts_dur > 0 else video_dur
        over_limit = tts_dur > max_shot + 0.05  # 나레이션이 컷 최대 길이 초과
        end = round(start + used, 3)
        entries.append({
            "shot_number": num,
            "video_duration": video_dur,
            "tts_duration": round(tts_dur, 3),
            "used_duration": round(used, 3),
            "start": round(start, 3),
            "end": end,
            "over_limit": over_limit,
        })
        if over_limit:
            warnings.append({
                "shot_number": num,
                "tts_duration": round(tts_dur, 3),
                "max_shot_duration": max_shot,
                "message": f"컷 {num:03d}: 나레이션({tts_dur:.1f}초)이 컷 길이({max_shot}초)보다 길어요.",
                "options": ["문장 짧게 다시 쓰기", "말 속도 조금 빠르게", "영상 길이 조금 늘리기"],
            })
        start = end

    timeline = {
        "project_title": project.get("project_title", ""),
        "fps": fps,
        "video_duration_per_shot": video_dur,
        "max_shot_duration": max_shot,
        "total_duration": round(start, 3),
        "shots": entries,
        "warnings": warnings,
    }
    pm.save_json("timeline.json", timeline)
    return timeline
