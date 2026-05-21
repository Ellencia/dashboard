"""프로젝트 대시보드 진입점.

config.json의 display_mode 값에 따라 표시 방식을 고름.
"widget"(항상 위 위젯 창)과 "tray"(트레이 아이콘)가 구현돼 있고,
"wallpaper"(바탕화면 배경 합성)는 추후 추가 예정.

실행:
    python main.py        # 오류 메시지를 보고 싶을 때
    pythonw main.py       # 콘솔 창 없이 조용히 실행 (run.bat이 이 방식)
"""
from __future__ import annotations

import sys
import traceback

from core import load_config


def main() -> None:
    cfg = load_config()
    mode = cfg.get("display_mode", "widget")

    if mode == "widget":
        from widget import run_widget
        run_widget()
    elif mode == "tray":
        try:
            from tray import run_tray
        except ImportError as e:
            # pystray/pillow 미설치 시 위젯 모드로 대체
            print("트레이 모드에는 pystray·pillow가 필요함: "
                  f"pip install pystray pillow\n({e})")
            from widget import run_widget
            run_widget()
        else:
            run_tray()
    elif mode == "wallpaper":
        # 아직 미구현 — 위젯 모드로 대체 실행
        print("'wallpaper' 모드는 아직 준비 중임. 위젯 모드로 실행함.")
        from widget import run_widget
        run_widget()
    else:
        print(f"알 수 없는 display_mode: {mode!r}  (widget / tray / wallpaper 중 하나)")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # pythonw로 실행하면 콘솔이 없어 오류가 안 보이므로 파일로도 남김
        traceback.print_exc()
        from core import BASE_DIR
        (BASE_DIR / "error.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        sys.exit(1)
