"""script_parser_skill: 대본 → script_segments.json

문장 분리 / 의미·감정 분석 / 키워드 / 시각화 가능성 / tts_text 생성.
"""
from __future__ import annotations

from typing import Any, Dict

from core import llm_client, validate_json
from . import _common


def parse_script(cfg: Dict[str, Any], pm, project: Dict[str, Any],
                 script_text: str) -> Dict[str, Any]:
    """대본을 분석해 script_segments.json을 만들고 저장한다. 정규화된 dict 반환."""
    system = _common.load_prompt("system_director.md")
    template = _common.load_prompt("script_parser.md")
    ctx = _common.style_context(project.get("input_mode", ""), project.get("style_preset", ""))

    user = (
        template
        .replace("{style_context}", ctx)
        .replace("{target_duration}", str(project.get("target_duration", 0)))
        .replace("{script}", script_text.strip())
    )

    log_path = pm.path("logs", "ollama.log")
    try:
        data = llm_client.chat_json(cfg, system, user, log_path=log_path)
        data = validate_json.validate_segments(data)
    except Exception as e:
        # LLM 응답 실패 또는 포맷 이탈 시 대본을 직접 문장별로 분해하는 폴백 적용
        # 에러 기록 보존
        try:
            with open(pm.path("logs", "error.log"), "a", encoding="utf-8") as f:
                f.write(f"LLM 대본 분석 실패로 폴백이 작동함: {e}\n")
        except Exception:
            pass
            
        sentences = [s.strip() for s in script_text.replace("\n", " ").split(".") if s.strip()]
        if not sentences:
            sentences = [script_text.strip()]
            
        fallback_segments = []
        for i, s in enumerate(sentences, start=1):
            fallback_segments.append({
                "segment_id": i,
                "sentence": s,
                "meaning": s,
                "emotion": "neutral",
                "keywords": ["cinematic", "visual"],
                "visual_potential": "medium",
                "tts_text": s
            })
        data = {"segments": fallback_segments}

    # 메타 정보 보강
    result = {
        "project_title": project.get("project_title", ""),
        "original_script": script_text.strip(),
        "target_duration": project.get("target_duration", 0),
        "max_shot_duration": project.get("max_shot_duration", cfg["default_max_shot_seconds"]),
        "segments": data["segments"],
    }
    pm.save_json("script_segments.json", result)
    return result
