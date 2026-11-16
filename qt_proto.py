"""PySide6 마이그레이션용 프로토타입.

부드러움 확인이 목적 — 더미 데이터로 카드 5개, 우하단 QSizeGrip 으로 리사이즈,
상단 바 드래그로 이동. core.py 와는 일단 분리, Qt 본연의 반응성만 확인.

실행:
    C:/Programming_STC/PPS/pps_venv/Scripts/python.exe qt_proto.py
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

# Tokyo-Night 톤
T = {
    "bg": "#1a1b26",
    "bg_alt": "#24283b",
    "card": "#2e3247",
    "text": "#c0caf5",
    "subtext": "#7aa2f7",
    "accent": "#bb9af7",
    "muted": "#565f89",
    "border": "#414868",
    "danger": "#f7768e",
}


class TitleBar(QWidget):
    """창 이동 드래그 + 닫기 버튼."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_win = parent
        self.setFixedHeight(30)
        self.setStyleSheet(f"background: {T['bg']};")
        self._drag_pos = None

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 4, 0)
        h.setSpacing(6)

        title = QLabel("프로젝트 보드 — Qt 프로토타입")
        title.setStyleSheet(f"color: {T['text']}; font-size: 10pt; font-weight: 600;")
        h.addWidget(title)
        h.addStretch()

        hint = QLabel("← 끌어서 이동, ↘ 우하단 그립으로 리사이즈")
        hint.setStyleSheet(f"color: {T['muted']}; font-size: 8pt;")
        h.addWidget(hint)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 22)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T['subtext']};"
            f" border: none; font-size: 11pt; }}"
            f"QPushButton:hover {{ color: {T['danger']}; }}"
        )
        close_btn.clicked.connect(parent.close)
        h.addWidget(close_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint()
                - self.parent_win.frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.parent_win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()


class ProjectCard(QFrame):
    """더미 프로젝트 카드 — 제목, 진행률 바, 할 일 행."""

    def __init__(self, name: str, percent: int, todos: list[tuple[str, bool]]):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ background: {T['card']}; border-radius: 8px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        title = QLabel(name)
        title.setStyleSheet(
            f"color: {T['text']}; font-size: 11pt; font-weight: 600;"
        )
        title.setWordWrap(True)
        head_row.addWidget(title, 1)
        pct_lbl = QLabel(f"{percent}%")
        pct_lbl.setStyleSheet(
            f"color: {T['subtext']}; font-size: 9pt; font-weight: 600;"
        )
        head_row.addWidget(pct_lbl)
        v.addLayout(head_row)

        bar = QProgressBar()
        bar.setValue(percent)
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {T['bg_alt']}; border-radius: 3px; border: none; }}"
            f"QProgressBar::chunk {{ background: {T['accent']}; border-radius: 3px; }}"
        )
        v.addWidget(bar)

        for text, done in todos:
            row = QHBoxLayout()
            row.setSpacing(8)
            mark = QLabel("☑" if done else "☐")
            mark.setStyleSheet(
                f"color: {T['accent'] if done else T['subtext']}; font-size: 11pt;"
            )
            row.addWidget(mark)
            lbl = QLabel(text)
            color = T["muted"] if done else T["text"]
            extra = "text-decoration: line-through;" if done else ""
            lbl.setStyleSheet(f"color: {color}; font-size: 9pt; {extra}")
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            v.addLayout(row)


class MainWidget(QWidget):
    """전체 — frameless + 자체 타이틀 + 스크롤 + 우하단 QSizeGrip."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setStyleSheet(f"background: {T['bg']};")
        self.resize(440, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(TitleBar(self))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {T['bg']}; border: none; }}"
            f"QScrollBar:vertical {{ background: {T['bg']}; width: 8px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {T['border']};"
            f" border-radius: 4px; min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {T['subtext']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}"
        )

        body = QWidget()
        body.setStyleSheet(f"background: {T['bg']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(8)

        bl.addWidget(
            ProjectCard(
                "buyflow — 구매팀 도구",
                67,
                [
                    ("DB 익명화 사본 만들기", True),
                    ("페이지 컨테이너 정리", True),
                    ("KC/KS 인증 흐름 통합", False),
                    ("점진적 이카운트 대체 플랜", False),
                ],
            )
        )
        bl.addWidget(
            ProjectCard(
                "대시보드 위젯 — Qt 마이그레이션",
                15,
                [
                    ("PySide6 프로토타입", True),
                    ("ProjectCard 위젯 구현", False),
                    ("TodoRow + 인라인 편집", False),
                    ("자연어 마감 파싱 연결", False),
                ],
            )
        )
        bl.addWidget(
            ProjectCard(
                "강진광주선 본선 및 터널 VMS",
                30,
                [
                    ("도면 검토", True),
                    ("자재 명세 확정", False),
                    ("생산 일정 협의", False),
                ],
            )
        )
        bl.addWidget(
            ProjectCard(
                "세종천안선 2공구 VMS",
                0,
                [
                    ("초기 도면 입수", False),
                    ("자재 단가 조사", False),
                    ("BOM 산출", False),
                ],
            )
        )
        bl.addWidget(
            ProjectCard(
                "강창학 야구장 전광판",
                100,
                [
                    ("설치 완료", True),
                    ("최종 검수", True),
                ],
            )
        )
        bl.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 우하단 사이즈 그립 — Qt 내장, OS 레벨 리사이즈 사용
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setStyleSheet(f"background: transparent;")
        grip_row.addWidget(grip)
        outer.addLayout(grip_row)


def main() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("맑은 고딕", 9))
    w = MainWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
