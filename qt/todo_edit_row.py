"""편집창 안의 할 일 한 행 — 체크/인라인 편집/마감 픽커/삭제.

각 행이 자기 데이터(`item`)와 파일(`status_path`)을 알고 core 호출.
변경 시 `on_change()` 콜백, 삭제 요청 시 `on_delete(row)` 콜백 — 부모(editor)에 위임.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QWidget,
)

import core


TODO_MIME = "application/x-todo-text"


class TodoEditRow(QWidget):
    """체크 + 텍스트(편집칸) + 마감 배지 + 삭제."""

    def __init__(
        self,
        item: core.TodoItem,
        status_path,
        theme: dict,
        on_change: Callable[[], None],
        on_delete: Callable[["TodoEditRow"], None],
        on_move_request: Callable[["TodoEditRow", QWidget], None] | None = None,
    ):
        super().__init__()
        self.item = item
        self.status_path = status_path
        self.theme = theme
        self.on_change = on_change
        self.on_delete = on_delete
        self.on_move_request = on_move_request

        due, clean = core.extract_first_due(item.text)
        self._cur_due = due           # 현재 ISO 마감 (없으면 "")
        self._cur_clean = clean       # 마감 토큰 뗀 텍스트

        h = QHBoxLayout(self)
        h.setSpacing(6)
        h.setContentsMargins(0, 0, 0, 0)

        # 드래그 핸들 ⋮⋮ — 행 순서 변경
        self._drag_start_pos = None
        handle = QLabel("⋮⋮")
        handle.setCursor(Qt.OpenHandCursor)
        handle.setToolTip("드래그해서 순서 변경")
        handle.setStyleSheet(
            f"color: {theme['muted']}; font-size: 10pt; padding: 0 2px;"
        )
        handle.mousePressEvent = self._on_handle_press
        handle.mouseMoveEvent = self._on_handle_move
        handle.mouseReleaseEvent = self._on_handle_release
        h.addWidget(handle)

        # 체크 마크
        self.mark = QLabel("☑" if item.done else "☐")
        self.mark.setCursor(Qt.PointingHandCursor)
        self.mark.mousePressEvent = self._on_check
        self._apply_mark_style()
        h.addWidget(self.mark)

        # 텍스트 — 평소 투명 border, 포커스 시 강조
        self.text_edit = QLineEdit(clean)
        self.text_edit.setStyleSheet(self._text_qss())
        self.text_edit.editingFinished.connect(self._save_text)
        h.addWidget(self.text_edit, 1)

        # 마감 배지/픽커
        self.due_btn = QLabel()
        self.due_btn.setCursor(Qt.PointingHandCursor)
        self.due_btn.mousePressEvent = self._on_pick_due
        self._refresh_due_view()
        h.addWidget(self.due_btn)

        # 다른 프로젝트로 이동 (편집창에서 cfg 가 있을 때만 콜백 연결됨)
        if self.on_move_request is not None:
            move_btn = QLabel("↗")
            move_btn.setCursor(Qt.PointingHandCursor)
            move_btn.setStyleSheet(
                f"color: {theme['subtext']}; font-size: 11pt; padding: 2px 4px;"
            )
            move_btn.setToolTip("다른 프로젝트로 이동")
            move_btn.mousePressEvent = self._on_move_click
            h.addWidget(move_btn)
            self.move_btn = move_btn

        # 삭제
        del_btn = QLabel("✕")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet(
            f"color: {theme['danger']}; font-size: 10pt; padding: 2px;"
        )
        del_btn.setToolTip("이 할 일 삭제")
        del_btn.mousePressEvent = self._on_delete_click
        h.addWidget(del_btn)

    # ------------------------------------------------------------------
    def _apply_mark_style(self) -> None:
        c = self.theme["accent"] if self.item.done else self.theme["subtext"]
        self.mark.setStyleSheet(f"color: {c}; font-size: 12pt; padding: 2px;")

    def _text_qss(self) -> str:
        t = self.theme
        color = t["muted"] if self.item.done else t["text"]
        extra = "text-decoration: line-through;" if self.item.done else ""
        return (
            f"QLineEdit {{ background: transparent; border: 1px solid transparent;"
            f" color: {color}; font-size: 10pt; padding: 2px 4px; {extra} }}"
            f"QLineEdit:focus {{ background: {t['inset']};"
            f" border: 1px solid {t['accent']}; color: {t['text']}; }}"
        )

    def _refresh_due_view(self) -> None:
        t = self.theme
        if self._cur_due:
            self.due_btn.setText(self._cur_due[5:])   # MM-DD
            self.due_btn.setStyleSheet(
                f"color: {t['warn']}; font-size: 8pt;"
                f" padding: 1px 5px; background: {t['inset']};"
                f" border-radius: 3px;"
            )
            self.due_btn.setToolTip(f"마감일: {self._cur_due} (클릭으로 변경)")
        else:
            self.due_btn.setText("📅")
            self.due_btn.setStyleSheet(
                f"color: {t['muted']}; font-size: 10pt; padding: 1px 3px;"
            )
            self.due_btn.setToolTip("마감일 설정 (클릭)")

    # ------------------------------------------------------------------
    def _on_check(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        new_done = not self.item.done
        try:
            core.set_item_done(self.status_path, self.item.text, new_done)
        except OSError:
            return
        self.item.done = new_done
        self.mark.setText("☑" if new_done else "☐")
        self._apply_mark_style()
        self.text_edit.setStyleSheet(self._text_qss())
        self.on_change()

    def _save_text(self) -> None:
        """텍스트 칸이 포커스를 잃을 때 호출 — 변경됐으면 파일 갱신."""
        new_clean = self.text_edit.text().strip()
        if not new_clean:
            # 빈 텍스트는 허용 안 함 — 원복
            self.text_edit.blockSignals(True)
            self.text_edit.setText(self._cur_clean)
            self.text_edit.blockSignals(False)
            return
        # 사용자가 텍스트에 마감을 같이 적었으면 그것 우선
        embedded_due, embedded_clean = core.extract_first_due(new_clean)
        if embedded_due:
            new_full = f"{embedded_clean} !{embedded_due}"
            new_due = embedded_due
            new_clean_only = embedded_clean
        elif self._cur_due:
            new_full = f"{new_clean} !{self._cur_due}"
            new_due = self._cur_due
            new_clean_only = new_clean
        else:
            new_full = new_clean
            new_due = ""
            new_clean_only = new_clean
        if new_full == self.item.text:
            return
        try:
            core.rename_item(self.status_path, self.item.text, new_full)
        except OSError:
            return
        self.item.text = new_full
        self._cur_due = new_due
        self._cur_clean = new_clean_only
        # 텍스트 칸엔 clean 만 표시
        if self.text_edit.text() != new_clean_only:
            self.text_edit.blockSignals(True)
            self.text_edit.setText(new_clean_only)
            self.text_edit.blockSignals(False)
        self._refresh_due_view()
        self.on_change()

    def _on_pick_due(self, _e) -> None:
        """마감 픽커 — 자연어 입력 받기."""
        text, ok = QInputDialog.getText(
            self,
            "마감일 설정",
            "마감일 (예: 오늘, 내일, +3, 9월30일, 9/30, 2026-09-30)\n"
            "비우면 마감 제거:",
            text=self._cur_due,
        )
        if not ok:
            return
        text = text.strip()
        if text:
            new_iso = core.parse_natural_due(text)
            if not new_iso:
                return   # 못 알아들으면 무시
        else:
            new_iso = ""
        if new_iso == self._cur_due:
            return
        new_full = (
            f"{self._cur_clean} !{new_iso}" if new_iso else self._cur_clean
        )
        try:
            core.rename_item(self.status_path, self.item.text, new_full)
        except OSError:
            return
        self.item.text = new_full
        self._cur_due = new_iso
        self._refresh_due_view()
        self.on_change()

    def _on_delete_click(self, _e) -> None:
        try:
            core.delete_item(self.status_path, self.item.text)
        except OSError:
            return
        self.on_delete(self)

    def _on_move_click(self, _e) -> None:
        """이동 버튼 클릭 — 부모(editor)가 프로젝트 선택 메뉴 띄움."""
        if self.on_move_request is not None:
            self.on_move_request(self, self.move_btn)

    # ------------------------------------------------------------------
    # 드래그 핸들 — 같은 편집창 안에서 행 순서 변경
    def _on_handle_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start_pos = e.globalPosition().toPoint()
            e.accept()

    def _on_handle_release(self, _e):
        self._drag_start_pos = None

    def _on_handle_move(self, e):
        if not (e.buttons() & Qt.LeftButton):
            return
        if self._drag_start_pos is None:
            return
        delta = e.globalPosition().toPoint() - self._drag_start_pos
        if delta.manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(TODO_MIME, self.item.text.encode("utf-8"))
        drag.setMimeData(mime)
        pix = self.grab()
        if pix.width() > 240:
            pix = pix.scaledToWidth(240, Qt.SmoothTransformation)
        drag.setPixmap(pix)
        drag.setHotSpot(pix.rect().center())
        self._drag_start_pos = None
        drag.exec(Qt.MoveAction)
