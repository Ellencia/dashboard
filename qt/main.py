"""Qt 버전 진입점 — `python -m qt.main` 으로 실행.

dashboard 폴더에서 실행하면 `core`, `qt` 둘 다 import 가능.
"""
from __future__ import annotations

import sys
from pathlib import Path

# dashboard 폴더를 sys.path 에 추가 (어디서 실행하든 core import 되게)
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

import core
from qt.hotkeys import HotkeyManager
from qt.settings import SettingsDialog
from qt.theme import DARK
from qt.tray import DashboardTray
from qt.window import DashboardWindow


def main() -> None:
    # native crash(segfault) traceback 캡쳐 — PySide6 디버그용. dashboard 폴더의
    # crash.log 로 stderr 가 함께 redirect 되니 콘솔 없이 실행해도 흔적이 남음
    import faulthandler
    _log = open(_DASHBOARD_DIR / "crash.log", "a", encoding="utf-8",
                buffering=1)
    faulthandler.enable(file=_log, all_threads=True)

    def _excepthook(exctype, value, tb):
        import traceback as _tb
        _tb.print_exception(exctype, value, tb, file=_log)
        _tb.print_exception(exctype, value, tb)

    sys.excepthook = _excepthook

    # 단일 실행 보장 — 이미 다른 인스턴스(tk 또는 qt)가 떠 있으면 조용히 종료
    import singleton
    ipc = singleton.acquire()
    if ipc is None:
        return

    app = QApplication(sys.argv)
    app.setFont(QFont("Malgun Gothic", 9))
    # 트레이 모드에서 위젯 닫아도 앱이 종료 안 되게
    app.setQuitOnLastWindowClosed(False)

    cfg = core.load_config()
    win = DashboardWindow(cfg, DARK)

    # 글로벌 단축키 — Win32 RegisterHotKey 를 Qt Signal 로 래핑
    hotkeys = HotkeyManager(cfg)
    hotkeys.collapse_pressed.connect(win.toggle_body_collapse)
    hotkeys.hide_pressed.connect(win.toggle_window_visibility)
    win._hotkeys = hotkeys   # settings 저장 시 reload 호출용

    # 설정 변경 후 단축키 재등록까지 처리
    def apply_after_settings() -> None:
        win._apply_settings()
        hotkeys.reload(cfg)

    def open_settings() -> None:
        dlg = SettingsDialog(cfg, DARK, apply_after_settings, parent=win)
        dlg.exec()

    tray = DashboardTray(
        win, cfg, DARK,
        on_open_settings=open_settings,
        on_quit=app.quit,
    )
    tray.show()
    win._tray = tray

    # 앱 종료 시 단축키 unregister
    app.aboutToQuit.connect(hotkeys.stop)

    if cfg.get("display_mode", "widget") == "tray":
        # 트레이 모드 — 시작 시 창은 숨김 (트레이 클릭으로 띄움)
        win.hide()
        tray.refresh_label()
    else:
        win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
