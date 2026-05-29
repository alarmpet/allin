"""skills 공용 helper: 프롬프트 템플릿 로딩 + 스타일 컨텍스트 매핑."""
from __future__ import annotations

import os
from typing import Dict

_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts"
)

# CLI 입력 모드 / style_preset → 스타일 파일명
STYLE_FILES: Dict[str, str] = {
    "emotional": "style_emotional.md",
    "mochi": "style_mochi.md",
    "mochi_animal_story": "style_mochi.md",
    "mochi_emotional": "style_mochi.md",
    "product_cf": "style_product_cf.md",
    "info": "style_info.md",
    "senior": "style_senior_trot.md",
    "senior_trot": "style_senior_trot.md",
    "anime_3d": "style_anime_3d.md",
    "claymation": "style_claymation.md",
    "lofi_3d_figure": "style_lofi_3d_figure.md",
    "stickman_sketch": "style_stickman_sketch.md",
    "asmr_cinematic": "style_asmr_cinematic.md",
    "neo_closure_vlog": "style_neo_closure_vlog.md",
    "retro_8bit": "style_retro_8bit.md",
    "cyberpunk_neon": "style_cyberpunk_neon.md",
    "minimal_beauty_cf": "style_minimal_beauty_cf.md",
    "vlog_illus_self": "style_vlog_illus_self.md",
    "wabi_sabi_japan": "style_wabi_sabi_japan.md",
}

# 스타일 파일을 못 찾았을 때 쓰는 공통 negative prompt
DEFAULT_NEGATIVE = (
    "text, subtitles, watermark, logo, low resolution, blurry, "
    "distorted anatomy, extra limbs, frame border, deformed"
)


def load_prompt(name: str) -> str:
    """prompts/ 폴더의 템플릿(.md)을 읽어온다."""
    path = os.path.join(_PROMPTS_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def style_file_for(key: str) -> str | None:
    if not key:
        return None
    return STYLE_FILES.get(key.lower())


def style_context(input_mode: str = "", style_preset: str = "") -> str:
    """모드/프리셋에 맞는 스타일 설명 텍스트를 반환 (LLM 프롬프트에 주입)."""
    fname = style_file_for(style_preset) or style_file_for(input_mode)
    if fname:
        try:
            return load_prompt(fname).strip()
        except FileNotFoundError:
            pass
    return "STYLE: General cinematic short-form video. Clean, visually clear, one action per shot."


def negative_prompt_for(input_mode: str = "", style_preset: str = "") -> str:
    """스타일 파일에 적힌 'Default negative prompt:' 줄을 추출. 없으면 공통값."""
    ctx = style_context(input_mode, style_preset)
    lines = ctx.splitlines()
    for i, line in enumerate(lines):
        if "negative prompt" in line.lower():
            # 같은 줄 뒤 또는 다음 줄에서 실제 값 찾기
            after = line.split(":", 1)[1].strip() if ":" in line else ""
            if after:
                return after
            if i + 1 < len(lines) and lines[i + 1].strip():
                return lines[i + 1].strip()
    return DEFAULT_NEGATIVE


def _extract_block_after_heading(ctx: str, heading: str) -> str:
    lines = ctx.splitlines()
    collecting = False
    values = []
    for line in lines:
        stripped = line.strip()
        if collecting:
            if not stripped:
                continue
            if stripped.endswith(":") or (":" in stripped and any(h in stripped.lower() for h in ["mood", "visual style", "camera", "texture cues", "style lock prefix", "default negative prompt"])):
                break
            values.append(stripped)
            continue
        if heading.lower() in stripped.lower():
            after = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if after:
                return after
            collecting = True
    return " ".join(values).strip()


def style_lock_prefix_for(style_preset: str = "", input_mode: str = "") -> str:
    ctx = style_context(input_mode, style_preset)
    return _extract_block_after_heading(ctx, "Style lock prefix")


def style_lock_negative_for(style_preset: str = "", input_mode: str = "") -> str:
    return negative_prompt_for(input_mode, style_preset)
