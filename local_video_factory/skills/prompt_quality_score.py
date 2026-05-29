"""prompt_quality_score: 생성된 프롬프트의 품질을 검사하고 점수화한다."""
from __future__ import annotations

import re
from typing import Any, Dict, List


def evaluate_prompt(prompt: str) -> Dict[str, Any]:
    """프롬프트를 검사하여 점수와 개선사항을 반환한다."""
    p_lower = prompt.lower()
    issues: List[str] = []
    suggestions: List[str] = []
    
    score = 100
    
    # 1. 길이 체크
    words = [w for w in re.split(r'\s+', prompt) if w]
    word_count = len(words)
    if word_count < 15:
        score -= 15
        issues.append("프롬프트 길이가 너무 짧습니다.")
        suggestions.append("세부 묘사나 배경, 환경적 세부사항을 추가하세요 (최소 20단어 이상 권장).")
    elif word_count > 100:
        score -= 5
        issues.append("프롬프트가 다소 깁니다.")
        suggestions.append("LTX-2는 80단어 내외의 명확한 문장을 선호합니다. 불필요한 단어를 지우세요.")

    # 2. 카메라 무브먼트 체크
    camera_terms = ["camera", "pan", "tilt", "dolly", "zoom", "push-in", "dolly back", "tracking", "static", "gimbal", "crane", "pedestal"]
    if not any(t in p_lower for t in camera_terms):
        score -= 15
        issues.append("카메라 모션 또는 구도 묘사가 누락되었습니다.")
        suggestions.append("카메라 움직임(예: 'slow pan', 'steady dolly back') 또는 렌즈 사양('35mm lens')을 기재하세요.")

    # 3. 조명/라이팅 체크
    lighting_terms = ["light", "illumination", "glow", "shadow", "sunlight", "ambient", "bright", "dim", "neon", "sunset", "golden hour", "warm light"]
    if not any(t in p_lower for t in lighting_terms):
        score -= 10
        issues.append("조명/라이팅에 대한 묘사가 누락되었습니다.")
        suggestions.append("빛의 방향이나 세기, 분위기(예: 'soft golden hour light', 'neon glow')를 추가하세요.")

    # 4. LTX-2 전용 오디오 단어 체크
    audio_terms = ["sound", "audio", "noise", "rustle", "wind", "chatter", "ambient", "hum", "rumble", "whistle", "clatter", "whisper", "echo"]
    if not any(t in p_lower for t in audio_terms):
        score -= 15
        issues.append("오디오 사운드 묘사가 누락되었습니다.")
        suggestions.append("LTX-2는 소리를 함께 만듭니다. 'the sound of distant wind' 또는 'gentle paper rustle' 같은 사운드 단어를 추가해 보세요.")

    # 5. 부정어 오작동 검사 (긍정 프롬프트 내에 부정어가 있는지)
    neg_terms = ["no text", "no subtitles", "no logo", "no watermark", "without text", "clean video"]
    if any(t in p_lower for t in neg_terms):
        score -= 20
        issues.append("긍정 프롬프트 내에 부정어가 포함되어 오작동 위험이 있습니다.")
        suggestions.append("'no text' 등의 문구를 긍정 프롬프트에서 삭제하고, Negative Prompt 필드로 이동시키세요.")

    # 6. 해상도 및 퀄리티 지시어 체크
    quality_terms = ["cinematic", "realism", "texture", "8k", "depth of field", "bokeh", "photorealistic"]
    if not any(t in p_lower for t in quality_terms):
        score -= 10
        issues.append("영화적 화질 유도 지시어가 부족합니다.")
        suggestions.append("'cinematic realism' 또는 'shallow depth of field' 등을 활용해 품질을 강화하세요.")

    # 점수 범위 제한
    score = max(0, min(100, score))
    
    return {
        "overall": score,
        "issues": issues,
        "suggestions": suggestions
    }
