"""wangp_queue: 컷 프롬프트로 WanGP 'Load Queue'용 큐 파일을 만든다.

문서: WanGP 자동 API 연동은 후순위. gradio_client 완전 자동 호출은
WanGP가 api_name 없이 큐+gr.State 기반이라 취약하다. 대신 WanGP의
Save/Load Queue 기능(queue.zip / queue.json)을 활용한다.

전략(가장 안전):
- '검증된 템플릿 task' 하나를 그대로 복제하고, 컷마다 prompt/negative/seed/id만 바꾼다.
- 모델/해상도/프레임/스텝 등 생성 파라미터는 템플릿 값을 유지 → 반드시 로드·생성되도록.

큐 포맷(wgp.py _save_queue_to_zip 기준):
  queue.zip 안에 queue.json = [{"id": <int>, "params": {...}}]
  텍스트→비디오는 첨부 이미지가 없어 params만 있으면 된다.

사용 흐름:
  1) 이 함수로 <project>/wangp_queue.zip 생성
  2) 사용자가 WanGP에서 'Load Queue'로 불러오고 'Generate'
  3) Phase 4 폴더 감시가 완성 mp4를 컷에 자동 연결
"""
from __future__ import annotations

import copy
import json
import os
import zipfile
from typing import Any, Dict, List, Optional, Tuple


class QueueTemplateError(Exception):
    """큐 템플릿을 찾거나 읽지 못했을 때. message는 사용자용 쉬운 문장."""


def _read_template_data(path: str) -> Any:
    """queue.zip(안의 queue.json) / queue.json / 단일 settings.json 을 읽어 raw 반환."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            with zf.open("queue.json") as f:
                return json.loads(f.read().decode("utf-8"))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_to_task(data: Any) -> Dict[str, Any]:
    """다양한 형태를 {'id':.., 'params':{...}} task 하나로 정규화.

    허용:
      - [{'id','params':{...}}, ...]  (queue.json / Save Queue 결과)
      - [{...params...}, ...]          (params 딕셔너리 리스트)
      - {'params': {...}}              (단일 task)
      - {...params...}                 (단일 settings.json — WanGP settings/*.json)
    """
    if isinstance(data, list):
        if not data:
            raise QueueTemplateError("큐 템플릿이 비어 있어요.")
        data = data[0]
    if not isinstance(data, dict):
        raise QueueTemplateError("큐 템플릿 형식을 알 수 없어요.")

    if "params" in data and isinstance(data["params"], dict):
        params = data["params"]
    else:
        # 단일 settings 딕셔너리로 간주 (model_type/prompt 등이 최상위에 있음)
        params = data
    if "model_type" not in params:
        raise QueueTemplateError(
            "큐 템플릿에 model_type이 없어요. WanGP에서 'Save Queue'로 저장한 파일이나 "
            "settings/*.json을 지정해 주세요."
        )
    return {"id": 1, "params": params}


def _find_template_path(cfg: Dict[str, Any]) -> str:
    """복제할 템플릿 경로 결정: config 지정 > 앱 폴더의 small_moments_queue/queue.json."""
    configured = (cfg.get("wan_gp_queue_template") or "").strip()
    candidates = []
    if configured:
        candidates.append(configured)
    app = cfg.get("wan_gp_path", "")
    if app:
        candidates.append(os.path.join(app, "small_moments_queue", "queue.json"))
        candidates.append(os.path.join(app, "queue.zip"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise QueueTemplateError(
        "WanGP 큐 템플릿을 찾지 못했어요.\n"
        "  WanGP에서 영상 한 개를 만든 뒤 'Save Queue'로 저장한 파일 경로를\n"
        "  config.yaml의 wan_gp_queue_template에 넣어주세요."
    )


def load_template_task(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """검증된 template task를 반환. params 포함. (queue.zip/queue.json/settings.json 허용)"""
    path = _find_template_path(cfg)
    return _normalize_to_task(_read_template_data(path))


def build_queue(cfg: Dict[str, Any], pm, project: Dict[str, Any],
                shots_data: Dict[str, Any], *, only_shots: Optional[List[int]] = None
                ) -> Tuple[str, int]:
    """컷 프롬프트로 <project>/wangp_queue.zip 생성. (경로, 컷수) 반환."""
    template = load_template_task(cfg)
    base_params = template["params"]

    shots = shots_data["shots"]
    if only_shots is not None:
        shots = [s for s in shots if s["shot_number"] in only_shots]
    if not shots:
        raise QueueTemplateError("큐에 넣을 컷이 없어요.")

    queue: List[Dict[str, Any]] = []
    for i, shot in enumerate(shots, start=1):
        params = copy.deepcopy(base_params)
        params["prompt"] = (shot.get("english_video_prompt") or "").strip()
        # negative는 컷 값이 있으면 사용, 없으면 템플릿 값 유지
        neg = (shot.get("negative_prompt") or "").strip()
        if neg:
            params["negative_prompt"] = neg
        params["seed"] = -1  # 매번 랜덤
        queue.append({"id": i, "params": params})

    # queue.json 저장(전문가용으로 프로젝트 폴더에도 남김) + zip
    pm.save_json("wangp_queue.json", queue)
    zip_path = pm.path("wangp_queue.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("queue.json", json.dumps(queue, ensure_ascii=False, indent=4))

    return zip_path, len(queue)
