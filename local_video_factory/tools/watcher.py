"""watcher: WanGP output 폴더를 감시해 새 mp4를 프로젝트로 가져온다.

문서 05/08:
- output 폴더 감시, 새 mp4 감지
- 파일 크기 변화가 멈추면(=쓰기 종료) 완료로 판단
- 프로젝트 outputs 폴더로 복사 후 shot_001.mp4 형식으로 이름 정리
- 자동 감지 실패 시 직접 파일 선택과 연동

Gradio Timer로 주기 호출하기 쉽도록 '상태 없는 helper'로 설계했다.
파일이 아직 쓰이는 중인지는 mtime이 min_age초 이상 지났는지로 판단(폴링 친화적).
"""
from __future__ import annotations

import glob
import os
import shutil
import time
from typing import Any, Dict, List, Optional


def list_mp4s(folder: str) -> List[str]:
    """폴더 최상위의 mp4 경로 목록 (하위 폴더의 과거 파일은 제외)."""
    if not folder or not os.path.isdir(folder):
        return []
    folder = os.path.abspath(folder)
    return [os.path.abspath(p) for p in glob.glob(os.path.join(folder, "*.mp4")) if os.path.isfile(p)]


def snapshot(folder: str) -> List[str]:
    """감시 시작 시점에 이미 존재하던 파일 목록(기준선). 이후 새 파일만 가져온다."""
    return sorted(list_mp4s(folder))


def find_new_stable(folder: str, known: List[str], *, min_age: float = 2.0) -> List[str]:
    """known(이미 본 파일)에 없고, 최근 min_age초 동안 변경이 없어
    '생성 완료'로 판단되는 새 mp4들을 오래된 순으로 반환."""
    known_set = set(known or [])
    now = time.time()
    fresh: List[tuple] = []
    for p in list_mp4s(folder):
        if p in known_set:
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_size <= 0:
            continue
        if now - st.st_mtime < min_age:   # 아직 쓰는 중일 수 있음 → 다음 주기에
            continue
        fresh.append((p, st.st_mtime))
    fresh.sort(key=lambda x: x[1])
    return [p for p, _ in fresh]


def import_video(src_path: str, pm, shot_number: int) -> str:
    """src_path 영상을 프로젝트 outputs/shot_NNN.mp4로 복사. 상대경로 반환."""
    if not src_path or not os.path.isfile(src_path):
        raise FileNotFoundError(f"영상 파일을 찾지 못했어요: {src_path}")
    rel = f"outputs/shot_{shot_number:03d}.mp4"
    dst = pm.path(rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src_path, dst)
    return rel


def assign_to_shot(pm, shots_data: Dict[str, Any], shot_number: int, src_path: str) -> Dict[str, Any]:
    """영상을 특정 컷에 연결하고 shots.json을 갱신한다."""
    rel = import_video(src_path, pm, shot_number)
    for shot in shots_data["shots"]:
        if shot["shot_number"] == shot_number:
            shot["video_file"] = rel
            shot["status"] = "video_ready"
            break
    pm.save_json("shots.json", shots_data)
    return shots_data


def shots_missing_video(pm, shots_data: Dict[str, Any]) -> List[int]:
    """영상 파일이 실제로 존재하지 않는 컷 번호 목록."""
    missing = []
    for shot in shots_data["shots"]:
        vf = shot.get("video_file", "")
        if not vf or not os.path.isfile(pm.path(vf)):
            missing.append(shot["shot_number"])
    return missing


def next_missing_shot(pm, shots_data: Dict[str, Any], after: Optional[int] = None) -> Optional[int]:
    """다음으로 영상이 필요한 컷 번호. after가 주어지면 그 다음부터 찾는다."""
    missing = shots_missing_video(pm, shots_data)
    if not missing:
        return None
    if after is None:
        return missing[0]
    for n in missing:
        if n > after:
            return n
    return missing[0]


def open_folder(folder: str) -> bool:
    """탐색기로 폴더 열기 (로컬 전용). 성공 여부 반환."""
    try:
        if os.path.isdir(folder):
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows
            return True
    except Exception:  # noqa: BLE001
        pass
    return False
