"""프로젝트 카드 위젯.

`core.Project` 한 개를 받아 제목·진행률·할 일 행 표시.
- 더블클릭 → 편집창
- 우클릭 → 메뉴 (편집/접기/숨기기/파일 열기)
- collapsed 면 todo 행 숨김 (진행률·제목만)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

import core
from qt.theme import TAG_STRIP_RE, menu_qss, tag_color


CARD_MIME = "application/x-project-folder"


class TodoRow(QWidget):
    """할 일 한 줄 — 체크 마크 클릭 가능 (메인 카드용 — 인라인 편집 없음)."""

    def __init__(self, item: core.TodoItem, theme: dict,
                 on_toggle: Callable[[str, bool], None]):
        super().__init__()
        self.item = item
        self.theme = theme
        self.on_toggle = on_toggle

        h = QHBoxLayout(self)
        h.setSpacing(8)
        h.setContentsMargins(0, 0, 0, 0)

        self.mark = QLabel("☑" if item.done else "☐")
        self.mark.setCursor(Qt.PointingHandCursor)
        self._apply_mark_style()
        h.addWidget(self.mark)

        due, clean = core.extract_first_due(item.text)
        self.lbl = QLabel(clean)
        self.lbl.setWordWrap(True)
        self._apply_label_style()
        h.addWidget(self.lbl, 1)

        if due:
            badge = QLabel(due[5:])
            badge.setStyleSheet(
                f"color: {theme['warn']}; font-size: 8pt;"
                f" padding: 1px 5px; background: {theme['inset']};"
                f" border-radius: 3px;"
            )
            h.addWidget(badge)

    def _apply_mark_style(self) -> None:
        c = self.theme["accent"] if self.item.done else self.theme["subtext"]
        self.mark.setStyleSheet(f"color: {c}; font-size: 11pt;")

    def _apply_label_style(self) -> None:
        color = self.theme["muted"] if self.item.done else self.theme["text"]
        extra = "text-decoration: line-through;" if self.item.done else ""
        self.lbl.setStyleSheet(f"color: {color}; font-size: 9pt; {extra}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            new_done = not self.item.done
            self.item.done = new_done
            self._apply_mark_style()
            self.mark.setText("☑" if new_done else "☐")
            self._apply_label_style()
            self.on_toggle(self.item.text, new_done)
            e.accept()


class ProjectCard(QFrame):
    """프로젝트 카드.

    Args:
        on_change: 데이터 변경 시 호출 (체크 토글 등) — 메인 윈도우 새로고침 트리거.
        on_open_editor(project): 더블클릭 / 우클릭 '편집' — 편집창 열기.
        on_toggle_collapsed(project): 우클릭 '접기/펴기'.
        on_toggle_hidden(project): 우클릭 '숨기기'.
        on_open_path(path): 우클릭 'STATUS.md/update.md/폴더 열기'.
    """

    def __init__(
        self,
        project: core.Project,
        theme: dict,
        on_change: Callable[[], None],
        on_open_editor: Callable[[core.Project], None] | None = None,
        on_toggle_collapsed: Callable[[core.Project], None] | None = None,
        on_toggle_hidden: Callable[[core.Project], None] | None = None,
        on_open_path: Callable[[Path], None] | None = None,
        on_toggle_tag_filter: Callable[[str], None] | None = None,
        on_todo_dblclick: Callable[..., None] | None = None,
        on_open_orders: Callable[[core.Project], None] | None = None,
        on_advance_order: Callable[..., None] | None = None,
        *,
        sort_by_due: bool = False,
        show_completed: bool = False,
        tag_filter: str = "",
        item_query: str = "",
        tag_colors: dict | None = None,
        orders_data: dict | None = None,
    ):
        super().__init__()
        self.project = project
        self.theme = theme
        self.on_change = on_change
        self.on_open_editor = on_open_editor
        self.on_toggle_collapsed = on_toggle_collapsed
        self.on_toggle_hidden = on_toggle_hidden
        self.on_open_path = on_open_path
        self.on_toggle_tag_filter = on_toggle_tag_filter
        self.on_todo_dblclick = on_todo_dblclick
        self.on_open_orders = on_open_orders
        self.on_advance_order = on_advance_order
        self.orders_data = orders_data or {}
        self.sort_by_due = sort_by_due
        self.show_completed = show_completed
        self.tag_filter = tag_filter
        self.item_query = item_query
        self.tag_colors_map = tag_colors or {}

        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        # 드래그용 시작 위치 (핸들에서 mousePress 시 기록)
        self._drag_start_pos = None

        # 제목 행 — 별도 QWidget 으로 감싸서 박스 전체가 클릭 가능 (접기/펴기 토글)
        head_widget = QWidget()
        head_widget.setStyleSheet("background: transparent;")
        head_widget.setCursor(Qt.PointingHandCursor)
        head_widget.mousePressEvent = self._on_head_click
        head = QHBoxLayout(head_widget)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        # project.name 은 이미 마감 토큰이 제거된 상태 — due 는 project.due 에 따로
        due = project.due
        clean_name = project.name
        self._clean_name = clean_name

        # 드래그 핸들 ⋮⋮ — 카드 순서 변경 (카드 본체의 더블/우클릭과 충돌 안 나게 별도 위젯)
        handle = QLabel("⋮⋮")
        handle.setCursor(Qt.OpenHandCursor)
        handle.setToolTip("드래그해서 순서 변경")
        handle.setStyleSheet(
            f"color: {theme['muted']}; font-size: 11pt;"
            f" padding: 0 2px;"
        )
        handle.mousePressEvent = self._on_handle_press
        handle.mouseMoveEvent = self._on_handle_move
        handle.mouseReleaseEvent = self._on_handle_release
        head.addWidget(handle)

        # 접힘 표시 — 클릭하면 접기/펴기 토글. fixed size 로 hit 영역 명확화
        fold_mark = QLabel("▶" if project.collapsed else "▼")
        fold_mark.setCursor(Qt.PointingHandCursor)
        fold_mark.setToolTip("접기 / 펴기")
        fold_mark.setFixedSize(22, 22)
        fold_mark.setAlignment(Qt.AlignCenter)
        fold_mark.setStyleSheet(
            f"color: {theme['subtext']}; font-size: 11pt;"
            f" background: transparent;"
        )
        fold_mark.mousePressEvent = self._on_fold_click
        self._fold_mark_ref = fold_mark
        head.addWidget(fold_mark)

        title = QLabel(clean_name)
        title.setStyleSheet(
            f"color: {theme['text']}; font-size: 11pt; font-weight: 600;"
        )
        title.setWordWrap(True)
        head.addWidget(title, 1)

        if due:
            due_lbl = QLabel(due)
            due_lbl.setStyleSheet(
                f"color: {theme['warn']}; font-size: 8pt;"
                f" padding: 1px 6px; background: {theme['inset']};"
                f" border-radius: 3px;"
            )
            head.addWidget(due_lbl)

        self.pct_lbl = QLabel(f"{project.percent}%")
        self.pct_lbl.setStyleSheet(
            f"color: {theme['subtext']}; font-size: 9pt; font-weight: 600;"
        )
        head.addWidget(self.pct_lbl)
        v.addWidget(head_widget)

        self.bar = QProgressBar()
        self.bar.setValue(project.percent)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)

        # 카드별 태그 통계 — 미완료 todo 의 태그 카운트 (compact/펼친 모두 표시)
        chips_row = self._build_tag_chips()
        if chips_row is not None:
            v.addWidget(chips_row)

        # collapsed 면 메모/최근 변경도 숨김 — 제목 막대만
        if project.collapsed:
            return

        # 카드 = 진행률 + 메모 + 최근 변경. 할 일은 통합 '전체 할 일' 영역에서만.
        # 카드 우클릭 → 접기 누르면 통합에서도 그 프로젝트 그룹이 숨겨짐.
        if project.note:
            note = QLabel(project.note)
            note.setStyleSheet(
                f"color: {theme['text']}; font-size: 9pt; font-style: italic;"
            )
            note.setWordWrap(True)
            v.addWidget(note)

        # 최근 변경 (update.md 가 있을 때만, 클릭하면 update.md 열림)
        if project.last_update:
            text = f"🕒 {project.last_update}"
            if project.last_change:
                text += f"  ·  {project.last_change}"
            upd = QLabel(text)
            upd.setStyleSheet(
                f"color: {theme['accent']}; font-size: 8pt; padding: 2px 0;"
            )
            upd.setWordWrap(True)
            if project.update_path is not None and self.on_open_path:
                upd.setCursor(Qt.PointingHandCursor)
                upd.setToolTip("update.md 열기")
                upd.mousePressEvent = self._on_update_click
            v.addWidget(upd)

        # 발주 트래커 행도 함께 표시 (있으면)
        for order_row in self.orders_data.get("rows", []):
            v.addWidget(self._make_orders_row(order_row))

        # 할 일 리스트 — 전역 정렬/완료보기/태그필터/검색 적용
        items = self._filter_items()
        if items:
            for it in items:
                v.addWidget(self._make_todo_row(it))
        elif project.total > 0:
            done_lbl = QLabel("✓ 모두 완료" if not project.todos else "")
            if done_lbl.text():
                done_lbl.setStyleSheet(
                    f"color: {theme['ok']}; font-size: 9pt; padding-top: 4px;"
                )
                v.addWidget(done_lbl)

    # ------------------------------------------------------------------
    def _build_tag_chips(self) -> QWidget | None:
        """이 카드의 미완료 todo 태그별 카운트 칩. 없으면 None.

        클릭 시 `on_toggle_tag_filter(tag)` 호출 — 전역 헤더의 칩과 동일 동작.
        활성 필터 칩은 흰 두꺼운 테두리.
        """
        counts: dict[str, int] = {}
        for it in self.project.todos:
            for tag in it.tags:
                counts[tag] = counts.get(tag, 0) + 1
        if not counts:
            return None

        t = self.theme
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 0)
        h.setSpacing(4)
        for tag, cnt in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            bg = tag_color(tag, self.tag_colors_map)
            is_active = (self.tag_filter == tag)
            border = (f"2px solid {t['text']}" if is_active
                      else "1px solid transparent")
            chip = QLabel(f"#{tag}·{cnt}")
            chip.setStyleSheet(
                f"color: {t['bg']}; font-size: 7pt; font-weight: 700;"
                f" padding: 1px 5px; background: {bg};"
                f" border-radius: 3px; border: {border};"
            )
            if self.on_toggle_tag_filter is not None:
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(
                    f"#{tag} 필터 해제" if is_active else f"#{tag} 로 필터"
                )
                chip.mousePressEvent = (
                    lambda e, tg=tag: self.on_toggle_tag_filter(tg)
                    if e.button() == Qt.LeftButton else None
                )
            h.addWidget(chip)
        h.addStretch()
        return row

    def _filter_items(self) -> list:
        """전역 토글(sort/show_completed/tag_filter/query) 적용해서 표시할 todo 목록."""
        src = self.project.items if self.show_completed else self.project.todos
        out = []
        q = self.item_query
        flt = self.tag_filter
        for it in src:
            if flt and flt not in it.tags:
                continue
            if q and q not in it.text.lower():
                continue
            out.append(it)
        if self.sort_by_due:
            out.sort(key=lambda it: it.due or "9999-99-99")
        return out

    def _make_orders_row(self, order_row: dict) -> QWidget:
        """발주 트래커 한 줄 — 이름 + 현재 단계 + 진행 마커 + 마감 배지.

        체크 클릭 → 다음 미완료 단계 advance. 모든 단계 완료면 줄 자체 완료.
        """
        t = self.theme
        name = order_row.get("name", "")
        flags = list(order_row.get("stages") or [])
        stage_names = list(self.orders_data.get("_stages") or [])
        # 길이 맞춤
        if len(flags) < len(stage_names):
            flags = flags + [False] * (len(stage_names) - len(flags))
        all_done = bool(stage_names) and all(flags[:len(stage_names)])
        next_idx = next(
            (i for i, x in enumerate(flags[:len(stage_names)]) if not x),
            len(stage_names),
        )

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setSpacing(8)
        h.setContentsMargins(0, 0, 0, 0)

        # 트래커 행 본문(체크 외)의 더블클릭 → 트래커 다이얼로그
        def on_open_dbl(_e):
            if self.on_open_orders is not None:
                self.on_open_orders(self.project)
        row.mouseDoubleClickEvent = on_open_dbl

        # 체크 마크
        mark = QLabel("☑" if all_done else "☐")
        mark.setCursor(Qt.PointingHandCursor)
        mark.setStyleSheet(
            f"color: {t['accent'] if all_done else t['subtext']};"
            f" font-size: 11pt; background: transparent;"
        )

        def on_advance(_e, n=name):
            if self.on_advance_order is not None:
                self.on_advance_order(self.project, n)
        mark.mousePressEvent = on_advance
        h.addWidget(mark)

        # 이름 + 현재/다음 단계
        if all_done:
            lbl_text = f"{name} — 완료"
        elif next_idx < len(stage_names):
            lbl_text = f"{name} — {stage_names[next_idx]}"
        else:
            lbl_text = name
        color = t["muted"] if all_done else t["text"]
        extra = "text-decoration: line-through;" if all_done else ""
        lbl = QLabel(lbl_text)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent; {extra}"
        )
        lbl.setWordWrap(True)
        lbl.setToolTip("더블클릭으로 트래커 열기")
        lbl.setCursor(Qt.PointingHandCursor)
        lbl.mouseDoubleClickEvent = on_open_dbl
        h.addWidget(lbl, 1)

        # 진행 마커 [●●●○○]
        if stage_names:
            markers = "".join(
                "●" if (i < len(flags) and flags[i]) else "○"
                for i in range(len(stage_names))
            )
            done_count = sum(1 for x in flags[:len(stage_names)] if x)
            progress = QLabel(f"{markers} {done_count}/{len(stage_names)}")
            progress.setStyleSheet(
                f"color: {t['accent2']}; font-size: 8pt; font-weight: 600;"
            )
            progress.setToolTip(
                "● = 완료, ○ = 미완료. 체크 클릭 = 다음 단계 / 더블클릭 = 트래커"
            )
            progress.setCursor(Qt.PointingHandCursor)
            progress.mouseDoubleClickEvent = on_open_dbl
            h.addWidget(progress)

        # 마감 배지
        due = (order_row.get("due") or "").strip()
        if due:
            badge_text = due[5:] if len(due) >= 10 else due
            badge = QLabel(badge_text)
            badge.setStyleSheet(
                f"color: {t['warn']}; font-size: 8pt;"
                f" padding: 1px 5px; background: {t['inset']};"
                f" border-radius: 3px;"
            )
            badge.setToolTip("더블클릭으로 트래커 열기")
            badge.setCursor(Qt.PointingHandCursor)
            badge.mouseDoubleClickEvent = on_open_dbl
            h.addWidget(badge)
        return row

    def _make_todo_row(self, item: "core.TodoItem") -> QWidget:
        """할 일 한 줄 — 체크 + 텍스트 + 마감 배지 + 태그 칩.

        체크 클릭 → core.set_item_done. 텍스트 자체 클릭은 동작 안 함
        (편집은 편집창에서). 태그 칩 클릭은 콜백을 카드가 알지 못해
        Phase 5 단순 모드 — 전역 헤더의 칩으로 필터.
        """
        t = self.theme
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setSpacing(8)
        h.setContentsMargins(0, 0, 0, 0)

        mark = QLabel("☑" if item.done else "☐")
        mark.setCursor(Qt.PointingHandCursor)
        mark.setStyleSheet(
            f"color: {t['accent'] if item.done else t['subtext']};"
            f" font-size: 11pt; background: transparent;"
        )

        def on_toggle(_e, it=item):
            new_done = not it.done
            try:
                core.set_item_done(
                    self.project.status_path, it.text, new_done)
            except OSError:
                return
            self.on_change()

        mark.mousePressEvent = on_toggle
        h.addWidget(mark)

        # 텍스트 — 마감/태그 떼고 본문만
        due, after_due = core.extract_first_due(item.text)
        clean = TAG_STRIP_RE.sub("", after_due).strip()
        color = t["muted"] if item.done else t["text"]
        extra = "text-decoration: line-through;" if item.done else ""
        lbl = QLabel(clean)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent; {extra}"
        )
        lbl.setWordWrap(True)
        if self.on_todo_dblclick is not None:
            lbl.setCursor(Qt.IBeamCursor)
            lbl.setToolTip("더블클릭으로 편집")
            lbl.mouseDoubleClickEvent = (
                lambda e, r=row, l=lbl, it=item:
                self.on_todo_dblclick(r, l, self.project, it)
                if e.button() == Qt.LeftButton else None
            )
        h.addWidget(lbl, 1)

        if due:
            badge = QLabel(due[5:])
            badge.setStyleSheet(
                f"color: {t['warn']}; font-size: 8pt;"
                f" padding: 1px 5px; background: {t['inset']};"
                f" border-radius: 3px;"
            )
            h.addWidget(badge)

        for tag in item.tags:
            chip_bg = tag_color(tag, self.tag_colors_map)
            chip = QLabel(f"#{tag}")
            chip.setStyleSheet(
                f"color: {t['bg']}; font-size: 7pt; font-weight: 700;"
                f" padding: 1px 5px; background: {chip_bg};"
                f" border-radius: 3px;"
            )
            h.addWidget(chip)
        return row

    # ------------------------------------------------------------------
    def _on_head_click(self, e):
        """제목 박스 전체 클릭 — 접기/펴기 토글 (드래그 핸들/▼ 마크/마감 배지 제외).

        자식 widget (drag handle, fold mark) 가 이미 e.accept() 로 처리하면 여기
        호출 안 됨. 빈 영역/제목/% 클릭은 여기로 와서 토글.
        """
        if e.button() == Qt.LeftButton and self.on_toggle_collapsed:
            self.on_toggle_collapsed(self.project)
            e.accept()

    def _on_update_click(self, e):
        """최근 변경 줄 클릭 — update.md 열기."""
        if (e.button() == Qt.LeftButton
                and self.on_open_path
                and self.project.update_path is not None):
            self.on_open_path(self.project.update_path)
            e.accept()

    def _on_handle_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start_pos = e.globalPosition().toPoint()
            e.accept()

    def _on_handle_release(self, _e):
        self._drag_start_pos = None

    def _on_handle_move(self, e):
        """일정 거리(startDragDistance) 이상 이동하면 QDrag 시작."""
        if not (e.buttons() & Qt.LeftButton):
            return
        if self._drag_start_pos is None:
            return
        delta = e.globalPosition().toPoint() - self._drag_start_pos
        if delta.manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(CARD_MIME, self.project.folder.name.encode("utf-8"))
        drag.setMimeData(mime)
        # 시각 피드백 — 카드 스냅샷을 반투명 픽맵으로
        pix = self.grab()
        if pix.width() > 220:
            pix = pix.scaledToWidth(220, Qt.SmoothTransformation)
        drag.setPixmap(pix)
        drag.setHotSpot(pix.rect().center())
        self._drag_start_pos = None
        drag.exec(Qt.MoveAction)

    def _on_fold_click(self, e):
        """▼/▶ 마크 클릭 — 접기/펴기 토글 (우클릭 메뉴와 동일)."""
        if e.button() == Qt.LeftButton and self.on_toggle_collapsed:
            self.on_toggle_collapsed(self.project)
            e.accept()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.on_open_editor:
            self.on_open_editor(self.project)
            e.accept()

    def contextMenuEvent(self, e):
        """우클릭 메뉴 — 편집/접기/숨기기/파일 열기."""
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss(self.theme))

        if self.on_open_editor:
            menu.addAction("편집...",
                           lambda: self.on_open_editor(self.project))
        if self.on_open_orders:
            menu.addAction("발주 트래커...",
                           lambda: self.on_open_orders(self.project))
        if self.on_toggle_collapsed:
            label = "펴기" if self.project.collapsed else "접기"
            menu.addAction(
                label, lambda: self.on_toggle_collapsed(self.project))
        if self.on_toggle_hidden:
            menu.addAction(
                f"'{self._clean_name}' 숨기기",
                lambda: self.on_toggle_hidden(self.project),
            )
        if self.on_open_path:
            menu.addSeparator()
            menu.addAction(
                "STATUS.md 열기",
                lambda: self.on_open_path(self.project.status_path),
            )
            if self.project.update_path is not None:
                menu.addAction(
                    "update.md 열기",
                    lambda: self.on_open_path(self.project.update_path),
                )
            menu.addAction(
                "폴더 열기",
                lambda: self.on_open_path(self.project.folder),
            )
        menu.exec(e.globalPos())

    # ------------------------------------------------------------------
    def _on_toggle(self, text: str, new_done: bool) -> None:
        """할 일 체크 토글 — 파일에 반영 + 카드 진행률 즉시 갱신."""
        try:
            core.set_item_done(self.project.status_path, text, new_done)
        except OSError:
            return
        self.bar.setValue(self.project.percent)
        self.pct_lbl.setText(f"{self.project.percent}%")
        self.on_change()
