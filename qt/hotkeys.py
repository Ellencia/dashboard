"""전역 단축키 — `hotkey.GlobalHotkey` (Win32 RegisterHotKey) 를 Qt 시그널로 래핑.

`GlobalHotkey` 의 콜백은 별도 스레드에서 호출되므로 GUI 조작 불가.
PySide6 `Signal` 로 main thread 로 안전하게 전달.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from hotkey import GlobalHotkey


class HotkeyManager(QObject):
    """위젯이 사용하는 두 단축키(접기·숨기기) 관리."""

    collapse_pressed = Signal()
    hide_pressed = Signal()

    def __init__(self, cfg: dict, parent: QObject | None = None):
        super().__init__(parent)
        wcfg = cfg.get("widget", {})
        # 시그널 emit 만 — connected slot 은 main thread 에서 실행됨
        self._collapse = GlobalHotkey(
            wcfg.get("collapse_hotkey", ""),
            lambda: self.collapse_pressed.emit(),
        )
        self._hide = GlobalHotkey(
            wcfg.get("hide_hotkey", ""),
            lambda: self.hide_pressed.emit(),
        )
        self._collapse.start()
        self._hide.start()

    def stop(self) -> None:
        """앱 종료 시 호출 — RegisterHotKey 해제 + 스레드 종료."""
        self._collapse.stop()
        self._hide.stop()

    def reload(self, cfg: dict) -> None:
        """설정 변경 시 — 기존 단축키 해제 후 새 설정으로 다시 등록."""
        self.stop()
        wcfg = cfg.get("widget", {})
        self._collapse = GlobalHotkey(
            wcfg.get("collapse_hotkey", ""),
            lambda: self.collapse_pressed.emit(),
        )
        self._hide = GlobalHotkey(
            wcfg.get("hide_hotkey", ""),
            lambda: self.hide_pressed.emit(),
        )
        self._collapse.start()
        self._hide.start()
