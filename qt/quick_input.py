"""빠른 입력 위젯 — 단일 입력칸 + 할일/프로젝트 모드 토글.

상단의 입력 한 줄에서 두 가지 모두 가능:
- 할일 모드: 좌측 대상 칩(default 프로젝트) + 입력 → core.add_quick_todo
- 프로젝트 모드: 입력 → core.create_project (manual_project_parent)

단축키: Ctrl+T 할일 모드 포커스, Ctrl+N 프로젝트 모드 포커스.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QWidget

import core
from qt.theme import input_qss, menu_qss


class QuickUnifiedInput(QWidget):
    """단일 입력칸 + [할일 | 프로젝트] segmented 토글."""

    _INBOX_LABEL = "인박스"
    _CFG_KEY = "default_quick_project"

    def __init__(self, cfg: dict, theme: dict,
                 on_change: Callable[..., None]):
        super().__init__()
        self.cfg = cfg
        self.theme = theme
        self.on_change = on_change
        self._mode: str = "todo"

        self.setStyleSheet(f"background: {theme['bg']};")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 12, 4)
        h.setSpacing(4)

        # 모드 segmented
        self.mode_todo_lbl = QLabel("✎ 할일")
        self.mode_todo_lbl.setCursor(Qt.PointingHandCursor)
        self.mode_todo_lbl.setToolTip("할 일 모드 (Ctrl+T)")
        self.mode_todo_lbl.mousePressEvent = lambda e: (
            self._set_mode("todo") if e.button() == Qt.LeftButton else None
        )
        h.addWidget(self.mode_todo_lbl)

        self.mode_proj_lbl = QLabel("⊕ 프로젝트")
        self.mode_proj_lbl.setCursor(Qt.PointingHandCursor)
        self.mode_proj_lbl.setToolTip("새 프로젝트 모드 (Ctrl+N)")
        self.mode_proj_lbl.mousePressEvent = lambda e: (
            self._set_mode("project") if e.button() == Qt.LeftButton else None
        )
        h.addWidget(self.mode_proj_lbl)

        # 대상 칩 — 할일 모드에서만 보임
        self.dest_chip = QLabel()
        self.dest_chip.setCursor(Qt.PointingHandCursor)
        self.dest_chip.setToolTip("기본 대상 프로젝트 (클릭으로 변경)")
        self.dest_chip.mousePressEvent = self._on_chip_click
        h.addWidget(self.dest_chip)

        self.entry = QLineEdit()
        self.entry.setStyleSheet(input_qss(theme))
        self.entry.returnPressed.connect(self._submit)
        h.addWidget(self.entry, 1)

        self._refresh_mode()
        self._refresh_chip_and_placeholder()

    # ------------------------------------------------------------------
    def focus_todo(self) -> None:
        self._set_mode("todo")
        self.entry.setFocus()
        self.entry.selectAll()

    def focus_project(self) -> None:
        self._set_mode("project")
        self.entry.setFocus()
        self.entry.selectAll()

    def focus(self) -> None:
        """기존 호환 — 할일 모드로."""
        self.focus_todo()

    # ------------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        if mode not in ("todo", "project"):
            return
        self._mode = mode
        self._refresh_mode()
        self._refresh_chip_and_placeholder()

    def _refresh_mode(self) -> None:
        t = self.theme
        active_qss = (
            f"color: {t['bg']}; background: {t['accent']};"
            f" font-size: 8pt; font-weight: 700;"
            f" padding: 3px 8px; border-radius: 3px;"
        )
        inactive_qss = (
            f"color: {t['muted']}; background: transparent;"
            f" font-size: 8pt; font-weight: 600;"
            f" padding: 3px 8px; border-radius: 3px;"
        )
        self.mode_todo_lbl.setStyleSheet(
            active_qss if self._mode == "todo" else inactive_qss
        )
        self.mode_proj_lbl.setStyleSheet(
            active_qss if self._mode == "project" else inactive_qss
        )
        # 대상 칩 visibility
        self.dest_chip.setVisible(self._mode == "todo")

    # ------------------------------------------------------------------
    def _current_default(self) -> tuple[str, str]:
        """(folder_name, 표시 이름) — cfg.default_quick_project 우선."""
        folder = (self.cfg.get(self._CFG_KEY, "") or "").strip()
        if not folder:
            return "", self._INBOX_LABEL
        for p in core.scan_projects(self.cfg):
            if p.folder.name == folder:
                return folder, p.name or folder
        return "", self._INBOX_LABEL

    def _refresh_chip_and_placeholder(self) -> None:
        t = self.theme
        if self._mode == "todo":
            folder, display = self._current_default()
            is_custom = bool(folder)
            bg = t["accent"] if is_custom else t["inset"]
            fg = t["bg"] if is_custom else t["subtext"]
            self.dest_chip.setText(f"→ {display}  ▾")
            self.dest_chip.setStyleSheet(
                f"color: {fg}; background: {bg}; font-size: 8pt;"
                f" font-weight: 600; padding: 2px 6px; border-radius: 3px;"
            )
            self.entry.setPlaceholderText(
                f"할 일 #태그 !마감 — Enter   (→ {display})"
            )
        else:
            self.entry.setPlaceholderText(
                "새 프로젝트 이름 — Enter   (manual_project_root 에 생성)"
            )

    # ------------------------------------------------------------------
    def _on_chip_click(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss(self.theme))
        menu.addAction(
            f"→ {self._INBOX_LABEL}",
            lambda: self._set_default(""),
        )
        menu.addSeparator()
        projects = [
            p for p in core.scan_projects(self.cfg)
            if p.folder.name != "_inbox"
        ]
        for p in projects:
            menu.addAction(
                f"→ {p.name}",
                lambda f=p.folder.name: self._set_default(f),
            )
        gpos = self.dest_chip.mapToGlobal(
            self.dest_chip.rect().bottomLeft())
        menu.exec(gpos)

    def _set_default(self, folder: str) -> None:
        """cfg.default_quick_project 영구 갱신 + 디스크 반영."""
        self.cfg[self._CFG_KEY] = folder
        try:
            disk = core.load_config()
            disk[self._CFG_KEY] = folder
            core.save_config(disk)
        except OSError:
            pass
        self._refresh_chip_and_placeholder()
        self.entry.setFocus()

    # ------------------------------------------------------------------
    def _submit(self) -> None:
        text = self.entry.text().strip()
        if not text:
            return
        if self._mode == "todo":
            self._submit_todo(text)
        else:
            self._submit_project(text)

    def _submit_todo(self, text: str) -> None:
        has_explicit = text.startswith("[") and "]" in text
        if not has_explicit:
            folder, _ = self._current_default()
            if folder:
                text = f"[{folder}] {text}"
        try:
            result = core.add_quick_todo(self.cfg, text)
        except OSError:
            return
        if result is None:
            return
        self.entry.clear()
        self.on_change()

    def _submit_project(self, name: str) -> None:
        folder = core.safe_folder_name(name)
        if not folder:
            return
        parent = core.manual_project_parent(self.cfg)
        if (parent / folder).exists():
            return
        try:
            core.create_project(parent, folder, name)
        except OSError:
            return
        # 펼친 상태 + 인박스 다음 위치 등록 → 사용자가 즉시 봄
        core.register_new_project(self.cfg, folder)
        self.entry.clear()
        self.on_change(just_added_folder=folder)
