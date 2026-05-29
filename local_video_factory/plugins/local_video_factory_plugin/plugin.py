import sys
import os
import gradio as gr
from shared.utils.plugins import WAN2GPPlugin

# 플러그인 로드 시 local_video_factory 패키지 경로를 sys.path에 추가하여
# core 및 skills 모듈을 정상적으로 임포트할 수 있도록 보장
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(plugin_dir))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core import config_loader, project_manager, llm_client
from skills import (
    script_parser_skill,
    shot_planner_skill,
    prompt_director_skill,
)

class LocalVideoFactoryPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Local Video Factory"
        self.version = "1.1.1"
        self.description = "대본을 분석하여 컷 분할 및 스타일 고정 프롬프트를 자동 생성하고 WanGP와 연결합니다."

    def setup_ui(self):
        # WanGP 메인 UI 컴포넌트 접근 요청
        self.request_component("prompt")          # 긍정 프롬프트 텍스트박스
        self.request_component("negative_prompt") # 부정 프롬프트 텍스트박스
        self.request_global("server_config")      # WanGP 서버 설정

        # 플러그인 메인 탭 등록
        self.add_tab(
            tab_id="local_video_factory_tab",
            label="🎬 Local Video Factory",
            component_constructor=self.create_plugin_ui,
            position=3
        )

    def create_plugin_ui(self):
        with gr.Blocks() as demo:
            gr.Markdown("### 🎬 Local Video Factory (WanGP Plugin MVP)")
            gr.Markdown("대본을 입력하면 AI가 장면을 6초 이하 컷으로 나누고, 고정 스타일이 적용된 프롬프트를 생성해 WanGP로 원클릭 주입합니다.")
            
            with gr.Row():
                with gr.Column(scale=3):
                    title_in = gr.Textbox(label="프로젝트 제목", placeholder="예: 무지개 아래 모찌")
                    script_in = gr.Textbox(
                        label="대본 / 아이디어",
                        placeholder="대본을 입력하거나 동영상 아이디어를 한글로 적어주세요.",
                        lines=8
                    )
                with gr.Column(scale=2):
                    mode_in = gr.Radio(
                        ["감성 쇼츠", "제품 CF", "정보 전달 영상", "모찌/동물 스토리", "시니어 정보"],
                        value="감성 쇼츠",
                        label="콘텐츠 목적"
                    )
                    
                    visual_style_in = gr.Radio(
                        [
                            "콘텐츠 목적 자동", "3D 애니 필름", "클레이 애니메이션", "로파이 3D 피규어",
                            "스틱맨 노트북 낙서", "ASMR 시네마틱", "네오 클로저 브이로그", "레트로 8비트",
                            "사이버펑크 네온", "미니멀 뷰티 CF", "브이로그 일러스트 셀프", "와비사비 재팬 리얼"
                        ],
                        value="콘텐츠 목적 자동",
                        label="비주얼 스타일"
                    )
                    
                    char_lock_in = gr.Textbox(
                        label="캐릭터/브랜드 잠금",
                        placeholder="예: Mochi, cream-colored long-haired Chihuahua"
                    )

            analyze_btn = gr.Button("🎬 분석하고 컷 만들기", variant="primary", size="lg")
            status_out = gr.Markdown()

            # 컷 정보 저장용 State
            shots_state = gr.State([])

            # 안정적이고 직관적인 드롭다운 기반 컷 선택 UI (gr.render 버그 회피)
            with gr.Group():
                gr.Markdown("#### 🎞️ 생성된 컷 프롬프트 선택 및 주입")
                with gr.Row():
                    select_cut_dd = gr.Dropdown(
                        label="선택된 컷",
                        choices=[],
                        interactive=True,
                        scale=3
                    )
                    inject_btn = gr.Button("🎯 이 컷을 WanGP 프롬프트에 주입", variant="secondary", scale=1)
                
                with gr.Row():
                    prompt_preview = gr.Textbox(label="Positive Prompt", lines=4, interactive=False, scale=3)
                    neg_preview = gr.Textbox(label="Negative Prompt", lines=2, interactive=False, scale=2)

            # 컷 선택 변경 이벤트 정의
            def on_cut_select(selected_label, shots):
                if not selected_label or not shots:
                    return "", ""
                try:
                    # "Cut 001 - ..." 포맷에서 번호 추출
                    num_str = selected_label.split(" - ")[0].replace("Cut ", "")
                    num = int(num_str)
                    shot = next((s for s in shots if s["shot_number"] == num), None)
                    if shot:
                        return shot.get("ltx_prompt", ""), shot.get("ltx_negative_prompt", "")
                except Exception:
                    pass
                return "", ""

            select_cut_dd.change(
                fn=on_cut_select,
                inputs=[select_cut_dd, shots_state],
                outputs=[prompt_preview, neg_preview]
            )

            # 주입 이벤트 정의 (Gradio 텍스트상자의 현재 값을 WanGP 메인 탭에 덮어씀)
            inject_btn.click(
                fn=lambda p, n: (p, n),
                inputs=[prompt_preview, neg_preview],
                outputs=[self.prompt, self.negative_prompt]
            )

            # 분석 완료 콜백
            def on_analyze_done(status, shots):
                if not shots:
                    return status, gr.update(choices=[], value=None), []
                choices = [f"Cut {s['shot_number']:03d} - {s.get('korean_description', '')[:30]}" for s in shots]
                return status, gr.update(choices=choices, value=choices[0]), shots

            # 분석 실행 이벤트 체인
            analyze_btn.click(
                fn=self.plugin_analyze,
                inputs=[title_in, script_in, mode_in, visual_style_in, char_lock_in],
                outputs=[status_out, shots_state]
            ).then(
                fn=on_analyze_done,
                inputs=[status_out, shots_state],
                outputs=[status_out, select_cut_dd, shots_state]
            )

        return demo

    def plugin_analyze(self, title, script, mode_label, visual_style_label, char_lock):
        if not (script or "").strip():
            return "### ⚠️ 대본을 입력해 주세요.", []
        if not (title or "").strip():
            title = "제목 없는 영상"

        try:
            cfg = config_loader.load_config()
        except Exception as e:
            return f"### ⚠️ 설정을 로드하지 못했습니다. (에러: {e})", []

        # Ollama 서버 상태 및 모델 확인
        server_ok, server_msg = llm_client.check_server(cfg)
        if not server_ok:
            return f"### ⚠️ Ollama 서버에 연결할 수 없습니다.\n{server_msg}", []
        model_ok, model_msg, _ = llm_client.ensure_model(cfg)
        if not model_ok:
            return f"### ⚠️ 설정된 LLM 모델을 찾을 수 없습니다.\n{model_msg}", []

        # 목적 및 스타일 매핑
        from app_gradio import MODE_MAP, VISUAL_STYLE_MAP
        mode = MODE_MAP.get(mode_label, "emotional")
        visual_style = VISUAL_STYLE_MAP.get(visual_style_label, "")
        effective_style = visual_style or mode

        try:
            # 임시 프로젝트 생성 (목표 길이는 자동/0)
            pm = project_manager.create_project(
                cfg["project_root"], title,
                input_mode=mode, style_preset=effective_style,
                visual_style_preset=effective_style,
                char_lock_prompt=(char_lock or "").strip(),
                target_duration=0, cfg=cfg
            )
            pm.save_text("script_original.txt", script.strip())
            pm.save_text("idea.txt", script.strip())
            project = pm.load_json("project.json")

            # 1단계: 대본 분석
            pm.update_status("parsing_script")
            segments = script_parser_skill.parse_script(cfg, pm, project, script.strip())
            pm.update_status("script_parsed")

            # 2단계: 컷 분해
            pm.update_status("planning_shots")
            shots = shot_planner_skill.plan_shots(cfg, pm, project, segments)
            n = len(shots["shots"])
            pm.update_status("shots_ready", total_shots=n)

            # 3단계: 프롬프트 생성 및 스타일/캐릭터 락 후처리
            pm.update_status("generating_prompts", total_shots=n)
            prompt_director_skill.generate_prompts(cfg, pm, project, shots)
            pm.update_status("prompts_ready", total_shots=n)

            # 최종 결과 로드
            shots_final = pm.load_json("shots.json")["shots"]
            
            return f"### 🎉 컷 {len(shots_final)}개 생성 및 프롬프트 준비 완료!\n아래 선택 상자에서 컷을 골라 **주입** 버튼을 누르시면 됩니다.", shots_final

        except llm_client.LLMError as e:
            return f"### ⚠️ LLM 생성 도중 에러 발생: {e.message}", []
        except Exception as e:
            return f"### ⚠️ 예기치 못한 에러 발생: {e}", []
