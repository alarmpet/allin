"""subtitle_sync_skill: 컷별 나레이션 → captions.srt

문서 05:
- captions.srt 생성, 컷별 시작/종료 시간 계산
- UTF-8-SIG 저장으로 한글 자막 깨짐 방지
- 하단 자막 기준(스타일은 ffmpeg 단계에서 적용)

timeline.json의 start/end(used_duration 기반)를 사용해 나레이션과 자막을 맞춘다.
숏폼 스타일을 위해 한 글자/단어 단위로 자막을 쪼개어 가독성을 높인다.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _ts(seconds: float) -> str:
    """초 → SRT 타임코드 HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(pm, shots_data: Dict[str, Any], timeline: Dict[str, Any]) -> str:
    """captions.srt 작성. 자막 텍스트가 있는 컷만 포함. 저장 후 내용 문자열 반환."""
    shots: List[Dict[str, Any]] = shots_data["shots"]
    times = {e["shot_number"]: e for e in timeline.get("shots", [])}

    blocks: List[str] = []
    index = 1
    for shot in shots:
        num = shot["shot_number"]
        text = (shot.get("subtitle_ko") or shot.get("tts_text") or "").strip()
        if not text:
            continue
        entry = times.get(num)
        if entry:
            start, end = entry["start"], entry["end"]
        else:  # 타임라인에 없으면 안전한 기본값
            start, end = 0.0, 3.0

        duration = end - start

        # 숏폼 자막 가독성을 위해 문장을 15자 내외의 짧은 청크로 분할
        words = text.split()
        chunks = []
        current_chunk = []
        current_len = 0
        for w in words:
            if current_len + len(w) + (1 if current_chunk else 0) > 15:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [w]
                current_len = len(w)
            else:
                current_chunk.append(w)
                current_len += len(w) + (1 if current_chunk else 0)
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # 청크 길이 비율에 맞게 시간 배분
        total_chars = sum(len(c) for c in chunks)
        if total_chars > 0:
            elapsed = start
            for c in chunks:
                ratio = len(c) / total_chars
                chunk_dur = duration * ratio
                chunk_end = elapsed + chunk_dur
                blocks.append(f"{index}\n{_ts(elapsed)} --> {_ts(chunk_end)}\n{c}\n")
                index += 1
                elapsed = chunk_end
        else:
            blocks.append(f"{index}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
            index += 1

    srt = "\n".join(blocks)
    # UTF-8-SIG(BOM)로 저장 → Windows 플레이어/ffmpeg 한글 깨짐 방지
    pm.save_text("captions.srt", srt, bom=True)
    return srt
