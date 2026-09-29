"""새 프로젝트 다이얼로그 — 이름 + 템플릿 dropdown.

빠른 입력은 이름만으로 즉시 생성. 템플릿이나 마감 설정이 필요할 때
이 다이얼로그를 통해 만든다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import core
from qt.theme import app_qss, input_qss
from qt.titlebar import TitleBar


class NewProjectDialog(QDialog):
    """frameless 모달 — 이름 + 템플릿."""

    def __init__(
        self,
        cfg: dict,
        theme: dict,
        on_created: Callable[[str], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.cfg = cfg
        self.theme = theme
        self.on_created = on_created

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme))
        self.resize(360, 200)
        self.setModal(True)
        if parent is not None:
            geo = parent.frameGeometry()
            self.move(geo.x() + 60, geo.y() + 50)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, theme, "새 프로젝트"))

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._label("이름", theme['text'], 10, bold=True))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("새 프로젝트 이름")
        self.name_edit.setStyleSheet(input_qss(theme))
        v.addWidget(self.name_edit)

        templates = core.list_templates()
        if templates:
            v.addWidget(self._label("템플릿", theme['text'], 9))
            self.template_combo = QComboBox()
            self.template_combo.addItem("(기본 — 빈 STATUS.md)")
            for t in templates:
                self.template_combo.addItem(t)
            self.template_combo.setStyleSheet(self._combo_qss(theme))
            v.addWidget(self.template_combo)
        else:
            self.template_combo = None

        self.msg = QLabel("")
        self.msg.setStyleSheet(
            f"color: {theme['danger']}; font-size: 8pt;"
        )
        v.addWidget(self.msg)

        v.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("취소")
        cancel.setStyleSheet(self._btn_qss(theme, accent=False))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        create = QPushButton("만들기")
        create.setStyleSheet(self._btn_qss(theme, accent=True))
        create.clicked.connect(self._on_create)
        create.setDefault(True)
        btns.addWidget(create)
        v.addLayout(btns)

        outer.addWidget(body, 1)
        self.name_edit.setFocus()
        self.name_edit.returnPressed.connect(self._on_create)

    # ------------------------------------------------------------------
    def _on_create(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.msg.setText("프로젝트 이름을 입력하세요")
            return
        folder = core.safe_folder_name(name)
        if not folder:
            self.msg.setText("이름에 쓸 수 있는 글자가 없습니다")
            return
        parent_dir = core.manual_project_parent(self.cfg)
        if (parent_dir / folder).exists():
            self.msg.setText("같은 이름의 프로젝트가 이미 있습니다")
            return
        template = None
        if self.template_combo is not None:
            idx = self.template_combo.currentIndex()
            if idx > 0:
                template = self.template_combo.currentText()
        try:
            core.create_project(parent_dir, folder, name, template=template)
        except OSError as e:
            self.msg.setText(f"생성 실패: {e}")
            return
        # 펼친 상태 + 인박스 다음 위치 등록
        core.register_new_project(self.cfg, folder)
        self.on_created(folder)
        self.accept()

    @staticmethod
    def _label(text: str, color: str, size: int,
               bold: bool = False) -> QLabel:
        lbl = QLabel(text)
        w = "600" if bold else "400"
        lbl.setStyleSheet(
            f"color: {color}; font-size: {size}pt; font-weight: {w};"
        )
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

    @staticmethod
    def _combo_qss(t: dict) -> str:
        return (
            f"QComboBox {{ background: {t['card']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; border-radius: 3px;"
            f" padding: 4px 8px; }}"
            f"QComboBox:focus {{ border: 1px solid {t['accent']}; }}"
            f"QComboBox QAbstractItemView {{ background: {t['card']};"
            f" color: {t['text']}; selection-background-color: {t['accent']};"
            f" selection-color: {t['bg']}; border: 1px solid {t['border']}; }}"
        )
