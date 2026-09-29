"""자체 타이틀 바 — frameless 창의 상단.

드래그로 창 이동, 우측에 (선택적) ⚙ 설정 + 닫기 버튼.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class TitleBar(QWidget):
    """상단 30px 바 — 드래그 이동 + (선택) ⚙ + 닫기."""

    def __init__(self, parent: QWidget, theme: dict,
                 title: str = "프로젝트 보드",
                 on_settings: Callable[[], None] | None = None,
                 on_new_project: Callable[[], None] | None = None,
                 on_batch_add: Callable[[], None] | None = None):
        super().__init__(parent)
        self.parent_win = parent
        self.theme = theme
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(30)
        self.setStyleSheet(f"background: {theme['bg']};")

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 4, 0)
        h.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {theme['text']}; font-size: 10pt; font-weight: 600;"
        )
        h.addWidget(self.title_label)
        h.addStretch()

        if on_batch_add is not None:
            batch_btn = QPushButton("⧉")
            batch_btn.setFixedSize(24, 22)
            batch_btn.setCursor(Qt.PointingHandCursor)
            batch_btn.setToolTip("일괄 입력 — 여러 프로젝트에 할 일/발주 행 추가")
            batch_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme['subtext']};"
                f" border: none; font-size: 11pt; }}"
                f"QPushButton:hover {{ color: {theme['accent']}; }}"
            )
            batch_btn.clicked.connect(on_batch_add)
            h.addWidget(batch_btn)

        if on_new_project is not None:
            new_btn = QPushButton("⊕")
            new_btn.setFixedSize(24, 22)
            new_btn.setCursor(Qt.PointingHandCursor)
            new_btn.setToolTip("새 프로젝트 (템플릿 선택 가능)")
            new_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme['subtext']};"
                f" border: none; font-size: 12pt; }}"
                f"QPushButton:hover {{ color: {theme['accent']}; }}"
            )
            new_btn.clicked.connect(on_new_project)
            h.addWidget(new_btn)

        if on_settings is not None:
            settings_btn = QPushButton("⚙")
            settings_btn.setFixedSize(24, 22)
            settings_btn.setCursor(Qt.PointingHandCursor)
            settings_btn.setToolTip("설정")
            settings_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme['subtext']};"
                f" border: none; font-size: 11pt; }}"
                f"QPushButton:hover {{ color: {theme['accent']}; }}"
            )
            settings_btn.clicked.connect(on_settings)
            h.addWidget(settings_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 22)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme['subtext']};"
            f" border: none; font-size: 11pt; }}"
            f"QPushButton:hover {{ color: {theme['danger']}; }}"
        )
        close_btn.clicked.connect(parent.close)
        h.addWidget(close_btn)

    def set_title(self, text: str) -> None:
        """타이틀 텍스트 갱신 (편집창에서 프로젝트 이름 변경 시 사용)."""
        self.title_label.setText(text)

    # ------------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = (
                e.globalPosition().toPoint()
                - self.parent_win.frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self._drag_offset is not None:
            self.parent_win.move(
                e.globalPosition().toPoint() - self._drag_offset
            )
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        e.accept()
