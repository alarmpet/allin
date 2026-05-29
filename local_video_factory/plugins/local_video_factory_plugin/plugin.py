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

import app_gradio

class LocalVideoFactoryPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Local Video Factory"
        self.version = "1.2.0"
        self.description = "대본 입력부터 분석, 컷 분할, 프롬프트 최적화, TTS 나레이션 생성, 영상 렌더링 및 최종 출력까지 로컬 비디오 팩토리의 모든 기능을 제공하며 WanGP와 연동합니다."

    def setup_ui(self):
        # WanGP 메인 UI 컴포넌트 접근 요청
        self.request_component("prompt")          # 긍정 프롬프트 텍스트박스
        self.request_component("negative_prompt") # 부정 프롬프트 텍스트박스
        self.request_global("server_config")      # WanGP 서버 설정

        # 플러그인 메인 탭 등록 (완전한 Gradio UI 연동)
        self.add_tab(
            tab_id="local_video_factory_tab",
            label="🎬 Local Video Factory",
            component_constructor=self.create_plugin_ui,
            position=3
        )

    def create_plugin_ui(self):
        # 로컬 비디오 팩토리 전체 UI를 생성하고 플러그인 인스턴스를 전달하여 WanGP 주입 기능 연동
        return app_gradio.build_ui(plugin_instance=self)
