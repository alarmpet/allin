"""prompt_director_skill: shots → 컷별 영어 프롬프트 + prompt_XXX.txt 저장

- 한 번의 LLM 호출로 모든 컷 프롬프트를 생성(성능: 호출 최소화).
- LLM이 일부 컷을 빠뜨리면 컷 데이터로 결정론적 프롬프트를 만들어 채운다(안정성).
- prompt_XXX.txt는 WanGP에 '파일 내용 전체 복붙'이 되도록 순수 프롬프트만 저장.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core import llm_client
from . import _common
from . import ltx_prompt_enhancer_skill
from . import prompt_quality_score
from . import wangp_deepy_bridge_skill

_PROMPT_TAIL = (
    "vertical short-form composition"
)


def _fallback_prompt(shot: Dict[str, Any], style_hint: str) -> str:
    """LLM 프롬프트가 비었을 때 컷 필드로 조립하는 백업 프롬프트."""
    subject = shot.get("korean_description", "").strip()
    kws = ", ".join(shot.get("keywords", []))
    parts = [
        kws or subject or "a cinematic scene",
        f"{shot.get('motion', 'gentle motion')}",
        f"camera: {shot.get('camera', 'slow push-in')}",
        f"{shot.get('lighting', 'soft natural light')}",
        f"mood: {shot.get('emotion', 'neutral')}",
        style_hint,
        _PROMPT_TAIL,
    ]
    return ", ".join(p for p in parts if p)


def generate_prompts(cfg: Dict[str, Any], pm, project: Dict[str, Any],
                     shots_data: Dict[str, Any]) -> Dict[str, Any]:
    shots: List[Dict[str, Any]] = shots_data["shots"]
    ctx = _common.style_context(project.get("input_mode", ""), project.get("style_preset", ""))
    negative = _common.negative_prompt_for(project.get("input_mode", ""),
                                           project.get("style_preset", ""))

    # LLM에 넘길 최소 정보(토큰 절약)
    slim = [{
        "shot_number": s["shot_number"],
        "korean_description": s["korean_description"],
        "keywords": s["keywords"],
        "emotion": s["emotion"],
        "camera": s["camera"],
        "lighting": s["lighting"],
        "motion": s["motion"],
    } for s in shots]

    system = _common.load_prompt("system_director.md")
    template = _common.load_prompt("wangp_ltx2_prompt_template.md")
    user = (
        template
        .replace("{style_context}", ctx)
        .replace("{shots_json}", json.dumps(slim, ensure_ascii=False, indent=2))
    )

    log_path = pm.path("logs", "ollama.log")
    prompt_by_num: Dict[int, str] = {}
    try:
        data = llm_client.chat_json(cfg, system, user, log_path=log_path)
        items = data.get("prompts", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("english_video_prompt"):
                    prompt_by_num[int(it.get("shot_number", 0))] = \
                        str(it["english_video_prompt"]).strip()
    except llm_client.LLMError:
        # 프롬프트 생성이 실패해도 백업으로 진행 (사용자 작업이 멈추지 않게)
        prompt_by_num = {}

    style_hint = ctx.splitlines()[0].replace("STYLE:", "").strip() if ctx else ""

    # 각 컷에 프롬프트 채우고 txt 저장
    for s in shots:
        num = s["shot_number"]
        eng = prompt_by_num.get(num, "").strip()
        if not eng:
            eng = _fallback_prompt(s, style_hint)
        s["english_video_prompt"] = eng
        s["negative_prompt"] = negative
        s["status"] = "prompt_ready"

        # base_prompt 보존 (연구소 탭에서 원본 비교용)
        s["base_prompt"] = eng

        # ltx_prompt는 초기에 base_prompt와 동일하게 초기화
        # (LTX-2 특화 강화는 사용자가 연구소 탭에서 명시적으로 실행할 때만 수행)
        s.setdefault("ltx_prompt", eng)
        s.setdefault("ltx_negative_prompt", negative)

        # 품질 채점 (규칙 기반, LLM 호출 없음)
        score = prompt_quality_score.evaluate_prompt(eng)
        s["prompt_quality_score"] = score

        # Deepy 팩 초기 빌드 (LLM 호출 없음)
        s["deepy_prompt_pack"] = wangp_deepy_bridge_skill.build_deepy_pack(s)

        # 기본 텍스트 파일 저장
        pm.save_text(f"prompt_{num:03d}.txt", eng + "\n")

    # 공통 negative prompt 파일
    pm.save_text("negative_prompt.txt", negative + "\n")

    # WanGP / Deepy 개별 복사용 파일들 일괄 빌드 및 md 저장
    wangp_deepy_bridge_skill.export_wangp_files(pm, shots_data)

    pm.save_json("shots.json", shots_data)
    return shots_data
