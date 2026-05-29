"""Apply deterministic visual style consistency locks to generated shot prompts."""
from __future__ import annotations

from typing import Any, Dict

from . import _common


def _prepend_unique(prefix: str, text: str) -> str:
    prefix = (prefix or "").strip().rstrip(",")
    text = (text or "").strip()
    if not prefix:
        return text
    if text.lower().startswith(prefix.lower()):
        return text
    return f"{prefix}, {text}" if text else prefix


def _limit_words(text: str, max_words: int) -> str:
    words = text.split()
    if max_words <= 0 or len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",")


def apply_style_lock(shots_data: Dict[str, Any], style_preset: str,
                     char_lock: str = "", input_mode: str = "",
                     max_words: int = 80) -> Dict[str, Any]:
    prefix = _common.style_lock_prefix_for(style_preset, input_mode).strip().rstrip(",")
    style_negative = _common.style_lock_negative_for(style_preset, input_mode).strip().rstrip(",")
    char_lock = (char_lock or "").strip().rstrip(",")
    combined_prefix = ", ".join(p for p in (prefix, char_lock) if p)

    for shot in shots_data.get("shots", []):
        original = shot.get("english_video_prompt") or shot.get("ltx_prompt") or ""
        locked_prompt = _limit_words(_prepend_unique(combined_prefix, original), max_words)
        shot["english_video_prompt"] = locked_prompt
        shot["ltx_prompt"] = locked_prompt
        shot["base_prompt"] = shot.get("base_prompt") or original

        original_negative = shot.get("negative_prompt") or shot.get("ltx_negative_prompt") or ""
        locked_negative = _prepend_unique(style_negative, original_negative)
        shot["negative_prompt"] = locked_negative
        shot["ltx_negative_prompt"] = locked_negative
        shot["style_lock_applied"] = bool(combined_prefix or style_negative)
        shot["style_lock_prefix"] = combined_prefix

    return shots_data
