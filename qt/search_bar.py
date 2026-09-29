"""검색 바 — Ctrl+F 로 토글, 200ms 디바운스로 카드 필터.

쿼리는 프로젝트 이름·메모·할 일 텍스트 모두에 대해 부분 일치.
매칭 없는 카드는 숨김 (Phase 3 단순 모드 — 통합 '전체 할 일' 영역은 phase 7).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from qt.theme import input_qss


class SearchBar(QWidget):
    """🔍 + 입력칸 + 닫기. 처음엔 숨김 상태."""

    def __init__(self, theme: dict, on_change: Callable[[], None]):
        super().__init__()
        self.theme = theme
        self.on_change = on_change
        self._query = ""

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 2, 12, 4)
        h.setSpacing(6)

        icon = QLabel("🔍")
        icon.setStyleSheet(f"color: {theme['subtext']}; font-size: 10pt;")
        h.addWidget(icon)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("프로젝트/할 일 검색 — Esc 로 닫기")
        self.entry.setStyleSheet(input_qss(theme))
        self.entry.textChanged.connect(self._on_text_changed)
        h.addWidget(self.entry, 1)

        # 200ms 디바운스
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)

        self.hide()

    # ------------------------------------------------------------------
    def query(self) -> str:
        return self._query

    def toggle(self) -> None:
        if self.isVisible():
            self.close_bar()
        else:
            self.show()
            self.entry.setFocus()
            self.entry.selectAll()

    def close_bar(self) -> None:
        had_query = bool(self._query)
        self.entry.blockSignals(True)
        self.entry.clear()
        self.entry.blockSignals(False)
        self._query = ""
        self.hide()
        if had_query:
            self.on_change()

    def _on_text_changed(self, _text: str) -> None:
        self._timer.start(200)

    def _fire(self) -> None:
        new = self.entry.text().strip().lower()
        if new != self._query:
            self._query = new
            self.on_change()
