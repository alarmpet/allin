"""wangp_deepy_bridge_skill: 프롬프트를 WanGP Prompt Enhancer / Deepy용 팩으로 변환 및 파일 저장"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def build_deepy_pack(shot: Dict[str, Any], character_lock_prompt: str = "") -> Dict[str, Any]:
    """컷 정보를 기반으로 wangp_deepy_pack JSON 포맷 데이터를 만든다."""
    # LTX 프롬프트가 없으면 기본 프롬프트 사용
    pos = shot.get("ltx_prompt", shot.get("english_video_prompt", "")).strip()
    neg = shot.get("ltx_negative_prompt", shot.get("negative_prompt", "")).strip()

    # 카메라, 움직임, 조명 추출 시도
    camera = shot.get("camera", "slow push-in")
    motion = shot.get("motion", "gentle motion")
    lighting = shot.get("lighting", "soft natural light")

    return {
        "shot_number": shot["shot_number"],
        "use_prompt_enhancer": True,
        "use_deepy": True,
        "model_target": "LTX-2",
        "duration_seconds": shot.get("duration", 5.875),
        "frames": int(shot.get("duration", 5.875) * 24), # fps=24 기준
        "positive_prompt": pos,
        "negative_prompt": neg,
        "camera_hint": camera,
        "motion_hint": motion,
        "lighting_hint": lighting,
        "character_lock_prompt": character_lock_prompt,
        "copy_ready_prompt": f"{pos} --neg {neg} --camera {camera} --motion {motion}"
    }


def export_wangp_files(pm, shots_data: Dict[str, Any], character_lock_prompt: str = "") -> None:
    """모든 컷에 대한 WanGP/Deepy 복사용 파일들을 생성한다."""
    shots: List[Dict[str, Any]] = shots_data["shots"]
    batch_lines = [
        "# WanGP / Deepy Batch Prompts",
        f"Project ID: {pm.project_id}",
        "---",
        ""
    ]

    for s in shots:
        num = s["shot_number"]
        pos = s.get("ltx_prompt", s.get("english_video_prompt", "")).strip()
        neg = s.get("ltx_negative_prompt", s.get("negative_prompt", "")).strip()

        # 1. 텍스트 파일 저장
        pm.save_text(f"wangp_prompt_{num:03d}.txt", pos + "\n")
        pm.save_text(f"wangp_negative_{num:03d}.txt", neg + "\n")

        # 2. Deepy 팩 저장
        pack = build_deepy_pack(s, character_lock_prompt)
        s["deepy_prompt_pack"] = pack # shots.json 내부 갱신용
        pm.save_json(f"wangp_deepy_pack_{num:03d}.json", pack)

        # 3. Batch prompts 라인 생성
        batch_lines.append(f"### [Shot {num:03d}] (Estimated {s.get('duration', 5.875)}s)")
        batch_lines.append(f"**Prompt:** `{pos}`")
        batch_lines.append(f"**Negative:** `{neg}`")
        batch_lines.append(f"**Copy-Ready command:** `{pack['copy_ready_prompt']}`")
        batch_lines.append("")

    # 4. Batch md 파일 저장
    pm.save_text("wangp_batch_prompts.md", "\n".join(batch_lines))
