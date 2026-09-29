"""일괄 입력 다이얼로그 — 여러 프로젝트에 할 일 또는 발주 트래커 행을 한 번에 추가.

- 모드: 할 일 (STATUS.md 에 `- [ ] ...` 추가) / 발주 행 (orders.json 에 행 추가)
- 대상: 프로젝트 체크리스트 (전체 선택/해제)
- 할 일 텍스트엔 #태그·!마감 그대로 사용 가능 (core 파서가 처리)
- 발주 행은 이름 + (선택) 마감 — 단계는 각 프로젝트의 워크플로 기준 전부 미완료
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import core
from qt.theme import app_qss, input_qss
from qt.titlebar import TitleBar


class BatchAddDialog(QDialog):
    """여러 프로젝트에 한 번에 입력."""

    def __init__(
        self,
        cfg: dict,
        theme: dict,
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.cfg = cfg
        self.theme = theme
        self.on_changed = on_changed
        self._mode = "todo"   # "todo" | "order"
        self._checks: list[tuple[core.Project, QCheckBox]] = []

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme))
        self.resize(420, 560)
        self.setModal(True)
        if parent is not None:
            geo = parent.frameGeometry()
            self.move(geo.x() + 40, geo.y() + 40)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, theme, "일괄 입력"))

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        # 모드 segmented
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self.mode_todo_lbl = QLabel("✎ 할 일")
        self.mode_todo_lbl.setCursor(Qt.PointingHandCursor)
        self.mode_todo_lbl.mousePressEvent = lambda e: (
            self._set_mode("todo") if e.button() == Qt.LeftButton else None
        )
        mode_row.addWidget(self.mode_todo_lbl)
        self.mode_order_lbl = QLabel("⧉ 발주 행")
        self.mode_order_lbl.setCursor(Qt.PointingHandCursor)
        self.mode_order_lbl.mousePressEvent = lambda e: (
            self._set_mode("order") if e.button() == Qt.LeftButton else None
        )
        mode_row.addWidget(self.mode_order_lbl)
        mode_row.addStretch()
        v.addLayout(mode_row)

        # 입력칸
        self.text_edit = QLineEdit()
        self.text_edit.setStyleSheet(input_qss(theme))
        v.addWidget(self.text_edit)

        # 발주 모드용 마감 입력 (자연어 허용)
        self.due_edit = QLineEdit()
        self.due_edit.setPlaceholderText(
            "마감 (선택) — 예: 오늘, 9/30, 2026-09-30")
        self.due_edit.setStyleSheet(input_qss(theme))
        v.addWidget(self.due_edit)

        # 대상 프로젝트 체크리스트
        v.addWidget(self._label("대상 프로젝트", theme["text"], 10, bold=True))
        sel_row = QHBoxLayout()
        sel_all = QPushButton("전체 선택")
        sel_all.setStyleSheet(self._link_btn_qss(theme["accent"]))
        sel_all.setCursor(Qt.PointingHandCursor)
        sel_all.setAutoDefault(False)
        sel_all.clicked.connect(lambda: self._set_all(True))
        sel_row.addWidget(sel_all)
        sel_none = QPushButton("전체 해제")
        sel_none.setStyleSheet(self._link_btn_qss(theme["subtext"]))
        sel_none.setCursor(Qt.PointingHandCursor)
        sel_none.setAutoDefault(False)
        sel_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(sel_none)
        sel_row.addStretch()
        v.addLayout(sel_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme['card']}; border: none;"
            f" border-radius: 4px; }}"
        )
        list_w = QWidget()
        list_w.setStyleSheet(f"background: {theme['card']};")
        lv = QVBoxLayout(list_w)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(2)
        projects = [
            p for p in core.scan_projects(cfg)
            if not p.hidden and p.folder.name != "_inbox"
        ]
        for p in projects:
            cb = QCheckBox(p.name)
            cb.setStyleSheet(self._check_qss(theme))
            lv.addWidget(cb)
            self._checks.append((p, cb))
        lv.addStretch()
        scroll.setWidget(list_w)
        v.addWidget(scroll, 1)

        self.msg = QLabel("")
        self.msg.setStyleSheet(
            f"color: {theme['ok']}; font-size: 8pt;"
        )
        v.addWidget(self.msg)

        outer.addWidget(body, 1)

        # 하단 버튼
        btns = QHBoxLayout()
        btns.setContentsMargins(14, 6, 14, 12)
        btns.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(self._btn_qss(theme, accent=False))
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        add_btn = QPushButton("추가")
        add_btn.setStyleSheet(self._btn_qss(theme, accent=True))
        add_btn.setAutoDefault(False)
        add_btn.setDefault(False)
        add_btn.clicked.connect(self._apply)
        btns.addWidget(add_btn)
        outer.addLayout(btns)

        self._refresh_mode()
        self.text_edit.setFocus()

    # ------------------------------------------------------------------
    def keyPressEvent(self, e):
        """Enter = 추가 (다이얼로그는 계속 열림 — 연속 입력 가능). Esc = 닫기."""
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._apply()
            e.accept()
            return
        super().keyPressEvent(e)

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        t = self.theme
        active = (
            f"color: {t['bg']}; background: {t['accent']};"
            f" font-size: 9pt; font-weight: 700;"
            f" padding: 3px 10px; border-radius: 3px;"
        )
        inactive = (
            f"color: {t['muted']}; background: transparent;"
            f" font-size: 9pt; font-weight: 600;"
            f" padding: 3px 10px; border-radius: 3px;"
        )
        self.mode_todo_lbl.setStyleSheet(
            active if self._mode == "todo" else inactive)
        self.mode_order_lbl.setStyleSheet(
            active if self._mode == "order" else inactive)
        if self._mode == "todo":
            self.text_edit.setPlaceholderText(
                "할 일 텍스트 #태그 !마감 — 체크한 모든 프로젝트에 추가")
            self.due_edit.setVisible(False)
        else:
            self.text_edit.setPlaceholderText(
                "발주 행 이름 (업체/항목) — 체크한 모든 프로젝트의 트래커에 추가")
            self.due_edit.setVisible(True)

    def _set_all(self, value: bool) -> None:
        for _, cb in self._checks:
            cb.setChecked(value)

    # ------------------------------------------------------------------
    def _apply(self) -> None:
        text = self.text_edit.text().strip()
        if not text:
            self._show_msg("내용을 입력하세요", error=True)
            return
        targets = [p for p, cb in self._checks if cb.isChecked()]
        if not targets:
            self._show_msg("대상 프로젝트를 선택하세요", error=True)
            return

        if self._mode == "todo":
            ok = self._apply_todo(text, targets)
        else:
            ok = self._apply_order(text, targets)
        if ok:
            self.text_edit.clear()
            self._show_msg(f"{len(targets)}개 프로젝트에 추가됨 ✓")
            self.on_changed()

    def _apply_todo(self, text: str, targets: list) -> bool:
        done = 0
        for p in targets:
            try:
                core.add_item(p.status_path, text)
                done += 1
            except OSError:
                continue
        return done > 0

    def _apply_order(self, name: str, targets: list) -> bool:
        # 마감 — 자연어 허용
        due_raw = self.due_edit.text().strip()
        due_iso = ""
        if due_raw:
            due_iso = core.parse_natural_due(due_raw) or ""
        done = 0
        for p in targets:
            try:
                data = core.load_orders(p.folder)
                stages = core.workflow_stages(
                    self.cfg, data.get("workflow") or "")
                data.setdefault("rows", []).append({
                    "name": name,
                    "due": due_iso,
                    "stages": [False] * len(stages),
                    "note": "",
                    "created": date.today().isoformat(),
                })
                core.save_orders(p.folder, data)
                done += 1
            except OSError:
                continue
        return done > 0

    def _show_msg(self, text: str, error: bool = False) -> None:
        t = self.theme
        color = t["danger"] if error else t["ok"]
        self.msg.setStyleSheet(f"color: {color}; font-size: 8pt;")
        self.msg.setText(text)

    # ------------------------------------------------------------------
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
    def _link_btn_qss(color: str) -> str:
        return (
            f"QPushButton {{ background: transparent; color: {color};"
            f" border: none; text-decoration: underline; font-size: 9pt;"
            f" padding: 2px 6px; }}"
        )

    @staticmethod
    def _check_qss(t: dict) -> str:
        return (
            f"QCheckBox {{ color: {t['text']}; font-size: 9pt;"
            f" spacing: 6px; padding: 3px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            f"QCheckBox::indicator:unchecked {{ background: {t['inset']};"
            f" border: 1px solid {t['border']}; border-radius: 3px; }}"
            f"QCheckBox::indicator:checked {{ background: {t['accent']};"
            f" border: 1px solid {t['accent']}; border-radius: 3px; }}"
        )

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
