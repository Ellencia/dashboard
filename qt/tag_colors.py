"""태그 색 매핑 다이얼로그.

cfg.widget.tag_colors = {"발주": "#bb9af7", ...} 를 편집.
설정 안 된 태그는 해시 기반 자동 팔레트가 적용됨 (core 측).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qt.theme import app_qss, input_qss
from qt.titlebar import TitleBar


class TagColorsDialog(QDialog):
    """태그 → hex 색 매핑 편집."""

    def __init__(self, cfg: dict, theme: dict,
                 on_saved: Callable[[dict], None],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.theme = theme
        self.on_saved = on_saved
        self._rows: list[tuple[QLineEdit, QLineEdit, QPushButton]] = []

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme))
        self.resize(380, 460)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, theme, "태그 색"))

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        v.addWidget(self._label(
            "각 태그에 색을 지정. 비우면 해시 기반 자동 팔레트.",
            theme['muted'], 8,
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme['bg']}; border: none; }}"
        )
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        scroll.setWidget(self.rows_host)
        v.addWidget(scroll, 1)

        # 기존 매핑 로드
        for tag, color in (cfg.get("widget", {}).get("tag_colors") or {}).items():
            self._add_row(tag, color)

        # + 행 추가 버튼
        add_btn = QPushButton("+ 새 태그")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme['accent']};"
            f" border: none; font-size: 9pt; padding: 4px; text-align: left; }}"
        )
        add_btn.clicked.connect(lambda: self._add_row("", ""))
        v.addWidget(add_btn)

        outer.addWidget(body, 1)

        # 저장 / 취소
        btns = QHBoxLayout()
        btns.setContentsMargins(14, 6, 14, 12)
        btns.addStretch()
        cancel = QPushButton("취소")
        cancel.setStyleSheet(self._btn_qss(theme, accent=False))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("저장")
        save.setStyleSheet(self._btn_qss(theme, accent=True))
        save.clicked.connect(self._on_save)
        btns.addWidget(save)
        outer.addLayout(btns)

    # ------------------------------------------------------------------
    def _add_row(self, tag: str, color: str) -> None:
        t = self.theme
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        tag_edit = QLineEdit(tag)
        tag_edit.setPlaceholderText("태그명")
        tag_edit.setStyleSheet(input_qss(t))
        h.addWidget(tag_edit, 1)

        color_edit = QLineEdit(color)
        color_edit.setPlaceholderText("#bb9af7")
        color_edit.setFixedWidth(90)
        color_edit.setStyleSheet(input_qss(t))
        h.addWidget(color_edit)

        # 미리보기 swatch
        swatch = QLabel()
        swatch.setFixedSize(22, 22)
        swatch.setStyleSheet(
            f"background: {color or t['inset']}; border-radius: 3px;"
            f" border: 1px solid {t['border']};"
        )
        swatch.setCursor(Qt.PointingHandCursor)
        swatch.setToolTip("클릭으로 색 선택")
        swatch.mousePressEvent = lambda _e, c=color_edit, s=swatch: \
            self._pick_color(c, s)
        h.addWidget(swatch)
        # 색 입력 변경 시 swatch 갱신
        color_edit.textChanged.connect(
            lambda txt, s=swatch: s.setStyleSheet(
                f"background: {txt or t['inset']}; border-radius: 3px;"
                f" border: 1px solid {t['border']};"
            )
        )

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['danger']};"
            f" border: none; font-size: 10pt; }}"
        )
        del_btn.clicked.connect(
            lambda: self._delete_row(row, tag_edit, color_edit, del_btn))
        h.addWidget(del_btn)

        self.rows_layout.addWidget(row)
        self._rows.append((tag_edit, color_edit, del_btn))

    def _delete_row(self, row: QWidget, tag_edit, color_edit, del_btn) -> None:
        self._rows = [
            r for r in self._rows
            if not (r[0] is tag_edit and r[1] is color_edit and r[2] is del_btn)
        ]
        self.rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _pick_color(self, color_edit: QLineEdit, swatch: QLabel) -> None:
        cur = QColor(color_edit.text().strip() or "#bb9af7")
        picked = QColorDialog.getColor(cur, self, "색 선택")
        if picked.isValid():
            color_edit.setText(picked.name())

    def _on_save(self) -> None:
        mapping: dict[str, str] = {}
        for tag_e, col_e, _ in self._rows:
            tag = tag_e.text().strip().lstrip("#")
            col = col_e.text().strip()
            if tag and col:
                mapping[tag] = col
        self.on_saved(mapping)
        self.accept()

    @staticmethod
    def _label(text: str, color: str, size: int) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: {size}pt;")
        lbl.setWordWrap(True)
        return lbl

    @staticmethod
    def _btn_qss(t: dict, accent: bool) -> str:
        if accent:
            return (
                f"QPushButton {{ background: {t['accent']}; color: {t['bg']};"
                f" border: none; padding: 6px 14px; border-radius: 3px;"
                f" font-weight: 600; }}"
            )
        return (
            f"QPushButton {{ background: {t['card']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; padding: 6px 14px;"
            f" border-radius: 3px; }}"
        )
