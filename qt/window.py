"""대시보드 메인 창 — frameless, 다크, 우하단 QSizeGrip.

자동 새로고침: `QTimer` + 내용 fingerprint 비교로 변경 없으면 redraw 스킵.
빠른 프로젝트 생성, 검색 바, 단축키(Ctrl+F/N, Esc) 포함.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizeGrip,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import core
from qt.card import CARD_MIME, ProjectCard
from qt.editor import ProjectEditor, pulse_widget
from qt.new_project import NewProjectDialog
from qt.orders import OrdersDialog
from qt.theme import TAG_STRIP_RE, tag_color


class _CardDropArea(QWidget):
    """카드들을 담고 dropEvent 로 reorder 처리.

    body QWidget 전체가 drop target — 마우스 Y 좌표로 가장 가까운 카드 사이의
    삽입 위치를 결정하고 콜백 호출. 시각 피드백으로 가로선 indicator.
    """

    def __init__(self, theme: dict,
                 on_reorder):
        super().__init__()
        self.theme = theme
        self.on_reorder = on_reorder
        self.setAcceptDrops(True)
        self._indicator: QWidget | None = None

    # ------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(CARD_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(CARD_MIME):
            return
        e.acceptProposedAction()
        self._show_indicator(self._insert_index_at(e.position().y()))

    def dragLeaveEvent(self, _e):
        self._hide_indicator()

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(CARD_MIME):
            return
        folder = bytes(e.mimeData().data(CARD_MIME)).decode("utf-8")
        idx = self._insert_index_at(e.position().y())
        self._hide_indicator()
        e.acceptProposedAction()
        self.on_reorder(folder, idx)

    # ------------------------------------------------------------------
    def _card_geometries(self) -> list[tuple[int, int, int]]:
        """현재 layout 안의 ProjectCard 들의 (layout_index, y_top, y_bottom)."""
        out = []
        lay = self.layout()
        if lay is None:
            return out
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, ProjectCard):
                out.append((i, w.y(), w.y() + w.height()))
        return out

    def _insert_index_at(self, y: float) -> int:
        """마우스 Y 좌표에 따른 visible cards 안에서의 새 위치(0..N).

        UI 인덱스가 아니라 '카드들만의 인덱스' 를 반환. on_reorder 에서 사용.
        """
        geos = self._card_geometries()
        for visible_i, (_, top, bottom) in enumerate(geos):
            mid = (top + bottom) / 2
            if y < mid:
                return visible_i
        return len(geos)

    def _show_indicator(self, visible_index: int) -> None:
        """카드들 사이에 가로선 — 어느 위치로 drop 될지 표시."""
        geos = self._card_geometries()
        if not geos:
            return
        if visible_index <= 0:
            y = geos[0][1] - 2
        elif visible_index >= len(geos):
            y = geos[-1][2] + 2
        else:
            prev_bottom = geos[visible_index - 1][2]
            next_top = geos[visible_index][1]
            y = (prev_bottom + next_top) // 2
        if self._indicator is None:
            self._indicator = QWidget(self)
            self._indicator.setStyleSheet(
                f"background: {self.theme['accent']};"
            )
            self._indicator.setFixedHeight(2)
        self._indicator.setGeometry(8, int(y) - 1, self.width() - 16, 2)
        self._indicator.show()
        self._indicator.raise_()

    def _hide_indicator(self) -> None:
        if self._indicator is not None:
            self._indicator.hide()
from qt.quick_input import QuickUnifiedInput
from qt.search_bar import SearchBar
from qt.settings import SettingsDialog
from qt.theme import app_qss, card_qss
from qt.titlebar import TitleBar


class DashboardWindow(QWidget):
    """frameless + 자체 타이틀 + 빠른 입력 + 검색 + 스크롤 + 사이즈 그립."""

    def __init__(self, cfg: dict, theme: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.theme = theme
        self._last_fp: str = ""
        self._hidden_expanded: bool = False   # 숨김 섹션 펼친 상태
        self._tag_filter: str = ""            # 활성 태그 필터 (빈 값 = 없음)
        # 카드 안 todo 의 활성 인라인 edit 추적 — 다른 todo 더블클릭 시 in-place 종료
        self._active_inline_edit_state: dict | None = None
        # 폴더 이름 → 현재 열려 있는 편집창 (중복 열기 방지·재포커스용)
        self._editors: dict[str, ProjectEditor] = {}
        # 위치/크기 저장 debounce — 마지막 변경 후 500ms 뒤에 한 번만 디스크 쓰기
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._persist_geometry)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setStyleSheet(app_qss(theme) + card_qss(theme))

        wcfg = cfg.get("widget", {})
        w = int(wcfg.get("width", 440)) or 440
        h = int(wcfg.get("height", 0)) or 640
        x = int(wcfg.get("x", 60))
        y = int(wcfg.get("y", 60))
        self.resize(w, h)
        self.move(x, y)
        self.setWindowOpacity(
            max(0.4, min(1.0, float(wcfg.get("opacity", 0.96))))
        )
        if bool(wcfg.get("topmost", True)):
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(
            self, theme, "프로젝트 보드",
            on_settings=self._open_settings,
            on_new_project=self._open_new_project,
            on_batch_add=self._open_batch_add,
        ))

        # 단일 빠른 입력 — 할일/프로젝트 모드 토글
        self.quick = QuickUnifiedInput(cfg, theme, self._force_refresh)
        outer.addWidget(self.quick)

        # 검색 바 (Ctrl+F 로 토글)
        self.search = SearchBar(theme, self._force_refresh)
        outer.addWidget(self.search)

        # 본문 — 카드 + (펼침 시 그 안에 todo) + 숨김 섹션. 한 스크롤
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme['bg']}; border: none; }}"
        )
        outer.addWidget(self.scroll, 1)

        # 푸터 — 시간 + 최근 변경
        self.footer = QLabel("")
        self.footer.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.footer.setStyleSheet(
            f"color: {theme['muted']}; font-size: 8pt; padding: 4px 12px;"
        )
        outer.addWidget(self.footer)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip)
        outer.addLayout(grip_row)

        # 단축키 — Ctrl+F=검색 토글, Ctrl+N=빠른 입력 포커스, Esc=필터 해제
        QShortcut(QKeySequence("Ctrl+F"), self,
                  activated=self.search.toggle)
        QShortcut(QKeySequence("Ctrl+N"), self,
                  activated=self.quick.focus_project)
        QShortcut(QKeySequence("Ctrl+T"), self,
                  activated=self.quick.focus_todo)
        QShortcut(QKeySequence("Esc"), self,
                  activated=self._clear_filters)

        # 활성 인라인 edit 가 있을 때 다른 곳 클릭 → 자동 저장 + 라벨 복귀
        QApplication.instance().installEventFilter(self)

        # 자동 새로고침
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        interval = max(5, int(cfg.get("refresh_seconds", 30))) * 1000
        self._timer.start(interval)

        # 푸터 시간 — 1초마다 in-place 갱신 (본문 redraw 와 분리)
        self._footer_timer = QTimer(self)
        self._footer_timer.timeout.connect(self._update_footer_time)
        self._footer_timer.start(1000)

        # _drop/*.json watcher — 5초마다 처리
        self._drop_timer = QTimer(self)
        self._drop_timer.timeout.connect(self._check_drop_folder)
        self._drop_timer.start(5000)

        self._latest_change_text = ""   # 가장 최근 변경 한 줄 (캐시)
        self.refresh()
        self._update_footer_time()

    # ------------------------------------------------------------------
    def _force_refresh(self, *, just_added_folder: str = "") -> None:
        """fingerprint 무효화 + redraw. 방금 추가된 폴더가 있으면 그 카드를
        스크롤로 보이게 + 펄스 강조."""
        self._last_fp = ""
        self.refresh()
        if just_added_folder:
            QTimer.singleShot(0,
                              lambda: self._highlight_card(just_added_folder))

    def _highlight_card(self, folder_name: str) -> None:
        """방금 만든 프로젝트 카드 — ensureWidgetVisible + 펄스."""
        body = self.card_scroll.widget()
        if body is None:
            return
        lay = body.layout()
        if lay is None:
            return
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if (isinstance(w, ProjectCard)
                    and w.project.folder.name == folder_name):
                self.card_scroll.ensureWidgetVisible(w, 0, 20)
                pulse_widget(w, self.theme["accent"], self.theme["card"])
                return

    def _clear_filters(self) -> None:
        # 활성 인라인 edit 가 있으면 그것 먼저 취소 (변경 안 저장 + 라벨 복귀)
        if self._active_inline_edit_state is not None:
            state = self._active_inline_edit_state
            state["saved"] = True
            self._active_inline_edit_state = None
            QTimer.singleShot(0, self._force_refresh)
            return
        # 그 다음 — 검색/태그 필터 해제
        if self.search.isVisible() or self.search.query():
            self.search.close_bar()
        if self._tag_filter:
            self._tag_filter = ""
            self._force_refresh()

    def _toggle_collapsed(self, project: core.Project) -> None:
        core.toggle_collapsed(self.cfg, project.folder.name)
        self._force_refresh()

    def _toggle_hidden(self, project: core.Project) -> None:
        core.toggle_hidden(self.cfg, project.folder.name)
        self._force_refresh()

    # ------------------------------------------------------------------
    def _persist_geometry(self) -> None:
        """현재 위치/크기를 cfg.widget 에 반영하고 디스크 저장.

        디스크 cfg 의 다른 키(projects, hidden 등)는 안 건드림 — 다시 읽어 병합.
        """
        wcfg = self.cfg.get("widget", {})
        wcfg["x"] = self.x()
        wcfg["y"] = self.y()
        wcfg["width"] = self.width()
        wcfg["height"] = self.height()
        self.cfg["widget"] = wcfg
        try:
            disk = core.load_config()
            disk["widget"] = wcfg
            core.save_config(disk)
        except OSError:
            pass

    def moveEvent(self, e):
        super().moveEvent(e)
        # 처음 show() 이전엔 self.cfg 등 없을 수 있어 attr 가드
        if hasattr(self, "_save_timer"):
            self._save_timer.start(500)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_save_timer"):
            self._save_timer.start(500)

    def closeEvent(self, e):
        """창 닫을 때 — 위치 저장 + 트레이 라벨 동기."""
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._persist_geometry()
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.refresh_label()
        super().closeEvent(e)

    # ------------------------------------------------------------------
    # 글로벌 단축키 핸들러
    def toggle_body_collapse(self) -> None:
        """본문(빠른 입력·검색·스크롤·그립)을 접기/펴기 — 제목줄만 남김."""
        # 스크롤 영역의 visibility 토글
        cur = self.splitter.isVisible()
        new_visible = not cur
        self.splitter.setVisible(new_visible)
        self.quick.setVisible(new_visible)
        self.search.setVisible(new_visible and self.search.isVisible())
        if new_visible:
            # 펴기 — 원래 높이로 복원 (cfg 값 또는 기본)
            wcfg = self.cfg.get("widget", {})
            h = int(wcfg.get("height", 0)) or 640
            self.resize(self.width(), h)
        else:
            # 접기 — 타이틀줄만 보이는 높이로
            self.resize(self.width(), 30)

    def toggle_window_visibility(self) -> None:
        """위젯 창 자체 hide/show 토글 (트레이 단축키와 동일 동작)."""
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.refresh_label()

    def _update_footer_time(self) -> None:
        """푸터 — 시간 + 최근 변경 한 줄을 in-place 로 갱신."""
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        parts = [f"업데이트 {now}"]
        if self._latest_change_text:
            txt = self._latest_change_text
            if len(txt) > 50:
                txt = txt[:48] + "…"
            parts.insert(0, txt)
        self.footer.setText("  ·  ".join(parts))

    def _check_drop_folder(self) -> None:
        """root/_drop/*.json 처리 — 새 항목 있으면 refresh."""
        try:
            added = core.process_drop_folder(self.cfg)
        except OSError:
            added = 0
        if added:
            self._force_refresh()

    def _open_path(self, path: Path) -> None:
        """파일/폴더 열기. 파일은 VS Code 우선 → 기본 핸들러 → notepad 순.

        `.md` 에 핸들러가 등록 안 됐거나 GUI 핸들러가 응답을 안 주는 경우 대비.
        """
        import shutil
        path_str = str(path)

        if path.is_dir():
            try:
                os.startfile(path_str)
                return
            except OSError:
                try:
                    subprocess.Popen(["explorer", path_str])
                except OSError:
                    pass
            return

        if not path.is_file():
            return

        # 1) VS Code (PATH 에 있으면) — 사용자 환경에 따라 cursor 등으로 바꿀 수 있게
        #    Phase 6b 에서 settings 에 editor 옵션 추가 예정
        editor_cmd = shutil.which("code") or shutil.which("cursor")
        if editor_cmd:
            try:
                subprocess.Popen(
                    [editor_cmd, path_str],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return
            except OSError:
                pass
        # 2) 기본 핸들러
        try:
            os.startfile(path_str)
            return
        except OSError:
            pass
        # 3) notepad
        try:
            subprocess.Popen(["notepad", path_str])
        except OSError:
            pass

    def _open_new_project(self) -> None:
        """⊕ 클릭 — 템플릿 선택 가능한 새 프로젝트 다이얼로그."""
        def on_created(folder_name: str) -> None:
            self._force_refresh(just_added_folder=folder_name)

        dlg = NewProjectDialog(self.cfg, self.theme, on_created, parent=self)
        dlg.exec()

    def _open_settings(self) -> None:
        """⚙ 클릭 — 설정 다이얼로그. 저장 시 cfg 갱신 + 새로고침 + 위젯 속성 재적용."""
        dlg = SettingsDialog(
            self.cfg, self.theme, self._apply_settings, parent=self)
        dlg.exec()

    def _apply_settings(self) -> None:
        """Settings 저장 후 — 폭/높이/투명도/최상위/주기를 실제 창에 다시 적용."""
        wcfg = self.cfg.get("widget", {})
        w = int(wcfg.get("width", 440)) or 440
        h = int(wcfg.get("height", 0)) or self.height()
        self.resize(w, h)
        self.setWindowOpacity(
            max(0.4, min(1.0, float(wcfg.get("opacity", 0.96))))
        )
        # topmost 토글 — Qt 의 windowFlags 갱신은 hide/show 필요
        cur = self.windowFlags()
        want_top = bool(wcfg.get("topmost", True))
        is_top = bool(cur & Qt.WindowStaysOnTopHint)
        if want_top != is_top:
            if want_top:
                self.setWindowFlags(cur | Qt.WindowStaysOnTopHint)
            else:
                self.setWindowFlags(cur & ~Qt.WindowStaysOnTopHint)
            self.show()   # flags 적용

        # 새로고침 주기 재시작
        interval = max(5, int(self.cfg.get("refresh_seconds", 30))) * 1000
        self._timer.start(interval)

        # 설정에서 default_quick_project 가 바뀌었을 수도 — 칩/placeholder 갱신
        if hasattr(self, "quick"):
            self.quick._refresh_chip_and_placeholder()

        self._force_refresh()

    def _open_batch_add(self) -> None:
        """⧉ 클릭 — 여러 프로젝트에 할 일/발주 행 일괄 추가."""
        from qt.batch_add import BatchAddDialog
        dlg = BatchAddDialog(
            self.cfg, self.theme,
            on_changed=self._force_refresh, parent=self,
        )
        dlg.exec()

    def _open_orders(self, project: core.Project) -> None:
        """카드 우클릭 → 발주 트래커 다이얼로그."""
        dlg = OrdersDialog(
            project, self.cfg, self.theme,
            on_changed=self._force_refresh, parent=self,
        )
        dlg.exec()

    def _advance_order(self, project: core.Project, name: str) -> None:
        """카드 안 트래커 row 의 체크 클릭 — 다음 미완료 단계 advance.

        모든 단계 완료된 row 면 무동작. orders.json 직접 갱신 + 새로고침.
        """
        try:
            data = core.load_orders(project.folder)
        except OSError:
            return
        stages = core.workflow_stages(self.cfg, data.get("workflow") or "")
        n = len(stages)
        changed = False
        for row in data.get("rows", []):
            if row.get("name") != name:
                continue
            flags = list(row.get("stages") or [])
            if len(flags) < n:
                flags = flags + [False] * (n - len(flags))
            for i in range(n):
                if not flags[i]:
                    flags[i] = True
                    row["stages"] = flags
                    changed = True
                    break
            break
        if not changed:
            return
        try:
            core.save_orders(project.folder, data)
        except OSError:
            return
        self._force_refresh()

    def _open_editor(self, project: core.Project) -> None:
        """카드 더블클릭 → 편집창. 이미 열려 있으면 그 창을 앞으로."""
        key = project.folder.name
        existing = self._editors.get(key)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        editor = ProjectEditor(
            project, self.cfg, self.theme,
            on_change=self._force_refresh, parent=self,
        )
        editor.destroyed.connect(lambda _=None, k=key: self._editors.pop(k, None))
        self._editors[key] = editor
        editor.show()

    def refresh(self) -> None:
        """STATUS.md 들을 다시 읽음. 내용 + 검색 쿼리가 같으면 redraw 스킵.

        redraw 시 스크롤 위치 보존 — 체크 토글로 todo 사라져도 화면이 맨 위로
        튀지 않게. 새 body 의 layout 계산 후 다음 event loop 에 복원.
        """
        projects = core.scan_projects(self.cfg)
        # 가장 최근 변경 한 줄 (last_update 가 가장 큰 프로젝트의 last_change)
        latest = max(projects,
                     key=lambda p: p.last_update or "",
                     default=None)
        if latest is not None and latest.last_change:
            self._latest_change_text = (
                f"{latest.name}: {latest.last_change}"
            )
        else:
            self._latest_change_text = ""
        fp = self._fingerprint(projects)
        if fp == self._last_fp:
            return
        self._last_fp = fp
        sb = self.scroll.verticalScrollBar()
        saved = sb.value() if sb is not None else 0
        self.scroll.setWidget(self._build_body(projects))
        if sb is not None:
            QTimer.singleShot(0, lambda v=saved: sb.setValue(v))

    def _fingerprint(self, projects: list[core.Project]) -> str:
        wcfg = self.cfg.get("widget", {})
        parts = [
            f"q={self.search.query()}",
            f"f={self._tag_filter}",
            f"hx={int(self._hidden_expanded)}",
            f"sd={int(bool(wcfg.get('sort_by_due', False)))}",
            f"sc={int(bool(wcfg.get('show_completed', False)))}",
        ]
        for p in projects:
            parts.append(
                f"{p.folder.name}|{p.name}|{p.note}|{p.due}|"
                f"{p.hidden}|{p.collapsed}|{p.percent}"
            )
            for it in p.items:
                parts.append(f"  {int(it.done)}|{it.text}")
            # orders.json 의 mtime — 트래커 변경도 redraw 트리거
            try:
                op = p.folder / core.ORDERS_FILENAME
                if op.exists():
                    parts.append(f"  o={op.stat().st_mtime}")
            except OSError:
                pass
        return "\n".join(parts)

    def _matches(self, p: core.Project, q: str) -> bool:
        """검색 쿼리 매칭 — 프로젝트 이름·메모·할 일 텍스트 어디라도."""
        if q in p.name.lower() or q in p.note.lower():
            return True
        return any(q in it.text.lower() for it in p.items)

    def _build_body(self, projects: list[core.Project]) -> QWidget:
        """본문 — 글로벌 정렬/완료/태그 헤더 + 카드 + 숨김 섹션."""
        body = _CardDropArea(self.theme, self._reorder_cards)
        v = QVBoxLayout(body)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(8)

        query = self.search.query()
        visible = [p for p in projects if not p.hidden]
        if query:
            visible = [p for p in visible if self._matches(p, query)]
        self._last_visible_order = [p.folder.name for p in visible]

        # 글로벌 헤더 — 정렬/완료보기/태그 통계 (필터 활성 시 배너도)
        self._build_global_header(v, visible, query)

        if not visible:
            msg = (
                f"'{query}' 에 일치하는 프로젝트가 없습니다."
                if query
                else "프로젝트가 없습니다.\n"
                     "root 폴더에 STATUS.md 가 있는 폴더를 만드세요."
            )
            empty = QLabel(msg)
            empty.setStyleSheet(
                f"color: {self.theme['muted']}; font-size: 10pt; padding: 20px;"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            v.addWidget(empty)
        else:
            wcfg = self.cfg.get("widget", {})
            sort_by_due = bool(wcfg.get("sort_by_due", False))
            show_done = bool(wcfg.get("show_completed", False))
            custom_tag_colors = wcfg.get("tag_colors") or {}
            for p in visible:
                od = core.load_orders(p.folder)
                if od.get("rows"):
                    od["_stages"] = core.workflow_stages(
                        self.cfg, od.get("workflow") or "")
                else:
                    od = {}
                v.addWidget(ProjectCard(
                    p, self.theme, self._force_refresh,
                    on_open_editor=self._open_editor,
                    on_toggle_collapsed=self._toggle_collapsed,
                    on_toggle_hidden=self._toggle_hidden,
                    on_open_path=self._open_path,
                    on_toggle_tag_filter=self._toggle_tag_filter,
                    on_todo_dblclick=self._enter_todo_inline_edit,
                    on_open_orders=self._open_orders,
                    on_advance_order=self._advance_order,
                    sort_by_due=sort_by_due,
                    show_completed=show_done,
                    tag_filter=self._tag_filter,
                    item_query=query,
                    tag_colors=custom_tag_colors,
                    orders_data=od,
                ))

        if not query:
            hidden = [p for p in projects if p.hidden]
            if hidden:
                self._build_hidden_section(v, hidden)

        v.addStretch()
        return body

    def _build_global_header(self, parent_layout: QVBoxLayout,
                             visible: list[core.Project], query: str) -> None:
        """본문 위에 정렬/완료보기 토글 + 태그 통계 칩 + 필터 배너."""
        t = self.theme
        wcfg = self.cfg.get("widget", {})
        sort_by_due = bool(wcfg.get("sort_by_due", False))
        show_done = bool(wcfg.get("show_completed", False))
        custom_tag_colors = wcfg.get("tag_colors") or {}

        # 태그 통계 — visible 카드(미펴진 카드 포함) 의 모든 todo 합산
        tag_counts: dict[str, int] = {}
        for p in visible:
            src = p.items if show_done else p.todos
            for it in src:
                for tag in it.tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # 토글 헤더
        head_row = QWidget()
        hl = QHBoxLayout(head_row)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(8)
        hl.addStretch()

        sort_lbl = QLabel("마감순 ✓" if sort_by_due else "마감순")
        sort_lbl.setCursor(Qt.PointingHandCursor)
        sort_lbl.setStyleSheet(self._toggle_link_qss(sort_by_due))
        sort_lbl.setToolTip("카드 안 할 일을 마감일 기준으로 정렬")
        sort_lbl.mousePressEvent = self._on_toggle_sort_due
        hl.addWidget(sort_lbl)

        done_lbl = QLabel("완료보기 ✓" if show_done else "완료보기")
        done_lbl.setCursor(Qt.PointingHandCursor)
        done_lbl.setStyleSheet(self._toggle_link_qss(show_done))
        done_lbl.setToolTip("완료된 항목도 함께 보기")
        done_lbl.mousePressEvent = self._on_toggle_show_completed
        hl.addWidget(done_lbl)
        parent_layout.addWidget(head_row)

        # 태그 통계 칩
        if tag_counts:
            stats_row = QWidget()
            srl = QHBoxLayout(stats_row)
            srl.setContentsMargins(4, 0, 4, 0)
            srl.setSpacing(4)
            for tag, cnt in sorted(tag_counts.items(),
                                   key=lambda x: (-x[1], x[0])):
                bg = tag_color(tag, custom_tag_colors)
                is_active = (self._tag_filter == tag)
                border = (f"2px solid {t['text']}" if is_active
                          else "1px solid transparent")
                chip = QLabel(f"#{tag}·{cnt}")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(
                    f"#{tag} 필터 해제" if is_active
                    else f"#{tag} 로 필터"
                )
                chip.setStyleSheet(
                    f"color: {t['bg']}; font-size: 7pt; font-weight: 700;"
                    f" padding: 1px 5px; background: {bg};"
                    f" border-radius: 3px; border: {border};"
                )
                chip.mousePressEvent = (
                    lambda e, tg=tag: self._toggle_tag_filter(tg)
                    if e.button() == Qt.LeftButton else None
                )
                srl.addWidget(chip)
            srl.addStretch()
            parent_layout.addWidget(stats_row)

        # 필터 활성 배너
        if self._tag_filter:
            banner = QWidget()
            bl = QHBoxLayout(banner)
            bl.setContentsMargins(4, 0, 4, 0)
            bl.setSpacing(6)
            lbl = QLabel(f"필터: #{self._tag_filter}")
            lbl.setStyleSheet(
                f"color: {t['subtext']}; font-size: 8pt;"
            )
            bl.addWidget(lbl)
            clear = QLabel("✕ 해제")
            clear.setCursor(Qt.PointingHandCursor)
            clear.setStyleSheet(
                f"color: {t['accent']}; font-size: 8pt; font-weight: 600;"
            )
            clear.mousePressEvent = lambda e: self._clear_tag_filter()
            bl.addWidget(clear)
            bl.addStretch()
            parent_layout.addWidget(banner)

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        """다른 곳 클릭 시 활성 인라인 edit 를 자동 저장 + 종료.

        QLabel 은 NoFocus 라 일반 클릭으론 edit 가 focusOut 안 함 → editingFinished
        signal 발사 안 됨. application-level eventFilter 로 edit 자체/자식 외 어디든
        클릭 시 강제 finish_in_place + force_refresh.
        """
        if (event.type() == QEvent.MouseButtonPress
                and self._active_inline_edit_state is not None):
            # QWindow 같은 non-Widget 이벤트는 duplicate — Widget 이벤트만 판정
            if not isinstance(obj, QWidget):
                return False
            edit = self._active_inline_edit_state.get("edit")
            try:
                inside = (edit is obj
                          or (edit is not None and edit.isAncestorOf(obj)))
            except RuntimeError:
                inside = False
            if not inside:
                state = self._active_inline_edit_state
                self._active_inline_edit_state = None
                self._finish_inline_edit_in_place(state)
                QTimer.singleShot(0, self._force_refresh)
        return False

    # ------------------------------------------------------------------
    # 카드 안 todo 인라인 편집 — 더블클릭 → QLineEdit swap
    def _enter_todo_inline_edit(self, row: QWidget, lbl: QLabel,
                                proj: core.Project,
                                item: core.TodoItem) -> None:
        """todo 라벨 더블클릭 → QLineEdit 으로 swap, 인라인 편집.

        다른 todo 더블클릭 시 기존 활성 edit 는 자동으로 in-place 종료 (저장 +
        라벨 복귀). Enter / 포커스 아웃 → 저장 + 전체 refresh. Esc → 취소.
        """
        if self._active_inline_edit_state is not None:
            self._finish_inline_edit_in_place(self._active_inline_edit_state)
            self._active_inline_edit_state = None

        h = row.layout()
        if h is None:
            return
        idx = -1
        for i in range(h.count()):
            if h.itemAt(i).widget() is lbl:
                idx = i
                break
        if idx == -1:
            return

        t = self.theme
        edit = QLineEdit(item.text)
        edit.setStyleSheet(
            f"QLineEdit {{ background: {t['inset']}; color: {t['text']};"
            f" border: 1px solid {t['accent']}; border-radius: 3px;"
            f" padding: 2px 5px; font-size: 9pt; }}"
        )

        h.removeWidget(lbl)
        lbl.setParent(None)
        lbl.deleteLater()
        h.insertWidget(idx, edit, 1)
        edit.setFocus()
        edit.selectAll()

        state = {
            "edit": edit, "row": row, "proj": proj, "item": item,
            "saved": False,
        }
        self._active_inline_edit_state = state

        def save_via_signal() -> None:
            try:
                if state["saved"]:
                    return
                state["saved"] = True
                self._save_inline_edit(state)
                if self._active_inline_edit_state is state:
                    self._active_inline_edit_state = None
                QTimer.singleShot(0, self._force_refresh)
            except Exception:
                import traceback
                traceback.print_exc()
                if self._active_inline_edit_state is state:
                    self._active_inline_edit_state = None

        def on_key(e):
            try:
                if e.key() == Qt.Key_Escape:
                    state["saved"] = True
                    if self._active_inline_edit_state is state:
                        self._active_inline_edit_state = None
                    QTimer.singleShot(0, self._force_refresh)
                    return
                QLineEdit.keyPressEvent(edit, e)
            except Exception:
                import traceback
                traceback.print_exc()

        edit.keyPressEvent = on_key
        edit.editingFinished.connect(save_via_signal)

    def _save_inline_edit(self, state: dict) -> None:
        edit = state["edit"]
        item = state["item"]
        proj = state["proj"]
        try:
            new_text = edit.text().strip()
        except RuntimeError:
            return
        if new_text and new_text != item.text:
            try:
                core.rename_item(proj.status_path, item.text, new_text)
            except (OSError, ValueError):
                return
            item.text = new_text

    def _finish_inline_edit_in_place(self, state: dict) -> None:
        """다른 todo 더블클릭 시 — 저장 후 라벨로 복귀. force_refresh 호출 X."""
        if state["saved"]:
            return
        state["saved"] = True
        try:
            self._save_inline_edit(state)
            edit = state["edit"]
            try:
                edit.editingFinished.disconnect()
            except (RuntimeError, TypeError):
                pass
            row = state["row"]
            proj = state["proj"]
            item = state["item"]
            try:
                h = row.layout()
            except RuntimeError:
                return
            if h is None:
                return
            idx = -1
            for i in range(h.count()):
                try:
                    w = h.itemAt(i).widget()
                except RuntimeError:
                    continue
                if w is edit:
                    idx = i
                    break
            if idx == -1:
                return
            new_lbl = self._make_inline_label(row, proj, item)
            h.removeWidget(edit)
            try:
                edit.setParent(None)
                edit.deleteLater()
            except RuntimeError:
                pass
            h.insertWidget(idx, new_lbl, 1)
        except Exception:
            import traceback
            traceback.print_exc()

    def _make_inline_label(self, row: QWidget, proj: core.Project,
                           item: core.TodoItem) -> QLabel:
        """in-place swap 시 새 라벨 — 같은 더블클릭 핸들러 연결."""
        t = self.theme
        _due, after_due = core.extract_first_due(item.text)
        clean = TAG_STRIP_RE.sub("", after_due).strip()
        color = t["muted"] if item.done else t["text"]
        extra = "text-decoration: line-through;" if item.done else ""
        lbl = QLabel(clean)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent; {extra}"
        )
        lbl.setWordWrap(True)
        lbl.setCursor(Qt.IBeamCursor)
        lbl.setToolTip("더블클릭으로 편집")
        lbl.mouseDoubleClickEvent = (
            lambda e, r=row, l=lbl, p=proj, it=item:
            self._enter_todo_inline_edit(r, l, p, it)
            if e.button() == Qt.LeftButton else None
        )
        return lbl

    # ------------------------------------------------------------------
    def _toggle_tag_filter(self, tag: str) -> None:
        """태그 칩 클릭 — 같은 태그면 해제, 다른 태그면 그 태그로 필터."""
        self._tag_filter = "" if self._tag_filter == tag else tag
        self._force_refresh()

    def _clear_tag_filter(self) -> None:
        if self._tag_filter:
            self._tag_filter = ""
            self._force_refresh()

    def _toggle_link_qss(self, on: bool) -> str:
        t = self.theme
        if on:
            return (
                f"color: {t['accent']}; font-size: 8pt; font-weight: 600;"
                f" padding: 2px 6px; background: {t['inset']};"
                f" border-radius: 3px;"
            )
        return (
            f"color: {t['muted']}; font-size: 8pt;"
            f" padding: 2px 6px;"
        )

    def _on_toggle_sort_due(self, e):
        if e.button() == Qt.LeftButton:
            wcfg = self.cfg.get("widget", {})
            wcfg["sort_by_due"] = not bool(wcfg.get("sort_by_due", False))
            self.cfg["widget"] = wcfg
            try:
                disk = core.load_config()
                disk["widget"]["sort_by_due"] = wcfg["sort_by_due"]
                core.save_config(disk)
            except OSError:
                pass
            self._force_refresh()

    def _on_toggle_show_completed(self, e):
        if e.button() == Qt.LeftButton:
            wcfg = self.cfg.get("widget", {})
            wcfg["show_completed"] = not bool(wcfg.get("show_completed", False))
            self.cfg["widget"] = wcfg
            try:
                disk = core.load_config()
                disk["widget"]["show_completed"] = wcfg["show_completed"]
                core.save_config(disk)
            except OSError:
                pass
            self._force_refresh()

    def _build_hidden_section(self, parent_layout: QVBoxLayout,
                              hidden: list[core.Project]) -> None:
        """접힌 헤더 ▶ + 펼치면 각 숨김 프로젝트에 '다시 보이기' 링크."""
        t = self.theme
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            f"color: {t['border']}; background: {t['border']};"
            f" max-height: 1px;"
        )
        parent_layout.addWidget(sep)

        arrow = "▼" if self._hidden_expanded else "▶"
        header = QLabel(f"{arrow}  숨김 {len(hidden)}개")
        header.setCursor(Qt.PointingHandCursor)
        header.setStyleSheet(
            f"color: {t['subtext']}; font-size: 9pt; font-weight: 600;"
            f" padding: 6px 4px 2px 4px;"
        )
        header.setToolTip("클릭으로 펼치기/접기")
        header.mousePressEvent = self._on_hidden_header_click
        parent_layout.addWidget(header)

        if not self._hidden_expanded:
            return

        for hp in hidden:
            row = QWidget()
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip("클릭하면 다시 보이게 됨")
            row.setStyleSheet(
                f"QWidget:hover {{ background: {t['card']};"
                f" border-radius: 4px; }}"
            )
            rh = QHBoxLayout(row)
            rh.setContentsMargins(12, 4, 8, 4)
            rh.setSpacing(8)

            _, clean_name = core.extract_first_due(hp.name)
            name_lbl = QLabel(clean_name)
            name_lbl.setStyleSheet(
                f"color: {t['subtext']}; font-size: 9pt; background: transparent;"
            )
            rh.addWidget(name_lbl, 1)

            act = QLabel("다시 보이기")
            act.setStyleSheet(
                f"color: {t['accent']}; font-size: 8pt; font-weight: 600;"
                f" background: transparent;"
            )
            rh.addWidget(act)

            # 행 전체 클릭으로 해제 — 자식 라벨에는 mouse 이벤트 전파
            row.mousePressEvent = (
                lambda e, p=hp: self._unhide_project(p)
                if e.button() == Qt.LeftButton else None
            )
            parent_layout.addWidget(row)

    def _on_hidden_header_click(self, e):
        if e.button() == Qt.LeftButton:
            self._hidden_expanded = not self._hidden_expanded
            self._force_refresh()
            e.accept()

    def _unhide_project(self, project: core.Project) -> None:
        """숨김 해제 — toggle_hidden 호출."""
        core.toggle_hidden(self.cfg, project.folder.name)
        self._force_refresh()

    def _reorder_cards(self, src_folder: str, insert_index: int) -> None:
        """카드 드래그로 reorder — 새 순서를 cfg.project_order 에 저장 + redraw.

        insert_index 는 '현재 visible 카드들' 안에서의 삽입 위치(0..N).
        검색/필터 중에도 같은 visible 리스트 기준으로 재배치.
        cfg.project_order 는 visible 외 다른 프로젝트도 모두 포함해야 안정적이므로,
        scan_projects 의 전체 순서에서 src 를 빼고 그 위치에 다시 끼움.
        """
        if not hasattr(self, "_last_visible_order"):
            return
        visible = list(self._last_visible_order)
        if src_folder not in visible:
            return
        # visible 내에서 src 제거하고 insert_index 위치에 삽입
        cur = visible.index(src_folder)
        if insert_index > cur:
            insert_index -= 1
        if insert_index == cur:
            return
        visible.remove(src_folder)
        visible.insert(insert_index, src_folder)

        # 전체 순서 = visible(새 순서) + 나머지(기존 순서 유지)
        all_projects = core.scan_projects(self.cfg)
        rest = [p.folder.name for p in all_projects
                if p.folder.name not in visible]
        new_order = visible + rest
        core.set_project_order(self.cfg, new_order)
        self._force_refresh()
