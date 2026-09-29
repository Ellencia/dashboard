"""시스템 트레이 아이콘 — 위젯 보이기/숨기기 + 진행률 표시.

QSystemTrayIcon 기본 제공이라 pystray 같은 외부 라이브러리 불필요.
아이콘은 도넛 모양 + 가운데 % 텍스트로 그려 진행률 시각화.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

import core
from qt.theme import menu_qss


def _render_icon(percent: int, theme: dict, size: int = 64) -> QIcon:
    """도넛 진행률 아이콘 — 가운데 % 텍스트."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    rect = QRect(4, 4, size - 8, size - 8)

    # 배경 트랙
    pen = QPen(QColor(theme["inset"]))
    pen.setWidth(6)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawArc(rect, 0, 360 * 16)

    # 진행률 — 12시 방향(90°)에서 시작, 시계방향
    if percent > 0:
        pen.setColor(QColor(theme["accent"]))
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, -int(percent * 360 / 100) * 16)

    # 가운데 % 텍스트
    p.setPen(QColor(theme["text"]))
    font = QFont()
    font.setPointSize(int(size * 0.28))
    font.setBold(True)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignCenter, f"{percent}")
    p.end()
    return QIcon(pix)


class DashboardTray(QSystemTrayIcon):
    """트레이 아이콘 — 좌클릭 위젯 토글, 우클릭 메뉴.

    Args:
        window: 토글 대상 메인 위젯
        cfg: 진행률 계산용 (load_config 결과)
        theme: 아이콘/메뉴 색
        on_open_settings: 설정 메뉴 → 다이얼로그
        on_quit: 진짜 종료 (QApplication.quit)
    """

    def __init__(
        self,
        window: QWidget,
        cfg: dict,
        theme: dict,
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        super().__init__()
        self.window_ref = window
        self.cfg = cfg
        self.theme = theme

        self.setToolTip("프로젝트 보드")
        self._refresh_icon()

        # 메뉴 — 다크 톤
        menu = QMenu()
        menu.setStyleSheet(menu_qss(theme))
        self._act_show = QAction("위젯 보이기", menu)
        self._act_show.triggered.connect(self._on_toggle_window)
        menu.addAction(self._act_show)
        menu.addSeparator()
        act_settings = QAction("설정...", menu)
        act_settings.triggered.connect(on_open_settings)
        menu.addAction(act_settings)
        menu.addSeparator()
        act_quit = QAction("종료", menu)
        act_quit.triggered.connect(on_quit)
        menu.addAction(act_quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

        # 30초마다 진행률 아이콘 갱신
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_icon)
        self._timer.start(30_000)

    # ------------------------------------------------------------------
    def _on_activated(self, reason) -> None:
        """좌클릭(Trigger) — 위젯 토글. 더블클릭도 동일."""
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_toggle_window()

    def _on_toggle_window(self) -> None:
        win = self.window_ref
        if win.isVisible() and not win.isMinimized():
            win.hide()
            self._act_show.setText("위젯 보이기")
        else:
            win.showNormal()
            win.raise_()
            win.activateWindow()
            self._act_show.setText("위젯 숨기기")

    def refresh_label(self) -> None:
        """창 visible 상태에 맞춰 메뉴 라벨 동기."""
        self._act_show.setText(
            "위젯 숨기기" if self.window_ref.isVisible() else "위젯 보이기"
        )

    def _refresh_icon(self) -> None:
        """전체 진행률 계산해 아이콘 다시 그림."""
        try:
            projects = [p for p in core.scan_projects(self.cfg) if not p.hidden]
            done = sum(p.done for p in projects)
            total = sum(p.total for p in projects)
            percent = round(done / total * 100) if total else 0
        except OSError:
            percent = 0
        self.setIcon(_render_icon(percent, self.theme))
        self.setToolTip(
            f"프로젝트 보드 — 진행 {percent}%"
        )
