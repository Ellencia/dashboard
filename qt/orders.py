"""발주 트래커 다이얼로그.

프로젝트 폴더의 orders.json 을 표 형식으로 편집:
- 행 = 발주 한 건 (업체/항목 이름)
- 열 = 워크플로 단계 (cfg.workflows 에서 정의)
- 각 셀 체크박스
- 마감일·메모·삭제 칸도 있음
- 워크플로 선택 (드롭다운)
- 하단 입력칸으로 새 행 추가

저장은 즉시 — 체크/이름/마감/메모 바꾸면 디스크 반영.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import core
from qt.theme import app_qss
from qt.titlebar import TitleBar


class OrdersDialog(QDialog):
    """프로젝트별 발주 트래커 — 표 형식."""

    def __init__(
        self,
        project: core.Project,
        cfg: dict,
        theme: dict,
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.project = project
        self.cfg = cfg
        self.theme = theme
        self.on_changed = on_changed
        # 데이터 로드
        self.data = core.load_orders(project.folder)
        self._suspend = False   # 위젯 셋업 중에는 변경 시그널 무시

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme))
        self.resize(720, 480)
        if parent is not None:
            geo = parent.frameGeometry()
            self.move(geo.x() + 40, geo.y() + 30)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, theme, f"발주 트래커 — {project.name}"))

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        # 워크플로 선택
        wf_row = QHBoxLayout()
        wf_row.addWidget(self._label("워크플로", theme["subtext"], 9))
        self.wf_combo = QComboBox()
        wf_names = list((cfg.get("workflows") or {}).keys())
        for name in wf_names:
            self.wf_combo.addItem(name)
        if self.data["workflow"] in wf_names:
            self.wf_combo.setCurrentText(self.data["workflow"])
        elif wf_names:
            self.data["workflow"] = wf_names[0]
        self.wf_combo.setStyleSheet(self._combo_qss(theme))
        self.wf_combo.currentTextChanged.connect(self._on_workflow_changed)
        wf_row.addWidget(self.wf_combo)
        wf_row.addStretch()
        v.addLayout(wf_row)

        # 표
        self.table = QTableWidget()
        self.table.setStyleSheet(self._table_qss(theme))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.SelectedClicked
            | QTableWidget.EditKeyPressed
        )
        self.table.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.table, 1)

        # 새 행 추가
        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        plus = QLabel("+")
        plus.setStyleSheet(
            f"color: {theme['accent']}; font-size: 12pt; font-weight: bold;"
        )
        add_row.addWidget(plus)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("새 발주 — 업체/항목 이름 — Enter")
        self.new_name.setStyleSheet(self._input_qss(theme))
        self.new_name.returnPressed.connect(self._add_row)
        add_row.addWidget(self.new_name, 1)
        v.addLayout(add_row)

        outer.addWidget(body, 1)

        # 닫기 버튼
        btns = QHBoxLayout()
        btns.setContentsMargins(14, 6, 14, 12)
        btns.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(self._btn_qss(theme, accent=True))
        # Enter 키가 default 버튼으로 가서 자동 accept 되는 걸 막음
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        outer.addLayout(btns)

        self._rebuild_table()

    # ------------------------------------------------------------------
    def _stages(self) -> list[str]:
        return core.workflow_stages(self.cfg, self.data["workflow"])

    def _rebuild_table(self) -> None:
        """워크플로/데이터 기반으로 표 재구성."""
        self._suspend = True
        stages = self._stages()
        rows = self.data.get("rows", [])
        # 열: 이름 | 마감 | 단계1 | ... | 메모 | ✕
        col_headers = ["이름", "마감"] + stages + ["메모", ""]
        self.table.clear()
        self.table.setColumnCount(len(col_headers))
        self.table.setHorizontalHeaderLabels(col_headers)
        self.table.setRowCount(len(rows))

        for i, row_data in enumerate(rows):
            # 이름
            name_item = QTableWidgetItem(row_data.get("name", ""))
            self.table.setItem(i, 0, name_item)
            # 마감
            due_item = QTableWidgetItem(row_data.get("due", ""))
            self.table.setItem(i, 1, due_item)
            # 단계 체크박스
            stage_flags = row_data.get("stages") or [False] * len(stages)
            # 워크플로 변경으로 길이 안 맞으면 맞춤
            if len(stage_flags) < len(stages):
                stage_flags = stage_flags + [False] * (
                    len(stages) - len(stage_flags))
            elif len(stage_flags) > len(stages):
                stage_flags = stage_flags[:len(stages)]
            row_data["stages"] = stage_flags
            for j, checked in enumerate(stage_flags):
                cb = QCheckBox()
                cb.setChecked(bool(checked))
                cb.setStyleSheet(self._cb_qss(self.theme))
                cb.stateChanged.connect(
                    lambda _state, ri=i, ci=j: self._on_stage_toggle(ri, ci))
                cell = QWidget()
                hl = QHBoxLayout(cell)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setAlignment(Qt.AlignCenter)
                hl.addWidget(cb)
                self.table.setCellWidget(i, 2 + j, cell)
            # 메모
            note_item = QTableWidgetItem(row_data.get("note", ""))
            self.table.setItem(i, 2 + len(stages), note_item)
            # 삭제 ✕
            del_btn = QPushButton("✕")
            del_btn.setStyleSheet(
                f"QPushButton {{ background: transparent;"
                f" color: {self.theme['danger']}; border: none;"
                f" font-size: 10pt; }}"
            )
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(lambda _c=False, ri=i: self._delete_row(ri))
            self.table.setCellWidget(i, 2 + len(stages) + 1, del_btn)

        # 열 너비
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)        # 이름
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 마감
        for j in range(len(stages)):
            header.setSectionResizeMode(2 + j, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2 + len(stages), QHeaderView.Stretch)  # 메모
        header.setSectionResizeMode(
            2 + len(stages) + 1, QHeaderView.ResizeToContents)  # ✕

        self._suspend = False

    # ------------------------------------------------------------------
    def _on_workflow_changed(self, name: str) -> None:
        if self._suspend:
            return
        self.data["workflow"] = name
        self._save()
        self._rebuild_table()

    def _on_stage_toggle(self, row_idx: int, stage_idx: int) -> None:
        if self._suspend:
            return
        rows = self.data.get("rows", [])
        if row_idx >= len(rows):
            return
        stages_flags = rows[row_idx].get("stages") or []
        stage_widget = self.table.cellWidget(row_idx, 2 + stage_idx)
        cb = stage_widget.findChild(QCheckBox)
        if cb is None:
            return
        # 길이 맞춤
        n = len(self._stages())
        if len(stages_flags) < n:
            stages_flags = stages_flags + [False] * (n - len(stages_flags))
        stages_flags[stage_idx] = cb.isChecked()
        rows[row_idx]["stages"] = stages_flags
        self._save()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suspend:
            return
        row_idx = item.row()
        col = item.column()
        rows = self.data.get("rows", [])
        if row_idx >= len(rows):
            return
        if col == 0:
            rows[row_idx]["name"] = item.text().strip()
        elif col == 1:
            rows[row_idx]["due"] = item.text().strip()
        elif col == 2 + len(self._stages()):
            rows[row_idx]["note"] = item.text().strip()
        else:
            return
        self._save()

    def keyPressEvent(self, e):
        """Enter 가 QDialog 의 default action 으로 가서 자동 accept 되는 걸 차단.

        새 행 입력칸이 포커스 가지면 _add_row 호출 (returnPressed 와 중복이지만
        _add_row 는 빈 텍스트엔 무동작이라 안전). Esc 는 super 가 처리해 reject.
        """
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.new_name.hasFocus():
                self._add_row()
            e.accept()
            return
        super().keyPressEvent(e)

    def _add_row(self) -> None:
        name = self.new_name.text().strip()
        if not name:
            return
        n = len(self._stages())
        self.data.setdefault("rows", []).append({
            "name": name,
            "due": "",
            "stages": [False] * n,
            "note": "",
            "created": date.today().isoformat(),
        })
        self.new_name.clear()
        self._save()
        self._rebuild_table()

    def _delete_row(self, row_idx: int) -> None:
        rows = self.data.get("rows", [])
        if 0 <= row_idx < len(rows):
            del rows[row_idx]
            self._save()
            self._rebuild_table()

    def _save(self) -> None:
        try:
            core.save_orders(self.project.folder, self.data)
        except OSError:
            return
        self.on_changed()

    # ------------------------------------------------------------------
    @staticmethod
    def _label(text: str, color: str, size: int) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: {size}pt;")
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
    def _input_qss(t: dict) -> str:
        return (
            f"QLineEdit {{ background: {t['card']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; border-radius: 3px;"
            f" padding: 4px 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {t['accent']}; }}"
        )

    @staticmethod
    def _combo_qss(t: dict) -> str:
        return (
            f"QComboBox {{ background: {t['card']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; border-radius: 3px;"
            f" padding: 4px 8px; }}"
            f"QComboBox QAbstractItemView {{ background: {t['card']};"
            f" color: {t['text']}; selection-background-color: {t['accent']};"
            f" selection-color: {t['bg']}; border: 1px solid {t['border']}; }}"
        )

    @staticmethod
    def _table_qss(t: dict) -> str:
        return (
            f"QTableWidget {{ background: {t['card']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; gridline-color: {t['border']};"
            f" font-size: 9pt; }}"
            f"QTableWidget::item {{ padding: 4px; }}"
            f"QTableWidget::item:selected {{ background: {t['accent']};"
            f" color: {t['bg']}; }}"
            f"QHeaderView::section {{ background: {t['bg_alt']};"
            f" color: {t['subtext']}; border: 1px solid {t['border']};"
            f" padding: 4px; font-weight: 600; }}"
        )

    @staticmethod
    def _cb_qss(t: dict) -> str:
        return (
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            f"QCheckBox::indicator:unchecked {{ background: {t['inset']};"
            f" border: 1px solid {t['border']}; border-radius: 3px; }}"
            f"QCheckBox::indicator:checked {{ background: {t['accent']};"
            f" border: 1px solid {t['accent']}; border-radius: 3px; }}"
        )
