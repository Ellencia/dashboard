"""프로젝트 대시보드 - 전역 단축키 (Windows 전용).

Win32 RegisterHotKey를 ctypes로 호출해 시스템 전역 단축키 한 개를 등록함.
별도 라이브러리가 필요 없고, 키보드 후킹이 아니라 OS가 제공하는 단축키
등록 방식이라 안전함(다른 키 입력을 가로채지 않음).

단축키 문자열 예: "ctrl+alt+d", "ctrl+shift+f9"
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

_user32 = ctypes.windll.user32

_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                   wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL

_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_MOD_NOREPEAT = 0x4000   # 키를 누르고 있어도 한 번만 발동
_HOTKEY_ID = 1

# 단축키 문자열의 수정키 이름 → RegisterHotKey 플래그
_MODIFIERS = {
    "ctrl": 0x0002, "control": 0x0002,
    "alt": 0x0001,
    "shift": 0x0004,
    "win": 0x0008,
}

# 자주 쓰는 특수키 이름 → 가상 키 코드(VK)
_SPECIAL_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "home": 0x24, "end": 0x23,
    "insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22,
}


def _key_to_vk(key: str) -> int | None:
    """키 이름 한 개 → 가상 키 코드. 못 알아보면 None."""
    if len(key) == 1:
        ch = key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)            # 알파벳·숫자는 VK가 ASCII 대문자와 같음
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)     # VK_F1 = 0x70
    return _SPECIAL_KEYS.get(key)


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'ctrl+alt+d' → (수정키 플래그, 가상키코드). 못 읽으면 None.

    수정키(ctrl/alt/shift/win)가 하나도 없으면 오작동 위험이 커서 거부함.
    """
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    mods = 0
    vk = None
    for p in parts:
        if p in _MODIFIERS:
            mods |= _MODIFIERS[p]
        elif vk is None:
            vk = _key_to_vk(p)
        else:
            return None               # 일반 키가 두 개 이상
    if vk is None or mods == 0:
        return None
    return mods, vk


class GlobalHotkey:
    """전역 단축키 한 개. 눌리면 callback을 호출함 (별도 스레드에서)."""

    def __init__(self, hotkey_text: str, callback) -> None:
        self._callback = callback
        self._parsed = parse_hotkey(hotkey_text) if hotkey_text else None
        self._thread: threading.Thread | None = None
        self._tid: int | None = None

    @property
    def valid(self) -> bool:
        """단축키 문자열을 해석할 수 있었는지."""
        return self._parsed is not None

    def start(self) -> None:
        """단축키 등록 시작 (해석 가능한 문자열일 때만)."""
        if self._parsed is None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        # WM_HOTKEY가 이 스레드의 메시지 큐로 오도록 hwnd=None으로 등록
        self._tid = threading.get_native_id()
        mods, vk = self._parsed
        if not _user32.RegisterHotKey(None, _HOTKEY_ID, mods | _MOD_NOREPEAT, vk):
            return   # 등록 실패 (이미 다른 앱이 쓰는 키 조합 등)
        msg = wintypes.MSG()
        try:
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_HOTKEY:
                    self._callback()
        finally:
            _user32.UnregisterHotKey(None, _HOTKEY_ID)

    def stop(self) -> None:
        """단축키 등록을 해제하고 스레드를 정리."""
        if self._tid is not None:
            _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
            self._tid = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
