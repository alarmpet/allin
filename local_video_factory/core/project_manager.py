"""프로젝트 폴더와 상태(project.json/status.json)를 관리한다.

문서 04/08 준수:
- projects/YYYY-MM-DD_project_name/ 구조 생성
- Windows에서 안전한 폴더명 (금지문자 제거)
- 프로젝트 폴더 밖은 절대 건드리지 않는다
- status.json으로 진행상태/이어하기 지원
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any, Dict, List, Optional

# 내부 상태값 → 사용자 표시 문구 (문서 04 표)
STATUS_MESSAGES: Dict[str, str] = {
    "idle": "준비 중",
    "script_loaded": "대본을 불러왔어요",
    "parsing_script": "대본을 분석하고 있어요",
    "script_parsed": "대본 분석이 끝났어요",
    "planning_shots": "장면을 나누고 있어요",
    "shots_ready": "컷 구성이 완료됐어요",
    "generating_prompts": "영상 프롬프트를 만들고 있어요",
    "prompts_ready": "프롬프트가 준비됐어요",
    "generating_tts": "나레이션을 만들고 있어요",
    "tts_ready": "나레이션이 준비됐어요",
    "waiting_for_wangp": "WanGP에서 영상을 만들어주세요",
    "watching_output_folder": "새 영상 파일을 찾고 있어요",
    "shot_video_ready": "컷 영상이 준비됐어요",
    "all_shots_ready": "모든 컷 영상이 준비됐어요",
    "merging_video_audio": "영상과 음성을 합치고 있어요",
    "adding_subtitles": "자막을 입히고 있어요",
    "final_ready": "최종 영상이 완성됐어요",
    "failed": "문제가 생겼어요. 해결 버튼을 눌러주세요",
}

# 사용자에게 보이는 단계(진행률 계산용)
STEP_ORDER = [
    "script_parsed", "shots_ready", "prompts_ready",
    "tts_ready", "all_shots_ready", "merging_video_audio", "final_ready",
]
TOTAL_STEPS = 7

_WINDOWS_FORBIDDEN = r'[<>:"/\\|?*\x00-\x1f]'
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def slugify(title: str) -> str:
    """프로젝트 제목 → Windows에서 안전한 폴더 슬러그."""
    title = (title or "").strip()
    if not title:
        return "untitled"
    # 금지 문자 제거, 공백류는 _ 로
    s = re.sub(_WINDOWS_FORBIDDEN, "", title)
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._ ")          # 끝의 점/공백은 Windows에서 문제
    s = s[:60] or "untitled"    # 경로 길이 방지
    if s.upper() in _RESERVED:
        s = f"{s}_project"
    return s


class ProjectManager:
    """하나의 프로젝트 폴더에 대한 입출력을 담당."""

    def __init__(self, root: str, project_id: str):
        self.root = os.path.abspath(root)
        self.project_id = project_id
        self.dir = os.path.join(self.root, project_id)

    # ── 경로 helper ──────────────────────────────────────────
    def path(self, *parts: str) -> str:
        p = os.path.abspath(os.path.join(self.dir, *parts))
        # 안전장치: 프로젝트 폴더 밖 경로 차단
        if os.path.commonpath([p, self.dir]) != self.dir:
            raise ValueError(f"프로젝트 폴더 밖 경로는 사용할 수 없어요: {p}")
        return p

    @property
    def audio_dir(self) -> str:
        return self.path("audio")

    @property
    def outputs_dir(self) -> str:
        return self.path("outputs")

    @property
    def logs_dir(self) -> str:
        return self.path("logs")

    # ── 생성/저장 ────────────────────────────────────────────
    def ensure_dirs(self) -> None:
        for d in (self.dir, self.audio_dir, self.outputs_dir, self.logs_dir):
            os.makedirs(d, exist_ok=True)

    def save_json(self, name: str, data: Any) -> str:
        target = self.path(name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return target

    def load_json(self, name: str) -> Any:
        with open(self.path(name), "r", encoding="utf-8") as f:
            return json.load(f)

    def save_text(self, name: str, text: str, *, bom: bool = False) -> str:
        target = self.path(name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        encoding = "utf-8-sig" if bom else "utf-8"
        with open(target, "w", encoding=encoding) as f:
            f.write(text)
        return target

    def exists(self, name: str) -> bool:
        return os.path.exists(self.path(name))

    # ── status.json ──────────────────────────────────────────
    def update_status(self, current_status: str, *, progress: Optional[float] = None,
                      current_shot: int = 0, total_shots: int = 0,
                      missing_items: Optional[Dict[str, List[int]]] = None,
                      last_error: Optional[str] = None) -> Dict[str, Any]:
        if progress is None:
            progress = self._progress_for(current_status)
        status = {
            "project_id": self.project_id,
            "current_status": current_status,
            "user_status_message": STATUS_MESSAGES.get(current_status, current_status),
            "progress": round(progress, 2),
            "current_step": self._step_for(current_status),
            "total_steps": TOTAL_STEPS,
            "current_shot": current_shot,
            "total_shots": total_shots,
            "missing_items": missing_items or {"videos": [], "audio": [], "subtitles": []},
            "last_error": last_error,
            "can_resume": current_status not in ("idle",),
            "updated_at": _now_iso(),
        }
        self.save_json("status.json", status)
        return status

    def _step_for(self, status: str) -> int:
        if status in STEP_ORDER:
            return STEP_ORDER.index(status) + 1
        return 0

    def _progress_for(self, status: str) -> float:
        if status == "final_ready":
            return 1.0
        if status in STEP_ORDER:
            return (STEP_ORDER.index(status) + 1) / TOTAL_STEPS
        return 0.0


# ── 모듈 레벨 helper ────────────────────────────────────────────

def _now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def create_project(root: str, title: str, *, input_mode: str, style_preset: str,
                   target_duration: int, cfg: Dict[str, Any]) -> ProjectManager:
    """새 프로젝트 폴더와 project.json/status.json을 만든다."""
    date = _dt.date.today().isoformat()
    slug = slugify(title)
    project_id = f"{date}_{slug}"

    # 같은 이름이 이미 있으면 뒤에 번호 붙이기 (덮어쓰기 방지)
    pm = ProjectManager(root, project_id)
    n = 2
    while os.path.exists(pm.dir):
        pm = ProjectManager(root, f"{project_id}_{n}")
        n += 1

    pm.ensure_dirs()

    now = _now_iso()
    project = {
        "project_id": pm.project_id,
        "project_title": title.strip() or "Untitled",
        "created_at": now,
        "updated_at": now,
        "input_mode": input_mode,
        "style_preset": style_preset,
        "target_duration": target_duration,
        "max_shot_duration": cfg["default_max_shot_seconds"],
        "fps": cfg["default_fps"],
        "frames_per_shot": cfg["default_frames_per_shot"],
        "resolution": cfg["test_resolution"],
        "final_aspect_ratio": cfg["final_aspect_ratio"],
    }
    pm.save_json("project.json", project)
    pm.update_status("idle")
    return pm


def list_projects(root: str) -> List[Dict[str, Any]]:
    """projects/ 안의 프로젝트 카드 정보 목록 (최신순)."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return []
    cards: List[Dict[str, Any]] = []
    for name in os.listdir(root):
        pdir = os.path.join(root, name)
        pj = os.path.join(pdir, "project.json")
        if not os.path.isfile(pj):
            continue
        try:
            with open(pj, "r", encoding="utf-8") as f:
                project = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        status = {}
        sj = os.path.join(pdir, "status.json")
        if os.path.isfile(sj):
            try:
                with open(sj, "r", encoding="utf-8") as f:
                    status = json.load(f)
            except Exception:  # noqa: BLE001
                pass
        cards.append({
            "project_id": name,
            "title": project.get("project_title", name),
            "created_at": project.get("created_at", ""),
            "target_duration": project.get("target_duration", 0),
            "progress": status.get("progress", 0.0),
            "status_message": status.get("user_status_message", "준비 중"),
            "has_final": os.path.isfile(os.path.join(pdir, "outputs", "final.mp4")),
        })
    cards.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return cards


def delete_project(root: str, project_id: str) -> bool:
    """프로젝트 폴더를 안전하게 삭제한다. 성공 여부 반환."""
    root = os.path.abspath(root)
    if not project_id or not os.path.isdir(root):
        return False
    # 프로젝트 폴더 경로 계산
    pdir = os.path.abspath(os.path.join(root, project_id))
    # 안전장치: 상위 폴더가 root인지 검증 (상위 폴더 이탈 방지)
    if os.path.dirname(pdir) != root:
        return False
    # project.json이 존재하는 유효한 프로젝트 폴더인지 확인 (아무 폴더나 삭제 방지)
    if not os.path.isfile(os.path.join(pdir, "project.json")):
        return False
    # 삭제 실행
    try:
        import shutil
        shutil.rmtree(pdir)
        return True
    except Exception:
        return False
