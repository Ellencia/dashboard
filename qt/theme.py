"""Tokyo-Night 다크 톤 + Qt StyleSheet(QSS) 모음.

테마 색은 dict 로 모으고, 스타일은 함수로 빌드 — 색 값이 한 곳에 모임.
나중에 라이트 테마 지원하려면 `dark()` 같은 selector 만 더 만들면 됨.
"""
from __future__ import annotations

import re
import zlib


# 할 일 텍스트에서 #태그 부분(앞 공백 포함)을 떼는 정규식
TAG_STRIP_RE = re.compile(r"\s*#\w+")

# 같은 태그는 항상 같은 색이 되도록 안정 해시(zlib.crc32)로 팔레트에서 선택
_TAG_PALETTE = [
    "#7aa2f7", "#9ece6a", "#e0af68", "#f7768e",
    "#bb9af7", "#7dcfff", "#ff9e64", "#73daca",
]


def tag_color(tag: str, custom_map: dict | None = None) -> str:
    """태그 → hex 색. custom_map 에 있으면 그것 우선, 없으면 안정 해시 팔레트."""
    if custom_map and tag in custom_map and custom_map[tag]:
        return custom_map[tag]
    idx = zlib.crc32(tag.encode("utf-8")) % len(_TAG_PALETTE)
    return _TAG_PALETTE[idx]


# Tokyo-Night 계열 — tkinter 위젯과 톤 맞춤
DARK = {
    "bg": "#1a1b26",
    "bg_alt": "#24283b",
    "card": "#2e3247",
    "card_hover": "#363b54",
    "inset": "#3a3f5a",   # 카드 안에 박히는 위젯(진행률 바, 배지) — 카드보다 살짝 밝게
    "text": "#c0caf5",
    "subtext": "#7aa2f7",
    "muted": "#565f89",
    "accent": "#bb9af7",
    "accent2": "#7dcfff",
    "border": "#414868",
    "ok": "#9ece6a",
    "warn": "#e0af68",
    "danger": "#f7768e",
}


def app_qss(t: dict) -> str:
    """앱 전체에 적용할 기본 QSS — 배경, 스크롤바, 툴팁."""
    return f"""
QWidget {{
    background: {t['bg']};
    color: {t['text']};
    font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
}}
QToolTip {{
    background: {t['card']};
    color: {t['text']};
    border: 1px solid {t['border']};
    padding: 4px 6px;
}}
QScrollBar:vertical {{
    background: {t['bg']};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['subtext']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: {t['bg']};
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border']};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""


def input_qss(t: dict) -> str:
    """입력칸(QLineEdit) — 카드 톤 + 미세한 border + 포커스 시 강조."""
    return f"""
QLineEdit {{
    background: {t['card']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {t['accent']};
    selection-color: {t['bg']};
}}
QLineEdit:focus {{
    border: 1px solid {t['accent']};
}}
"""


def menu_qss(t: dict) -> str:
    """우클릭 팝업 메뉴(QMenu) — 다크 톤에 맞춤."""
    return f"""
QMenu {{
    background: {t['card']};
    color: {t['text']};
    border: 1px solid {t['border']};
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 18px 5px 12px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background: {t['accent']};
    color: {t['bg']};
}}
QMenu::separator {{
    height: 1px;
    background: {t['border']};
    margin: 4px 8px;
}}
"""


def card_qss(t: dict) -> str:
    """프로젝트 카드용 — QFrame#card 셀렉터.

    카드 안의 자식 QLabel/QWidget 은 default 로 transparent 가 되도록 cascade.
    명시적 background 가 있는 위젯(마감 배지 등)은 inline styleSheet 가 우선.
    """
    return f"""
QFrame#card {{
    background: {t['card']};
    border-radius: 8px;
}}
QFrame#card:hover {{
    background: {t['card_hover']};
}}
QFrame#card QLabel {{
    background: transparent;
}}
QFrame#card > QWidget {{
    background: transparent;
}}
QProgressBar {{
    background: {t['inset']};
    border-radius: 3px;
    border: none;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {t['accent']};
    border-radius: 3px;
}}
"""
