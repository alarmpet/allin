# Local Video Factory

완전 로컬 영상 자동화 프로그램. 대본을 넣으면 AI가 6초 이하 컷으로 나누고,
컷별 영상 프롬프트·나레이션·자막·파일 상태를 관리한 뒤
WanGP/LTX2 + Supertonic3 + ffmpeg로 최종 영상을 조립합니다.

- LLM: **Ollama + Qwen3.5 9B** (외부 유료 API 미사용)
- 영상 생성: Pinokio WanGP/LTX2 (초기에는 반자동 복붙 + 폴더 감시)
- TTS: Supertonic3 / 후처리: ffmpeg

## 현재 단계: Phase 1~8 완료 — 전체 기능 동작

- Phase 1: 대본 → `script_segments.json` → `shots.json` → `prompt_XXX.txt` (CLI)
- Phase 2: 브라우저에서 대본 입력 → 컷 카드 확인 → 프롬프트 복사 (Gradio)
- Phase 3: 컷별 나레이션(Supertonic3) → `audio/audio_XXX.wav`, `timeline.json`, `captions.srt`
- Phase 4: WanGP output 폴더 감시 → 새 mp4 자동 감지 → `outputs/shot_XXX.mp4` 연결
- Phase 5: 컷 영상 + 나레이션 + 자막 → 9:16 `outputs/final.mp4` (ffmpeg)

### 브라우저 UI 실행
```powershell
python app_gradio.py     # http://127.0.0.1:7860
```
0. "시작" 탭: 최근 프로젝트를 골라 **이전 작업 이어하기**, 또는 새 영상 만들기
1. "만들기" 탭: 대본 입력 → **분석하고 컷 만들기**
2. "컷 보드" 탭: 컷 카드 확인·프롬프트 복사 (전문가 모드로 shots.json 보기)
3. "음성/자막" 탭: 목소리 선택 → **나레이션 만들기** → 컷별 미리듣기 + 자막(SRT)
4. "영상 생성" 탭: 컷 프롬프트 복사 → WanGP에서 Generate → **감시 시작**하면 새 mp4를 자동으로 컷에 연결 (또는 직접 파일 선택)
   - ⚡ **한 번에 만들기**: 전 컷을 담은 WanGP **큐 파일(zip)**을 만들어, WanGP의 *Load Queue → Generate*로 배치 생성 (복붙 불필요)
5. "최종 출력" 탭: 현황 확인 → **최종 영상 만들기** → 9:16 `final.mp4` 미리보기 → 결과 폴더 열기
6. "진단/설정" 탭: 전체 진단, 모델 자동 선택, 경로/영상 설정 저장, 전문가 모드(JSON·로그 보기)

### WanGP output 폴더
`config.yaml`의 `wan_gp_output_path` = `C:/pinokio/api/wan.git/app/outputs`.
감시 시작 후 WanGP에서 영상을 만들면, 크기가 안정된 새 mp4를 순서대로 컷에 연결합니다.

### Supertonic3
`config.yaml`의 `supertonic_home` 경로 사용. HTTP 서버(포트 3093)가 켜져 있으면 우선,
없으면 venv CLI로 폴백. 목소리: 친화적 이름 → F1~F5/M1~M5 매핑.

### 설치
```powershell
cd C:\Users\petbl\allin\local_video_factory
pip install -r requirements.txt
```

### 환경 점검
```powershell
python app_cli.py check
```

### 대본 → 컷 + 프롬프트
```powershell
# 파일에서 대본 읽기
python app_cli.py make --title "비 오는 날 모찌" --mode mochi --duration 15 --script-file sample_script.txt

# 직접 입력
python app_cli.py make --title "테스트" --mode emotional --script "한 줄 아이디어를 영상으로"
```

생성물: `projects/YYYY-MM-DD_제목/` 안에 json + prompt txt.

### 모드(--mode)
`emotional`(감성), `product_cf`(제품 CF), `info`(정보), `mochi`(모찌/동물), `senior`(시니어)

## 폴더 구조
```
core/    설정/LLM/JSON검증/프로젝트 관리
skills/  대본분석 → 컷분해 → 프롬프트 생성
tools/   (Phase 3~5: watcher, ffmpeg)
prompts/ LLM 프롬프트·스타일 템플릿
projects/ 산출물
```

## WanGP 자동화 메모
- gradio_client 완전 자동 호출은 WanGP가 `api_name` 없이 큐+gr.State 기반이라 취약 → 채택 안 함.
- 대신 **큐 파일(queue.zip) 생성** 방식 채택: 검증된 템플릿 task를 복제해 컷별 prompt만 교체.
- 템플릿: `config.wan_gp_queue_template`(미지정 시 앱의 `small_moments_queue/queue.json`).
  모델/해상도/스텝은 템플릿 값을 그대로 사용(로드·생성 보장). 다른 설정을 쓰려면 WanGP에서
  원하는 설정으로 1개 만들고 *Save Queue* 한 파일을 템플릿으로 지정하세요.

## 다음 단계 (선택)
- Electron + FastAPI 데스크톱 앱
- shot_planner 튜닝(컷당 1문장 우선)으로 나레이션-영상 길이 싱크 개선
