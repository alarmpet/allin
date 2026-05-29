"""LLM이 만든 JSON을 안전하게 파싱/복구/검증한다.

문서 08: "AI가 만든 컷 데이터가 조금 깨졌어요. 자동으로 고쳐볼게요."
- 코드블록(```json) 제거
- 흔한 깨짐(앞뒤 잡텍스트, 끝쉼표) 자동 복구
- 필수 필드 검사 + 기본값 채우기
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


class JSONRepairError(Exception):
    """복구를 시도했지만 끝내 JSON으로 읽지 못했을 때."""


def strip_code_fences(text: str) -> str:
    """```json ... ``` 또는 ``` ... ``` 코드블록을 벗겨낸다."""
    t = text.strip()
    if t.startswith("```"):
        # 첫 줄(```json 등) 제거
        first_newline = t.find("\n")
        if first_newline != -1:
            t = t[first_newline + 1:]
        # 끝 ``` 제거
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _extract_balanced(text: str) -> str | None:
    """문자열 안에서 첫 번째 균형 잡힌 {...} 또는 [...] 블록을 잘라낸다.

    LLM이 JSON 앞뒤에 설명을 붙이는 경우를 대비한 보루.
    """
    start = None
    opener = closer = ""
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            closer = "}" if ch == "{" else "]"
            break
    if start is None:
        return None

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def loads_with_repair(raw: str) -> Any:
    """가능한 모든 수단으로 JSON을 읽어낸다. 실패하면 JSONRepairError."""
    if raw is None or not str(raw).strip():
        raise JSONRepairError("AI 응답이 비어 있어요.")

    candidates: List[str] = []
    stripped = strip_code_fences(str(raw))
    candidates.append(stripped)

    extracted = _extract_balanced(stripped)
    if extracted:
        candidates.append(extracted)

    # 끝쉼표 제거 버전도 시도
    for c in list(candidates):
        candidates.append(_remove_trailing_commas(c))

    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue

    raise JSONRepairError(
        "AI가 만든 데이터를 읽지 못했어요. 다시 생성하면 대부분 해결돼요."
    )


# ── 스키마 검증 ────────────────────────────────────────────────

def validate_segments(data: Any) -> Dict[str, Any]:
    """script_segments.json 형태로 정규화. 누락 필드는 기본값으로 채운다."""
    if isinstance(data, list):
        data = {"segments": data}
    if not isinstance(data, dict):
        raise JSONRepairError("대본 분석 결과 형식이 올바르지 않아요.")

    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise JSONRepairError("대본에서 문장을 하나도 추출하지 못했어요.")

    norm: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            continue
        sentence = str(seg.get("sentence", "")).strip()
        if not sentence:
            continue
        kw = seg.get("keywords", [])
        if isinstance(kw, str):
            kw = [k.strip() for k in kw.split(",") if k.strip()]
        elif not isinstance(kw, list):
            kw = []
        norm.append({
            "segment_id": int(seg.get("segment_id", i)),
            "sentence": sentence,
            "meaning": str(seg.get("meaning", "")).strip(),
            "emotion": str(seg.get("emotion", "neutral")).strip() or "neutral",
            "keywords": [str(k).strip() for k in kw if str(k).strip()],
            "visual_potential": str(seg.get("visual_potential", "medium")).strip() or "medium",
            "tts_text": str(seg.get("tts_text", sentence)).strip() or sentence,
        })

    if not norm:
        raise JSONRepairError("유효한 문장이 없어요. 대본을 다시 확인해 주세요.")

    data["segments"] = norm
    return data


REQUIRED_SHOT_FIELDS = (
    "shot_number", "duration", "korean_description",
    "english_video_prompt", "negative_prompt", "tts_text", "status",
)


def validate_shots(data: Any) -> Dict[str, Any]:
    """shots.json 검증. 필수 필드 누락 시 기본값으로 보정."""
    if isinstance(data, list):
        data = {"shots": data}
    if not isinstance(data, dict):
        raise JSONRepairError("컷 데이터 형식이 올바르지 않아요.")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        raise JSONRepairError("컷을 하나도 만들지 못했어요.")

    for i, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise JSONRepairError(f"{i}번째 컷 데이터가 비어 있어요.")
        shot.setdefault("shot_number", i)
        shot.setdefault("duration", 0.0)
        shot.setdefault("korean_description", "")
        shot.setdefault("english_video_prompt", "")
        shot.setdefault("negative_prompt", "")
        shot.setdefault("tts_text", "")
        shot.setdefault("status", "planned")
    return data
