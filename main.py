"""프로젝트 대시보드 진입점.

기본은 Qt(PySide6) 백엔드. config.json 의 `"ui": "tk"` 면 legacy tkinter
백엔드로 폴백 — widget.py/editor.py/tray.py 는 그대로 보존돼 있음.

실행:
    python main.py        # 오류 메시지를 보고 싶을 때
    pythonw main.py       # 콘솔 창 없이 (run.bat 이 이 방식)

Qt 백엔드를 직접 실행하려면:
    python -m qt.main
"""
from __future__ import annotations

import sys
import traceback

from core import load_config


def _run_qt() -> None:
    """PySide6 진입점 — qt 패키지의 main() 으로 위임 (singleton 도 거기서)."""
    from qt.main import main as qt_main
    qt_main()


def _run_tk_legacy() -> None:
    """tkinter 백엔드 — 옛 main.py 와 동일한 분기."""
    import singleton

    ipc = singleton.acquire()
    if ipc is None:
        print("대시보드가 이미 실행 중입니다 — 기존 창을 띄웠습니다.")
        return

    cfg = load_config()
    mode = cfg.get("display_mode", "widget")
    if mode == "tray":
        try:
            from tray import run_tray
        except ImportError as e:
            print("트레이 모드에는 pystray·pillow가 필요함: "
                  f"pip install pystray pillow\n({e})")
            from widget import run_widget
            run_widget(ipc)
        else:
            run_tray(ipc)
    else:
        from widget import run_widget
        run_widget(ipc)


def main() -> None:
    cfg = load_config()
    ui = cfg.get("ui", "qt")
    if ui == "tk":
        _run_tk_legacy()
    else:
        _run_qt()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        from core import BASE_DIR
        (BASE_DIR / "error.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        sys.exit(1)
