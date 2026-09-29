"""프로젝트 편집창 — 비모달, frameless + 자체 타이틀, 우하단 그립.

이름·메모·마감 편집, 할 일 CRUD, 새 할 일 추가, update.md 기록.
저장은 입력칸이 포커스를 잃거나 Enter 칠 때 일어남 (자동 저장).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

import core
from qt.theme import app_qss, card_qss, input_qss, menu_qss
from qt.titlebar import TitleBar
from qt.todo_edit_row import TODO_MIME, TodoEditRow


class _TodoDropContainer(QWidget):
    """편집창의 할 일 영역 — TodoEditRow 들 사이로 drop 시 reorder.

    drop 시 콜백 `on_reorder(src_text, insert_index)` 호출. 시각 indicator 표시.
    """

    def __init__(self, theme: dict, on_reorder):
        super().__init__()
        self.theme = theme
        self.on_reorder = on_reorder
        self.setAcceptDrops(True)
        self._indicator: QWidget | None = None

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(TODO_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(TODO_MIME):
            return
        e.acceptProposedAction()
        self._show_indicator(self._insert_index_at(e.position().y()))

    def dragLeaveEvent(self, _e):
        self._hide_indicator()

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(TODO_MIME):
            return
        text = bytes(e.mimeData().data(TODO_MIME)).decode("utf-8")
        idx = self._insert_index_at(e.position().y())
        self._hide_indicator()
        e.acceptProposedAction()
        self.on_reorder(text, idx)

    def _row_geos(self) -> list[tuple[int, int]]:
        out = []
        lay = self.layout()
        if lay is None:
            return out
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, TodoEditRow):
                out.append((w.y(), w.y() + w.height()))
        return out

    def _insert_index_at(self, y: float) -> int:
        geos = self._row_geos()
        for i, (top, bottom) in enumerate(geos):
            if y < (top + bottom) / 2:
                return i
        return len(geos)

    def _show_indicator(self, idx: int) -> None:
        geos = self._row_geos()
        if not geos:
            return
        if idx <= 0:
            y = geos[0][0] - 2
        elif idx >= len(geos):
            y = geos[-1][1] + 2
        else:
            y = (geos[idx - 1][1] + geos[idx][0]) // 2
        if self._indicator is None:
            self._indicator = QWidget(self)
            self._indicator.setStyleSheet(
                f"background: {self.theme['accent']};"
            )
            self._indicator.setFixedHeight(2)
        self._indicator.setGeometry(0, int(y) - 1, self.width(), 2)
        self._indicator.show()
        self._indicator.raise_()

    def _hide_indicator(self) -> None:
        if self._indicator is not None:
            self._indicator.hide()


def pulse_widget(widget: QWidget, accent: str, original: str,
                 duration_ms: int = 1200, steps: int = 10) -> None:
    """위젯 배경을 accent → original 로 fade. 인라인 styleSheet 만 갱신.

    위젯이 이미 setStyleSheet 으로 다른 속성을 갖고 있으면 그 위에 background 만
    덧붙임. 끝나면 background 줄을 제거.
    """
    base_qss = widget.styleSheet()
    timer = QTimer(widget)
    state = {"step": 0}

    def hex_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    ar, ag, ab = hex_rgb(accent)
    br, bg_, bb = hex_rgb(original)

    def tick() -> None:
        f = state["step"] / steps
        r = int(ar * (1 - f) + br * f)
        g = int(ag * (1 - f) + bg_ * f)
        b = int(ab * (1 - f) + bb * f)
        color = f"#{r:02x}{g:02x}{b:02x}"
        widget.setStyleSheet(
            base_qss + f"\nQWidget {{ background: {color}; border-radius: 4px; }}"
        )
        state["step"] += 1
        if state["step"] > steps:
            timer.stop()
            widget.setStyleSheet(base_qss)

    timer.timeout.connect(tick)
    timer.start(max(20, duration_ms // steps))


class ProjectEditor(QWidget):
    """편집창 — 부모 윈도우 위에 별도 창으로 띄움 (비모달)."""

    def __init__(
        self,
        project: core.Project,
        cfg: dict,
        theme: dict,
        on_change: Callable[[], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.project = project
        self.cfg = cfg
        self.theme = theme
        self.on_change = on_change

        # 마감은 project.due, 이름은 이미 마감 토큰이 제거된 project.name
        self._cur_proj_due = project.due
        self._cur_proj_clean = project.name
        proj_due = project.due
        proj_clean_name = project.name

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme) + card_qss(theme))
        self.resize(460, 600)
        if parent is not None:
            geo = parent.frameGeometry()
            self.move(geo.x() + 40, geo.y() + 40)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self, theme, f"편집 — {proj_clean_name}")
        outer.addWidget(self.title_bar)

        # Esc 로 편집창 닫기 — QLineEdit focus 중에도 동작 (QShortcut 우선)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)

        # 본문 — 스크롤
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme['bg']}; border: none; }}"
        )

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        # 이름 / 메모 / 마감 입력칸
        self.name_edit = self._field(v, "이름", proj_clean_name)
        self.name_edit.returnPressed.connect(self._save_name)
        self.name_edit.editingFinished.connect(self._save_name)

        self.note_edit = self._field(v, "메모", project.note)
        self.note_edit.returnPressed.connect(self._save_note)
        self.note_edit.editingFinished.connect(self._save_note)

        self.due_edit = self._field(
            v, "마감", proj_due,
            placeholder="예: 오늘, 9월30일, 9/30, 2026-09-30 (비우면 제거)",
        )
        self.due_edit.returnPressed.connect(self._save_due)
        self.due_edit.editingFinished.connect(self._save_due)

        # 할 일 섹션 — 드롭 가능 컨테이너
        v.addSpacing(8)
        v.addWidget(self._section_label("할 일"))

        self.todo_container = _TodoDropContainer(theme, self._reorder_todo)
        self.todo_layout = QVBoxLayout(self.todo_container)
        self.todo_layout.setSpacing(2)
        self.todo_layout.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.todo_container)
        self._scroll_ref = scroll   # _add_task 후 자동 스크롤용

        for it in project.items:
            self._add_todo_widget(it)

        # 새 할 일 추가
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 4, 0, 0)
        plus = QLabel("+")
        plus.setStyleSheet(
            f"color: {theme['accent']}; font-size: 12pt; font-weight: bold;"
        )
        add_row.addWidget(plus)
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText(
            "새 할 일 — Enter (마감 같이 적기: ... !9/30)"
        )
        self.add_edit.setStyleSheet(input_qss(theme))
        self.add_edit.returnPressed.connect(self._add_task)
        add_row.addWidget(self.add_edit, 1)
        v.addLayout(add_row)

        # update.md 기록
        v.addSpacing(10)
        v.addWidget(self._section_label("변경 기록 (update.md)"))
        upd_row = QHBoxLayout()
        upd_row.setSpacing(6)
        self.upd_edit = QLineEdit()
        self.upd_edit.setPlaceholderText("오늘 한 일 한 줄 — Enter")
        self.upd_edit.setStyleSheet(input_qss(theme))
        self.upd_edit.returnPressed.connect(self._add_update)
        upd_row.addWidget(self.upd_edit, 1)
        self.upd_msg = QLabel("")
        self.upd_msg.setStyleSheet(
            f"color: {theme['ok']}; font-size: 8pt; padding: 0 4px;"
        )
        upd_row.addWidget(self.upd_msg)
        v.addLayout(upd_row)

        v.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 우하단 사이즈 그립
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip)
        outer.addLayout(grip_row)

    # ------------------------------------------------------------------
    def _field(self, parent_layout: QVBoxLayout, label: str,
               value: str, placeholder: str = "") -> QLineEdit:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setFixedWidth(40)
        lbl.setStyleSheet(
            f"color: {self.theme['subtext']}; font-size: 9pt;"
        )
        row.addWidget(lbl)
        edit = QLineEdit(value)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(input_qss(self.theme))
        row.addWidget(edit, 1)
        parent_layout.addLayout(row)
        return edit

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {self.theme['text']}; font-size: 10pt; font-weight: 600;"
        )
        return lbl

    def _add_todo_widget(self, item: core.TodoItem) -> None:
        row = TodoEditRow(
            item, self.project.status_path, self.theme,
            on_change=self._notify_change,
            on_delete=self._on_todo_delete,
            on_move_request=self._on_todo_move_request,
        )
        self.todo_layout.addWidget(row)

    def _on_todo_move_request(self, row: TodoEditRow,
                              anchor: QWidget) -> None:
        """↗ 버튼 클릭 — 다른 프로젝트 선택 메뉴를 anchor 아래에 띄움."""
        candidates = [
            p for p in core.scan_projects(self.cfg)
            if p.folder.name != self.project.folder.name
        ]
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss(self.theme))
        title = menu.addAction("옮길 프로젝트")
        title.setEnabled(False)
        menu.addSeparator()
        if not row.item.done:
            menu.addAction("→ work-inbox (텔레그램 대기실)",
                           lambda r=row: self._do_send_work_inbox(r))
            menu.addSeparator()
        for target in candidates:
            _, clean = core.extract_first_due(target.name)
            menu.addAction(
                f"→ {clean}",
                lambda t=target, r=row: self._do_move_todo(r, t),
            )
        # 버튼 아래에 띄움
        gpos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        menu.exec(gpos)

    def _do_move_todo(self, row: TodoEditRow,
                      target: core.Project) -> None:
        ok = core.move_item(
            self.project.status_path,
            target.folder / core.STATUS_FILENAME,
            row.item.text,
        )
        if not ok:
            return
        self._remove_row(row)

    def _do_send_work_inbox(self, row: TodoEditRow) -> None:
        try:
            core.send_to_work_inbox(self.project.status_path, row.item.text,
                                    self._cur_proj_clean)
        except Exception as e:  # OSError, sqlite3.Error
            QMessageBox.warning(self, "work-inbox 이동 실패", str(e))
            return
        self._remove_row(row)

    def _remove_row(self, row: TodoEditRow) -> None:
        self.todo_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self.project.items = [
            it for it in self.project.items if it is not row.item
        ]
        self._notify_change()

    # ------------------------------------------------------------------
    def _save_name(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setText(self._cur_proj_clean)
            return
        if name == self._cur_proj_clean:
            return
        try:
            new_folder = core.rename_project_folder(
                self.project.folder, name, self.cfg)
        except (ValueError, FileExistsError, OSError) as e:
            QMessageBox.warning(self, "이름 변경 실패", str(e))
            self.name_edit.setText(self._cur_proj_clean)
            return
        # core 가 STATUS '# 제목' 을 새 이름으로 바꿀 때 기존 마감 보존
        self.project.folder = new_folder
        self.project.status_path = new_folder / core.STATUS_FILENAME
        self.project.update_path = new_folder / core.UPDATE_FILENAME
        self._cur_proj_clean = name
        # project.name 은 항상 마감 토큰 없는 형태 (core convention)
        self.project.name = name
        self.title_bar.set_title(f"편집 — {name}")
        # 할 일 행들의 status_path 도 새 폴더 기준으로 갱신
        for i in range(self.todo_layout.count()):
            w = self.todo_layout.itemAt(i).widget()
            if isinstance(w, TodoEditRow):
                w.status_path = self.project.status_path
        self._notify_change()

    def _save_note(self) -> None:
        note = self.note_edit.text().strip()
        if note == self.project.note:
            return
        try:
            core.set_project_note(self.project.status_path, note)
        except OSError:
            return
        self.project.note = note
        self._notify_change()

    def _save_due(self) -> None:
        text = self.due_edit.text().strip()
        if not text:
            new_iso = ""
        else:
            new_iso = core.parse_natural_due(text)
            if new_iso is None:
                self.due_edit.setText(self._cur_proj_due)
                return
        if new_iso == self._cur_proj_due:
            return
        try:
            core.set_project_due(self.project.status_path, new_iso)
        except OSError:
            return
        self._cur_proj_due = new_iso
        self.due_edit.setText(new_iso)
        # project.name 은 마감 토큰 없는 형태 그대로, due 만 갱신
        self.project.due = new_iso
        self._notify_change()

    def _add_task(self) -> None:
        text = self.add_edit.text().strip()
        if not text:
            return
        try:
            core.add_item(self.project.status_path, text)
        except OSError:
            return
        # 새 항목을 다시 파싱해서 정확한 TodoItem 객체 만듦 (tags/due 채워야)
        try:
            fresh = core.scan_projects(self.cfg)
            updated = next(
                (p for p in fresh
                 if p.folder.name == self.project.folder.name),
                None,
            )
            new_item = None
            if updated is not None:
                for it in reversed(updated.items):
                    if it.text == text and not it.done:
                        new_item = it
                        break
                self.project.items = list(updated.items)
        except Exception:
            new_item = None
        if new_item is None:
            new_item = core.TodoItem(text=text, done=False)
            self.project.items.append(new_item)
        self._add_todo_widget(new_item)
        self.add_edit.clear()
        # 펄스 + 자동 스크롤 — 방금 추가한 행
        new_row = self.todo_layout.itemAt(self.todo_layout.count() - 1).widget()
        if isinstance(new_row, TodoEditRow):
            QTimer.singleShot(0, lambda: self._highlight_new_row(new_row))
        self._notify_change()

    def _highlight_new_row(self, row: TodoEditRow) -> None:
        """새 추가된 행 — 화면에 보이게 스크롤 + 펄스 강조."""
        self._scroll_ref.ensureWidgetVisible(row, 0, 20)
        pulse_widget(row, self.theme["accent"], self.theme["bg"])

    def _reorder_todo(self, src_text: str, insert_index: int) -> None:
        """편집창 안에서 할 일 순서 변경.

        같은 STATUS.md 안에서 미완료 항목의 순서만 바꿈 — 완료 항목은 자기 자리 유지.
        `core.reorder_items(status_path, full_text_order)` 호출.
        """
        rows: list[TodoEditRow] = []
        for i in range(self.todo_layout.count()):
            w = self.todo_layout.itemAt(i).widget()
            if isinstance(w, TodoEditRow):
                rows.append(w)
        src_row = next((r for r in rows if r.item.text == src_text), None)
        if src_row is None:
            return
        cur = rows.index(src_row)
        if insert_index > cur:
            insert_index -= 1
        if insert_index == cur:
            return
        # rows 새 순서
        rows.pop(cur)
        rows.insert(insert_index, src_row)

        # 미완료/완료 합쳐 full 순서 만들기 — 완료는 원래 자리에서 자기 텍스트,
        # 미완료 자리엔 새 순서를 차례로
        new_open_texts = iter(r.item.text for r in rows)
        full: list[str] = []
        for it in self.project.items:
            if it.done:
                full.append(it.text)
            else:
                full.append(next(new_open_texts, it.text))
        try:
            core.reorder_items(self.project.status_path, full)
        except OSError:
            return

        # layout 에서 위젯 재배치
        for r in rows:
            self.todo_layout.removeWidget(r)
        for r in rows:
            self.todo_layout.addWidget(r)
        self._notify_change()

    def _add_update(self) -> None:
        text = self.upd_edit.text().strip()
        if not text:
            return
        update_path = self.project.folder / core.UPDATE_FILENAME
        try:
            core.add_update_entry(update_path, text)
        except OSError:
            return
        self.upd_edit.clear()
        self.upd_msg.setText("기록됨 ✓")
        QTimer.singleShot(2500, lambda: self.upd_msg.setText(""))
        self._notify_change()

    def _on_todo_delete(self, row: TodoEditRow) -> None:
        self.todo_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self.project.items = [
            it for it in self.project.items if it is not row.item
        ]
        self._notify_change()

    def _notify_change(self) -> None:
        """편집 결과를 메인 윈도우에 알림 → 메인 윈도우는 fingerprint 깨고 refresh."""
        try:
            self.on_change()
        except Exception:
            pass
