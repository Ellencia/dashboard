"""설정 창 — 위젯 폭/높이/투명도/최상위/주기, manual_project_root 등.

저장 시 manual_project_root 가 바뀌면 후보 프로젝트들을 보여 주는
체크리스트 다이얼로그를 띄워 어떤 폴더를 새 위치로 옮길지 사용자가 선택.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import core
from qt.theme import app_qss, card_qss, input_qss, menu_qss
from qt.titlebar import TitleBar


class _MoveChecklistDialog(QDialog):
    """프로젝트 이동 체크리스트 — manual_project_root 변경 시 띄움."""

    def __init__(self, parent: QWidget, theme: dict,
                 candidates: list[tuple[Path, bool]], dest_path: Path):
        super().__init__(parent)
        self.theme = theme
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme) + card_qss(theme))
        self.resize(460, 440)
        self.setModal(True)

        self._checks: list[tuple[Path, QCheckBox]] = []
        self.selected: list[Path] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, theme, "프로젝트 이동"))

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        head = QLabel("어느 프로젝트들을 새 폴더로 옮길까요?")
        head.setStyleSheet(
            f"color: {theme['text']}; font-size: 11pt; font-weight: 600;"
        )
        v.addWidget(head)
        v.addWidget(self._label(f"새 위치: {dest_path}", theme['subtext'], 8))

        # 전체 선택/해제
        sel_row = QHBoxLayout()
        sel_all = QPushButton("전체 선택")
        sel_all.setStyleSheet(self._link_btn_qss(theme['accent']))
        sel_all.setCursor(Qt.PointingHandCursor)
        sel_all.clicked.connect(lambda: self._set_all(True))
        sel_row.addWidget(sel_all)
        sel_none = QPushButton("전체 해제")
        sel_none.setStyleSheet(self._link_btn_qss(theme['subtext']))
        sel_none.setCursor(Qt.PointingHandCursor)
        sel_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(sel_none)
        sel_row.addStretch()
        v.addLayout(sel_row)

        # 체크리스트 (스크롤)
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
        for folder, default_checked in candidates:
            cb = QCheckBox(folder.name)
            cb.setChecked(default_checked)
            cb.setStyleSheet(self._check_qss(theme))
            lv.addWidget(cb)
            self._checks.append((folder, cb))
        lv.addStretch()
        scroll.setWidget(list_w)
        v.addWidget(scroll, 1)

        # 버튼
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("취소")
        cancel.setStyleSheet(self._btn_qss(theme, accent=False))
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        do = QPushButton("이동")
        do.setStyleSheet(self._btn_qss(theme, accent=True))
        do.clicked.connect(self._accept)
        btn_row.addWidget(do)
        v.addLayout(btn_row)

        outer.addWidget(body, 1)

    def _accept(self) -> None:
        self.selected = [f for f, cb in self._checks if cb.isChecked()]
        self.accept()

    def _set_all(self, value: bool) -> None:
        for _, cb in self._checks:
            cb.setChecked(value)

    @staticmethod
    def _label(text: str, color: str, size: int) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: {size}pt;")
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


class SettingsDialog(QDialog):
    """위젯 설정 — 폭/높이/투명도/최상위/주기 + manual_project_root."""

    def __init__(self, cfg: dict, theme: dict,
                 on_saved: Callable[[], None], parent: QWidget):
        super().__init__(parent)
        self.cfg = cfg
        self.theme = theme
        self.on_saved = on_saved
        self.parent_win = parent

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(app_qss(theme) + card_qss(theme) + menu_qss(theme))
        self.resize(440, 540)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, theme, "설정"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme['bg']}; border: none; }}"
        )
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        wcfg = cfg.get("widget", {})

        # 새로고침 주기
        self.spin_refresh = self._spin_row(
            v, "새로고침 주기 (초)",
            int(cfg.get("refresh_seconds", 30)), 5, 3600)

        # 폭 / 높이
        self.spin_w = self._spin_row(
            v, "창 너비 (px)", int(wcfg.get("width", 440)), 240, 1600)
        self.spin_h = self._spin_row(
            v, "창 높이 (px) — 0=내용 맞춤",
            int(wcfg.get("height", 0)), 0, 2000)

        # 투명도 슬라이더
        self.slider_op, self.lbl_op = self._slider_row(
            v, "투명도 (%)",
            int(round(float(wcfg.get("opacity", 0.96)) * 100)),
            40, 100,
        )

        # 최상위
        self.chk_topmost = self._check_row(
            v, "항상 다른 창 위에 표시",
            bool(wcfg.get("topmost", True)))

        # 빠른 할 일 입력 기본 프로젝트
        v.addSpacing(6)
        v.addWidget(self._section_label("빠른 할 일 입력"))
        v.addWidget(self._label(
            "기본 프로젝트 — 빠른 입력에서 `[프로젝트]` 안 적었을 때 어디로 갈지.\n"
            "비우면 인박스. 입력칸 좌측 칩으로 일회성 변경 가능.",
            theme['muted'], 8,
        ))
        qp_row = QHBoxLayout()
        self.quick_default_combo = QComboBox()
        self.quick_default_combo.addItem("(인박스 — _inbox)", "")
        cur_default = cfg.get("default_quick_project", "")
        try:
            for p in core.scan_projects(cfg):
                if p.folder.name == "_inbox":
                    continue
                self.quick_default_combo.addItem(
                    f"→ {p.name}", p.folder.name)
        except OSError:
            pass
        # 현재 선택 복원
        for i in range(self.quick_default_combo.count()):
            if self.quick_default_combo.itemData(i) == cur_default:
                self.quick_default_combo.setCurrentIndex(i)
                break
        self.quick_default_combo.setStyleSheet(self._combo_qss(theme))
        qp_row.addWidget(self.quick_default_combo, 1)
        v.addLayout(qp_row)

        # 태그 색
        v.addSpacing(6)
        v.addWidget(self._section_label("태그 색"))
        tag_row = QHBoxLayout()
        tag_row.addWidget(self._label(
            "태그 → 색 매핑 편집", theme['muted'], 8,
        ), 1)
        tag_btn = QPushButton("편집...")
        tag_btn.setStyleSheet(self._btn_qss(theme, accent=False))
        tag_btn.setCursor(Qt.PointingHandCursor)
        tag_btn.clicked.connect(self._open_tag_colors)
        tag_row.addWidget(tag_btn)
        v.addLayout(tag_row)

        # 글로벌 단축키
        v.addSpacing(6)
        v.addWidget(self._section_label("전역 단축키"))
        v.addWidget(self._label(
            "예: ctrl+alt+d, ctrl+shift+f9 — 비우면 끔",
            theme['muted'], 8,
        ))
        self.hotkey_collapse = self._text_row(
            v, "접기 / 펴기",
            str(wcfg.get("collapse_hotkey", "")))
        self.hotkey_hide = self._text_row(
            v, "숨기기 / 보이기",
            str(wcfg.get("hide_hotkey", "")))

        # 수동 생성 폴더 (manual_project_root)
        v.addSpacing(6)
        v.addWidget(self._section_label("수동 생성 폴더"))
        v.addWidget(self._label(
            "위젯에서 직접 만드는 프로젝트가 저장될 폴더.\n"
            "비우면 root 와 동일. 코딩 워크스페이스와 분리할 때 유용.",
            theme['muted'], 8,
        ))
        manual_row = QHBoxLayout()
        self.manual_entry = QLineEdit(
            str(cfg.get("manual_project_root", "")))
        self.manual_entry.setStyleSheet(input_qss(theme))
        manual_row.addWidget(self.manual_entry, 1)
        browse = QPushButton("찾기...")
        browse.setStyleSheet(self._btn_qss(theme, accent=False))
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse_manual)
        manual_row.addWidget(browse)
        clear = QPushButton("비우기")
        clear.setStyleSheet(self._btn_qss(theme, accent=False))
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(lambda: self.manual_entry.clear())
        manual_row.addWidget(clear)
        v.addLayout(manual_row)

        v.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 하단 버튼
        bottom = QHBoxLayout()
        bottom.setContentsMargins(16, 8, 16, 12)
        bottom.addStretch()
        cancel = QPushButton("취소")
        cancel.setStyleSheet(self._btn_qss(theme, accent=False))
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        save = QPushButton("저장")
        save.setStyleSheet(self._btn_qss(theme, accent=True))
        save.clicked.connect(self._on_save)
        bottom.addWidget(save)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {self.theme['text']}; font-size: 10pt; font-weight: 600;"
        )
        return lbl

    def _label(self, text: str, color: str, size: int) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: {size}pt;")
        lbl.setWordWrap(True)
        return lbl

    def _text_row(self, parent: QVBoxLayout, label: str,
                  value: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {self.theme['text']}; font-size: 9pt;")
        lbl.setFixedWidth(110)
        row.addWidget(lbl)
        edit = QLineEdit(value)
        edit.setStyleSheet(input_qss(self.theme))
        edit.setFixedWidth(160)
        row.addWidget(edit)
        row.addStretch()
        parent.addLayout(row)
        return edit

    def _spin_row(self, parent: QVBoxLayout, label: str,
                  value: int, lo: int, hi: int) -> QSpinBox:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {self.theme['text']}; font-size: 9pt;"
        )
        row.addWidget(lbl, 1)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(value)
        spin.setStyleSheet(self._spin_qss(self.theme))
        spin.setFixedWidth(90)
        row.addWidget(spin)
        parent.addLayout(row)
        return spin

    def _slider_row(self, parent: QVBoxLayout, label: str,
                    value: int, lo: int, hi: int) -> tuple[QSlider, QLabel]:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {self.theme['text']}; font-size: 9pt;")
        row.addWidget(lbl, 1)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        slider.setFixedWidth(140)
        slider.setStyleSheet(self._slider_qss(self.theme))
        row.addWidget(slider)
        val_lbl = QLabel(f"{value}")
        val_lbl.setFixedWidth(40)
        val_lbl.setStyleSheet(
            f"color: {self.theme['subtext']}; font-size: 9pt;"
        )
        slider.valueChanged.connect(
            lambda v: val_lbl.setText(f"{v}"))
        row.addWidget(val_lbl)
        parent.addLayout(row)
        return slider, val_lbl

    def _check_row(self, parent: QVBoxLayout,
                   label: str, value: bool) -> QCheckBox:
        cb = QCheckBox(label)
        cb.setChecked(value)
        cb.setStyleSheet(_MoveChecklistDialog._check_qss(self.theme))
        parent.addWidget(cb)
        return cb

    def _open_tag_colors(self) -> None:
        from qt.tag_colors import TagColorsDialog

        def on_saved(mapping: dict) -> None:
            wcfg = self.cfg.get("widget", {})
            wcfg["tag_colors"] = mapping
            self.cfg["widget"] = wcfg
            try:
                disk = core.load_config()
                disk["widget"]["tag_colors"] = mapping
                core.save_config(disk)
            except OSError:
                pass

        dlg = TagColorsDialog(self.cfg, self.theme, on_saved, parent=self)
        dlg.exec()

    def _browse_manual(self) -> None:
        current = self.manual_entry.text().strip() or str(
            Path(self.cfg.get("root", ".")).resolve())
        chosen = QFileDialog.getExistingDirectory(
            self, "수동 생성 프로젝트가 저장될 폴더", current)
        if chosen:
            self.manual_entry.setText(chosen)

    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        new_manual = self.manual_entry.text().strip()
        old_manual = (self.cfg.get("manual_project_root") or "").strip()

        # manual_project_root 가 바뀌었으면 이동 후보 체크리스트
        if old_manual != new_manual:
            dest_path = (Path(new_manual).resolve() if new_manual
                         else Path(self.cfg["root"]).resolve())
            root_path = Path(self.cfg["root"]).resolve()
            candidates: list[tuple[Path, bool]] = []
            seen: set = set()
            if old_manual:
                old_path = Path(old_manual).resolve()
                if old_path != dest_path:
                    for p in core.discover_direct_projects(old_path):
                        if p.parent.resolve() == dest_path:
                            continue
                        rp = p.resolve()
                        if rp in seen:
                            continue
                        seen.add(rp)
                        candidates.append((p, True))
            if root_path != dest_path:
                for p in core.discover_direct_projects(root_path):
                    if p.parent.resolve() == dest_path:
                        continue
                    rp = p.resolve()
                    if rp in seen:
                        continue
                    seen.add(rp)
                    candidates.append((p, False))
            if candidates:
                dlg = _MoveChecklistDialog(
                    self, self.theme, candidates, dest_path)
                if dlg.exec() == QDialog.Accepted and dlg.selected:
                    ok, errors = core.move_projects(dlg.selected, dest_path)
                    if errors:
                        QMessageBox.warning(
                            self, "이동 결과",
                            f"성공 {ok}개 / 문제 {len(errors)}개:\n\n"
                            + "\n".join(errors),
                        )

        # cfg 갱신 — disk + 메모리
        try:
            disk = core.load_config()
        except OSError:
            disk = dict(self.cfg)
        disk["refresh_seconds"] = self.spin_refresh.value()
        disk["manual_project_root"] = new_manual
        disk["default_quick_project"] = (
            self.quick_default_combo.currentData() or "")
        self.cfg["default_quick_project"] = disk["default_quick_project"]
        wcfg = disk.get("widget", {})
        wcfg["width"] = self.spin_w.value()
        wcfg["height"] = self.spin_h.value()
        wcfg["opacity"] = round(self.slider_op.value() / 100, 2)
        wcfg["topmost"] = self.chk_topmost.isChecked()
        wcfg["collapse_hotkey"] = self.hotkey_collapse.text().strip()
        wcfg["hide_hotkey"] = self.hotkey_hide.text().strip()
        disk["widget"] = wcfg
        try:
            core.save_config(disk)
        except OSError:
            pass
        self.cfg["refresh_seconds"] = disk["refresh_seconds"]
        self.cfg["manual_project_root"] = new_manual
        self.cfg["widget"] = wcfg

        self.on_saved()
        self.accept()

    # ------------------------------------------------------------------
    @staticmethod
    def _btn_qss(t: dict, accent: bool) -> str:
        return _MoveChecklistDialog._btn_qss(t, accent)

    @staticmethod
    def _spin_qss(t: dict) -> str:
        return (
            f"QSpinBox {{ background: {t['card']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; border-radius: 3px;"
            f" padding: 3px 6px; }}"
            f"QSpinBox:focus {{ border: 1px solid {t['accent']}; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{"
            f" background: {t['inset']}; width: 14px; }}"
            f"QSpinBox::up-arrow {{ image: none; border-left: 4px solid transparent;"
            f" border-right: 4px solid transparent;"
            f" border-bottom: 5px solid {t['subtext']}; }}"
            f"QSpinBox::down-arrow {{ image: none; border-left: 4px solid transparent;"
            f" border-right: 4px solid transparent;"
            f" border-top: 5px solid {t['subtext']}; }}"
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

    @staticmethod
    def _slider_qss(t: dict) -> str:
        return (
            f"QSlider::groove:horizontal {{ background: {t['inset']};"
            f" height: 5px; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {t['accent']};"
            f" width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}"
            f"QSlider::sub-page:horizontal {{ background: {t['accent']};"
            f" border-radius: 2px; }}"
        )
