"""ltx_prompt_enhancer_skill: 기본 컷 설명을 LTX-2에 최적화된 비디오/오디오 프롬프트로 강화한다."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core import llm_client
from . import _common


def enhance_prompt(cfg: Dict[str, Any], pm,
                   korean_description: str,
                   keywords: List[str],
                   emotion: str,
                   style_preset: str,
                   character_lock_prompt: str = "",
                   duration: float = 5.875) -> Dict[str, Any]:
    """단일 컷의 정보를 받아 LTX-2 최적화 프롬프트로 강화한다."""
    ctx = _common.style_context(style_preset, style_preset)
    negative = _common.negative_prompt_for(style_preset, style_preset)

    system_prompt = (
        "You are an expert prompt engineer specializing in LTX-2 and WanGP video generation.\n"
        "Your task is to rewrite a basic scene description into a highly detailed, cinematic, "
        "and physical action-based prompt in English.\n"
        "ALWAYS return a single JSON object."
    )

    user_prompt = f"""TASK: Enhance the following shot details into a professional LTX-2 prompt.

Shot Details:
- Korean Description: {korean_description}
- Keywords: {", ".join(keywords)}
- Emotion: {emotion}
- Style Preset context: {ctx}
- Character Lock Prompt: {character_lock_prompt}
- Duration (seconds): {duration}

LTX-2 Prompting Guidelines:
1. Describe ONE clear, concrete action. Avoid multiple separate actions or transitions.
2. Specify cinematic composition, lens details (e.g., "35mm lens", "shallow depth of field", "cinematic realism").
3. Specify camera movement (e.g., "slow dolly back", "gentle panning", "dramatic push-in").
4. Include ambient audio cues matching the scene (e.g., "the soft crackle of a fireplace", "distant rain falling", "gentle hum of traffic") because LTX-2 is a joint video-audio model.
5. DO NOT include negative constraints (like "no text", "no watermark") or duration text (like "about 6 seconds") in the positive prompt.
6. Incorporate the character lock prompt if provided.

Return ONLY this JSON format:
{{
  "ltx_prompt": "<the full English positive prompt>",
  "ltx_negative_prompt": "<negative prompt containing: text, subtitles, logo, watermark, low quality, blurry>"
}}
"""
    log_path = pm.path("logs", "ollama.log")
    try:
        data = llm_client.chat_json(cfg, system_prompt, user_prompt, log_path=log_path)
        ltx_prompt = str(data.get("ltx_prompt", "")).strip()
        ltx_neg = str(data.get("ltx_negative_prompt", negative)).strip()
    except Exception as e:
        # Fallback if LLM fails
        kws = ", ".join(keywords)
        parts = [
            character_lock_prompt,
            kws or korean_description,
            f"mood: {emotion}",
            "cinematic composition, shallow depth of field, realistic textures, slow camera motion",
            f"sound of ambient background matching {emotion} mood"
        ]
        ltx_prompt = ", ".join(p for p in parts if p)
        ltx_neg = negative

    return {
        "ltx_prompt": ltx_prompt,
        "ltx_negative_prompt": ltx_neg
    }
