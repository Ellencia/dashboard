"""프로젝트 대시보드 - 위젯 모드.

화면 위에 항상 떠 있는 작은 창. 프로젝트별 진행률과 할 일을 보여주고,
할 일을 클릭하면 해당 STATUS.md 파일의 체크 상태가 바로 바뀜.

조작법:
  - 제목 표시줄을 끌어서 창 이동
  - 제목 표시줄 우클릭 → 메뉴(새로고침 / 테마 전환 / 설정 열기 / 종료)
  - 할 일 줄 클릭 → 완료/미완료 토글
  - '할 일' 헤더 클릭 → 할 일 목록 접기 / 펴기
  - 프로젝트 이름 클릭 → 해당 STATUS.md 파일 열기
  - 카드 ▾ 화살표 클릭 → 카드 접기 / 펴기
  - 프로젝트 카드 우클릭 → 접기 / 숨기기 / 파일 열기
  - 헤더 ⚙ 버튼 → 설정 창 (테마·투명도·너비·색 강조 등)
"""
from __future__ import annotations

import os
import queue
import tkinter as tk
from datetime import datetime
from pathlib import Path

from core import (
    BASE_DIR,
    CONFIG_PATH,
    load_config,
    reorder_items,
    save_config,
    scan_projects,
    set_project_order,
    toggle_collapsed,
    toggle_hidden,
    toggle_item,
)
from hotkey import GlobalHotkey
import editor
import singleton

FONT = "Malgun Gothic"   # 윈도우 기본 한글 폰트
TITLEBAR_H = 34          # 제목 표시줄 높이(px)

# 색상 테마 (다크 / 라이트)
THEMES = {
    "dark": {
        "bg": "#1e1e2e",
        "card": "#2a2a3c",
        "titlebar": "#181825",
        "text": "#e4e4ef",
        "subtext": "#9a9ab0",
        "accent": "#7aa2f7",
        "bar_bg": "#3a3a4e",
        "btn_hover": "#33334a",
        "highlight": "#f2a541",
    },
    "light": {
        "bg": "#fdf6e3",
        "card": "#ffffff",
        "titlebar": "#efe7cf",
        "text": "#3a3a44",
        "subtext": "#8a8a8a",
        "accent": "#2f6fed",
        "bar_bg": "#e6ddc4",
        "btn_hover": "#e3d9bd",
        "highlight": "#e8890c",
    },
}


def bar_color(percent: int) -> str:
    """진행률에 따른 진행바 색상 (낮을수록 분홍, 높을수록 초록)."""
    if percent >= 100:
        return "#9ece6a"   # 초록 - 완료
    if percent >= 60:
        return "#7aa2f7"   # 파랑 - 순항
    if percent >= 30:
        return "#e0af68"   # 노랑 - 진행 중
    return "#f7768e"        # 분홍 - 초기


class _Tooltip:
    """위젯에 마우스를 올리면 잠깐 떠서 설명을 보여주는 풍선."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        # add="+" : 위젯에 이미 걸린 다른 Enter/Leave 동작을 덮어쓰지 않도록
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 3
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#3a3a4e", fg="#ffffff",
                 font=(FONT, 8), padx=6, pady=3).pack()

    def _hide(self, _event=None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class _PopupMenu:
    """위젯 테마에 맞춘 다크 팝업 메뉴 (tk.Menu의 흰 네이티브 메뉴 대체).

    tk.Menu는 운영체제가 그리는 흰색 메뉴라 다크 테마와 어울리지 않음.
    이 클래스는 overrideredirect Toplevel에 라벨을 쌓아 직접 메뉴를 그림.
    사용법: add()/add_separator()로 항목을 채운 뒤 popup(x, y) 호출.
    """

    def __init__(self, parent: tk.Widget, theme: dict) -> None:
        self.parent = parent
        self.theme = theme
        self.items: list = []   # (label, command) 또는 None(구분선)

    def add(self, label: str, command) -> None:
        self.items.append((label, command))

    def add_separator(self) -> None:
        self.items.append(None)

    def popup(self, x: int, y: int) -> None:
        t = self.theme
        win = tk.Toplevel(self.parent)
        win.overrideredirect(True)              # 창틀 제거
        win.attributes("-topmost", True)
        win.configure(bg=t["bar_bg"])           # 1px 테두리 색

        body = tk.Frame(win, bg=t["card"])
        body.pack(padx=1, pady=1)               # padx/pady 1 → 테두리 효과

        for item in self.items:
            if item is None:
                # 구분선 — 얇은 가로줄
                tk.Frame(body, bg=t["bar_bg"], height=1).pack(
                    fill="x", padx=6, pady=3)
                continue
            label, command = item
            row = tk.Label(body, text=label, bg=t["card"], fg=t["text"],
                           font=(FONT, 9), anchor="w", padx=16, pady=5,
                           cursor="hand2")
            row.pack(fill="x")
            # 마우스 올리면 강조색, 벗어나면 원래색
            row.bind("<Enter>",
                     lambda e, r=row: r.configure(bg=t["accent"], fg="#ffffff"))
            row.bind("<Leave>",
                     lambda e, r=row: r.configure(bg=t["card"], fg=t["text"]))
            row.bind("<Button-1>",
                     lambda e, c=command: (win.destroy(), c()))

        win.bind("<Escape>", lambda e: win.destroy())

        # 화면 밖으로 나가지 않게 위치 보정
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = max(0, min(x, win.winfo_screenwidth() - w - 4))
        y = max(0, min(y, win.winfo_screenheight() - h - 4))
        win.geometry(f"+{x}+{y}")
        win.focus_force()

        # 다른 곳을 클릭하면(포커스 잃으면) 닫힘.
        # 단, 띄운 직후엔 focus_force가 끝나기 전이라 잠깐 뒤에 연결.
        def _arm() -> None:
            try:
                win.bind("<FocusOut>", lambda e: win.destroy())
            except tk.TclError:
                pass

        win.after(60, _arm)


class _DragReorder:
    """세로로 쌓인 행들을 '드래그 핸들'로 끌어 순서를 바꾸는 기능.

    한 '그룹'(예: 프로젝트 카드들, 또는 한 프로젝트의 할 일들) 안에서만
    순서가 바뀜. 다른 그룹으로는 넘어가지 못함 — 그룹마다 _DragReorder를
    따로 만들기 때문. 드래그가 끝나면 on_reorder(새 순서 리스트)를 호출함.

    사용법:
        drag = _DragReorder(body, theme)
        drag.add_row(handle_widget, row_widget, payload)   # 행마다
        drag.on_reorder = lambda new_payloads: ...
    body: 좌표 기준이자 삽입 표시선을 올릴 컨테이너 (스크롤 캔버스 안의 프레임).
    """

    def __init__(self, body: tk.Frame, theme: dict) -> None:
        self.body = body
        self.theme = theme
        self.rows: list = []            # [(row_widget, payload)] — 표시 순서대로
        self.on_reorder = None
        self._line: tk.Frame | None = None   # 삽입 위치 표시선
        self._drag_row = None
        self._start_y = 0
        self._dragging = False

    def add_row(self, handle: tk.Widget, row: tk.Widget, payload) -> None:
        """드래그 가능한 행 하나를 등록 (handle을 잡고 끌면 row가 움직임)."""
        self.rows.append((row, payload))
        handle.bind("<Button-1>", lambda e, r=row: self._press(e, r))
        handle.bind("<B1-Motion>", self._motion)
        handle.bind("<ButtonRelease-1>", self._release)

    # ---- 내부 동작 ----
    def _press(self, event, row) -> None:
        self._drag_row = row
        self._start_y = event.y_root
        self._dragging = False

    def _motion(self, event) -> None:
        if self._drag_row is None:
            return
        if not self._dragging:
            # 5px 미만으로 움직인 건 드래그로 안 봄 (손 떨림 무시)
            if abs(event.y_root - self._start_y) < 5:
                return
            self._dragging = True
        try:
            self._show_line(self._target_index(event.y_root))
        except tk.TclError:
            pass   # 드래그 도중 새로고침으로 위젯이 사라진 경우

    def _release(self, event) -> None:
        target = None
        if self._drag_row is not None and self._dragging:
            try:
                target = self._target_index(event.y_root)
            except tk.TclError:
                target = None
        self._clear_line()   # 새로고침으로 body가 지워지기 전에 먼저 정리
        if target is not None:
            self._drop(target)
        self._drag_row = None
        self._dragging = False

    def _target_index(self, y_root: int) -> int:
        """마우스 y가 몇 번째 자리인지 (0 ~ 행 개수)."""
        body_y = y_root - self.body.winfo_rooty()
        idx = 0
        for row, _ in self.rows:
            if body_y > row.winfo_y() + row.winfo_height() / 2:
                idx += 1
        return idx

    def _gap_y(self, index: int) -> int:
        """index번째 자리(행과 행 사이)의 y좌표."""
        if index < len(self.rows):
            return self.rows[index][0].winfo_y()
        last = self.rows[-1][0]
        return last.winfo_y() + last.winfo_height()

    def _show_line(self, index: int) -> None:
        """삽입될 위치에 강조색 가로선을 표시."""
        if self._line is None:
            self._line = tk.Frame(self.body, bg=self.theme["accent"], height=2)
        self._line.place(x=10, y=max(0, self._gap_y(index) - 1),
                         width=max(1, self.body.winfo_width() - 20))
        self._line.lift()

    def _clear_line(self) -> None:
        if self._line is not None:
            try:
                self._line.destroy()
            except tk.TclError:
                pass
            self._line = None

    def _drop(self, target: int) -> None:
        """드래그한 행을 target 자리로 옮긴 새 순서를 on_reorder로 알림."""
        order = [payload for _, payload in self.rows]
        orig = next(i for i, (row, _) in enumerate(self.rows)
                    if row is self._drag_row)
        if target > orig:
            target -= 1   # 자기 자신을 빼고 나면 뒤쪽 인덱스가 하나 당겨짐
        if target == orig:
            return        # 제자리면 아무것도 안 함
        item = order.pop(orig)
        order.insert(target, item)
        if self.on_reorder is not None:
            self.on_reorder(order)


class DashboardWidget:
    """항상 위에 떠 있는 대시보드 창 한 개."""

    def __init__(self, show_q=None) -> None:
        self.cfg = load_config()
        self.wcfg = self.cfg["widget"]
        theme_name = self.wcfg.get("theme", "dark")
        self.theme = THEMES.get(theme_name, THEMES["dark"])
        self.width = int(self.wcfg.get("width", 340))

        self.collapsed = False        # 접힘 상태
        self.restart = False          # 테마 전환 시 창을 다시 띄우기 위한 플래그
        self.hidden_expanded = False  # 맨 아래 '숨김' 목록 펼침 상태
        self._after_id: str | None = None
        self._hotkey_after: str | None = None
        self._show_q = show_q   # 중복 실행 시 '띄우기' 신호 큐 (없으면 None)
        self._settings_win: tk.Toplevel | None = None
        self._icon_buttons: list[tk.Label] = []
        self._todo_canvas: tk.Canvas | None = None   # 할 일 영역 내부 스크롤
        # 깜빡임 방지: 마지막으로 그린 내용의 지문 — 같으면 redraw 건너뜀
        self._last_draw_fp = None
        self._footer_label: tk.Label | None = None
        # 설정 시 ✕가 종료 대신 이 콜백을 호출 (트레이 모드에서 '숨기기'로 씀)
        self.on_close_override = None
        # 닫기/열기 단축키의 동작 (None이면 위젯 창 자체를 숨김/표시)
        self.hide_action = None
        self._window_hidden = False   # 닫기/열기로 창을 숨긴 상태인지
        # 제목 표시줄의 현재 색 (접힘 색 강조 시 바뀜)
        self._titlebar_bg = self.theme["titlebar"]
        self._titlebar_fg = self.theme["subtext"]

        # --- 창 기본 설정 ---
        self.root = tk.Tk()
        self.root.title("프로젝트 보드")
        self.root.overrideredirect(True)   # 윈도우 기본 창틀 제거
        self.root.attributes("-topmost", bool(self.wcfg.get("topmost", True)))
        self.root.attributes("-alpha", float(self.wcfg.get("opacity", 0.96)))
        self.root.configure(bg=self.theme["bg"])
        x = int(self.wcfg.get("x", 60))
        y = int(self.wcfg.get("y", 60))
        self.root.geometry(f"{self.width}x400+{x}+{y}")

        self._build_titlebar()
        self._build_scroll_area()
        self._build_resize_grip()

        # 마우스 휠로 스크롤
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        # Alt+F4 등으로 닫혀도 창 위치를 저장하도록
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh()

        # 전역 단축키 (보드 접기/펴기). 눌리면 큐에 신호 → poll이 처리
        self._hotkey_q: queue.Queue = queue.Queue()
        self._hotkey_collapse = GlobalHotkey(
            self.wcfg.get("collapse_hotkey", ""),
            lambda: self._hotkey_q.put("collapse"))
        self._hotkey_hide = GlobalHotkey(
            self.wcfg.get("hide_hotkey", ""),
            lambda: self._hotkey_q.put("hide"))
        self._hotkey_collapse.start()
        self._hotkey_hide.start()
        self._hotkey_after = self.root.after(120, self._hotkey_poll)

    # ------------------------------------------------------------------
    # 화면 뼈대 만들기
    # ------------------------------------------------------------------
    def _build_titlebar(self) -> None:
        t = self.theme
        bar = tk.Frame(self.root, bg=t["titlebar"], height=TITLEBAR_H)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.titlebar = bar

        # 왼쪽: 핀(항상 위 고정) 토글 버튼
        self.pin_btn = tk.Label(bar, text="📌", bg=t["titlebar"],
                                font=(FONT, 11), width=3, cursor="hand2")
        self.pin_btn.pack(side="left")
        self.pin_btn.bind("<Button-1>", lambda e: self._toggle_pin())
        _Tooltip(self.pin_btn, "항상 위에 고정 — 켜기 / 끄기")
        self._update_pin_icon()

        self.title_label = tk.Label(bar, text="프로젝트 보드", bg=t["titlebar"],
                                    fg=t["text"], font=(FONT, 10, "bold"))
        self.title_label.pack(side="left", padx=(0, 10))

        # 오른쪽 버튼들 (닫기 → 접기 → 설정 → 새로고침 순서로 오른쪽부터 채움)
        self._icon_button(bar, "✕", self._on_close, tip="닫기", hover="#e0556b")
        self._icon_button(bar, "—", self._toggle_collapse, tip="접기 / 펴기")
        self._icon_button(bar, "⚙", self._open_settings, tip="설정")
        self._icon_button(bar, "↻", self.refresh, tip="새로고침")

        # 제목 표시줄 드래그로 창 이동
        for w in (bar, self.title_label):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<Button-3>", self._show_menu)

        # 우클릭 메뉴 (위젯 테마에 맞춘 다크 팝업)
        self.menu = _PopupMenu(self.root, self.theme)
        self.menu.add("설정...", self._open_settings)
        self.menu.add("새 프로젝트 만들기...", self._new_project)
        self.menu.add("새로고침", self.refresh)
        self.menu.add("테마 전환 (다크/라이트)", self._switch_theme)
        self.menu.add_separator()
        self.menu.add("설정 파일 열기 (config.json)",
                      lambda: self._open_path(CONFIG_PATH))
        self.menu.add("대시보드 폴더 열기",
                      lambda: self._open_path(BASE_DIR))
        self.menu.add_separator()
        self.menu.add("종료", self._on_close)

    def _icon_button(self, parent: tk.Frame, char: str, command,
                     tip: str = "", hover: str | None = None) -> tk.Label:
        """제목 표시줄용 납작한 아이콘 버튼 (오른쪽부터 배치)."""
        t = self.theme
        hover_bg = hover or t["btn_hover"]
        btn = tk.Label(parent, text=char, bg=self._titlebar_bg,
                       fg=self._titlebar_fg, font=(FONT, 11), width=3,
                       cursor="hand2")
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_bg, fg="#ffffff"))
        btn.bind("<Leave>", lambda e: btn.configure(
            bg=self._titlebar_bg, fg=self._titlebar_fg))
        if tip:
            _Tooltip(btn, tip)
        self._icon_buttons.append(btn)
        return btn

    def _build_scroll_area(self) -> None:
        """내용이 길어지면 마우스 휠로 스크롤되는 영역."""
        t = self.theme
        self.canvas = tk.Canvas(self.root, bg=t["bg"], highlightthickness=0,
                                bd=0, width=self.width)
        self.canvas.pack(side="top", fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=t["bg"])
        self._body_id = self.canvas.create_window(
            (0, 0), window=self.body, anchor="nw", width=self.width)
        self.body.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

    def _build_resize_grip(self) -> None:
        """오른쪽 아래 모서리에 크기 조절 손잡이 (◢).

        overrideredirect 창이라 윈도우 기본 리사이즈 핸들이 없으므로 직접
        둠. 잡고 끌면 너비·높이 모두 바뀌고, 손을 떼면 config.json에 저장됨.
        """
        t = self.theme
        grip = tk.Label(self.root, text="◢", bg=t["bg"], fg=t["subtext"],
                        font=(FONT, 9), cursor="size_nw_se")
        grip.place(relx=1.0, rely=1.0, anchor="se", x=-1, y=-1)
        grip.lift()
        grip.bind("<Enter>", lambda e: grip.configure(fg=t["accent"]))
        grip.bind("<Leave>", lambda e: grip.configure(fg=t["subtext"]))
        grip.bind("<Button-1>", self._start_resize)
        grip.bind("<B1-Motion>", self._on_resize)
        grip.bind("<ButtonRelease-1>", self._end_resize)
        _Tooltip(grip, "끌어서 위젯 크기 조절")
        self.resize_grip = grip

    def _start_resize(self, event) -> None:
        self._resize_w0 = self.root.winfo_width()
        self._resize_h0 = self.root.winfo_height()
        self._resize_x0 = event.x_root
        self._resize_y0 = event.y_root

    def _on_resize(self, event) -> None:
        """드래그 중 실시간으로 창 크기 갱신 (저장은 손을 뗀 뒤에)."""
        new_w = max(240, self._resize_w0 + (event.x_root - self._resize_x0))
        new_h = max(TITLEBAR_H + 60,
                    self._resize_h0 + (event.y_root - self._resize_y0))
        self.root.geometry(f"{new_w}x{new_h}")
        # 자식들이 새 너비로 wrap 되도록 캔버스 안 본문 너비도 갱신
        self.width = new_w
        self.canvas.itemconfigure(self._body_id, width=new_w)

    def _end_resize(self, event) -> None:
        """리사이즈 종료 — 새 크기를 저장하고 다시 그림 (텍스트 줄바꿈 재계산)."""
        self.width = self.root.winfo_width()
        self.wcfg["width"] = self.width
        self.wcfg["height"] = self.root.winfo_height()
        self._save_config_safe()
        self.refresh()

    # ------------------------------------------------------------------
    # 내용 그리기
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """STATUS.md들을 다시 읽어 화면을 새로 그림.

        깜빡임을 줄이기 위해 '내용 지문'을 비교 — 마지막에 그린 것과
        모든 면에서 같으면 redraw를 건너뛰고 푸터 시간만 갱신함.
        대부분의 자동 새로고침은 변화가 없으므로 이 경로로 빠짐.
        """
        # 다음 자동 새로고침 예약 (이전 예약은 취소)
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        interval = int(self.cfg.get("refresh_seconds", 30)) * 1000
        self._after_id = self.root.after(interval, self.refresh)

        if self.collapsed:
            return  # 접혀 있으면 그리지 않음

        projects = scan_projects(self.cfg)

        # 빠른 경로 — 마지막으로 그린 것과 같으면 redraw 안 함 (깜빡임 없음)
        fp = self._draw_fingerprint(projects)
        if fp == self._last_draw_fp:
            self._update_footer_only()
            return
        self._last_draw_fp = fp

        # 깜빡임 방지: 새 본문을 캔버스에 보이지 않은 채로 만들어 거기에 모두 그린 뒤,
        # 캔버스의 embedded window를 한 번에 옛 본문 → 새 본문으로 교체. 옛 본문은
        # 그 뒤에 파괴 → 사용자에겐 한 번의 매끈한 전환으로 보임 (개별 destroy 없음).
        old_body = self.body
        new_body = tk.Frame(self.canvas, bg=self.theme["bg"])
        self.body = new_body
        # _draw_* 가 참조하는 캐시들도 옛 위젯을 가리키지 않게 비움
        self._card_drag = None
        self._todo_drags = []
        self._todo_canvas = None
        self._footer_label = None

        visible = [p for p in projects if not p.hidden]
        hidden = [p for p in projects if p.hidden]

        if not projects:
            self._draw_empty()
        elif not visible:
            # 프로젝트는 있지만 전부 숨겨진 경우
            self._draw_all_hidden()
        else:
            self._draw_summary(visible)
            # 카드들을 그리며 드래그 그룹에 등록 → 카드끼리 순서 변경 가능
            card_drag = _DragReorder(self.body, self.theme)
            for proj in visible:
                card, handle = self._draw_project_card(proj)
                card_drag.add_row(handle, card, proj)
            card_drag.on_reorder = self._reorder_projects
            self._card_drag = card_drag
            self._draw_todos(visible)

        self._draw_hidden_section(hidden)
        self._draw_footer()

        # 스크롤 영역 갱신용 <Configure> 도 새 본문에 다시 연결
        new_body.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))

        # 캔버스 안 embedded window를 옛 본문 → 새 본문으로 한 번에 교체
        self.canvas.itemconfigure(self._body_id, window=new_body)
        old_body.destroy()

        self._resize_to_content()

    def _draw_empty(self) -> None:
        t = self.theme
        msg = (
            "아직 표시할 프로젝트가 없음.\n\n"
            "아래 버튼으로 새 프로젝트를 만들거나,\n"
            "프로젝트 폴더에 STATUS.md 를 두면 자동으로 잡힘."
        )
        tk.Label(self.body, text=msg, bg=t["bg"], fg=t["subtext"],
                 font=(FONT, 9), justify="left").pack(padx=14, pady=(20, 10))
        btn = tk.Label(self.body, text="+ 새 프로젝트 만들기", bg=t["accent"],
                       fg="#ffffff", font=(FONT, 9, "bold"), cursor="hand2",
                       padx=10, pady=4)
        btn.pack(pady=(0, 16))
        btn.bind("<Button-1>", lambda e: self._new_project())

    def _draw_summary(self, projects: list) -> None:
        t = self.theme
        todo_count = sum(len(p.todos) for p in projects)
        row = tk.Frame(self.body, bg=t["bg"])
        row.pack(fill="x", padx=12, pady=(8, 2))
        text = f"프로젝트 {len(projects)}개 · 남은 할 일 {todo_count}개"
        tk.Label(row, text=text, bg=t["bg"], fg=t["subtext"],
                 font=(FONT, 8), anchor="w").pack(side="left")
        add = tk.Label(row, text="+ 새 프로젝트", bg=t["bg"], fg=t["accent"],
                       font=(FONT, 8, "bold"), cursor="hand2")
        add.pack(side="right")
        add.bind("<Button-1>", lambda e: self._new_project())

    def _drag_handle(self, parent: tk.Widget, bg: str) -> tk.Label:
        """드래그용 손잡이 라벨(↕). 잡고 위아래로 끌면 순서가 바뀜."""
        t = self.theme
        h = tk.Label(parent, text="↕", bg=bg, fg=t["subtext"],
                     font=(FONT, 9), cursor="fleur")
        h.bind("<Enter>", lambda e: h.configure(fg=t["accent"]))
        h.bind("<Leave>", lambda e: h.configure(fg=t["subtext"]))
        _Tooltip(h, "드래그해서 순서 바꾸기")
        return h

    def _draw_project_card(self, proj) -> tuple[tk.Frame, tk.Label]:
        """프로젝트 카드 한 개를 그림. (카드 프레임, 드래그 핸들)을 반환."""
        t = self.theme
        card = tk.Frame(self.body, bg=t["card"])
        card.pack(fill="x", padx=8, pady=4)
        inner = tk.Frame(card, bg=t["card"])
        inner.pack(fill="x", padx=10, pady=8)

        # 윗줄: [드래그 핸들] [접기 화살표] 이름(클릭 시 STATUS.md 열기) + 퍼센트
        top = tk.Frame(inner, bg=t["card"])
        top.pack(fill="x")
        handle = self._drag_handle(top, t["card"])
        handle.pack(side="left", padx=(0, 4))
        chev = tk.Label(top, text="▸" if proj.collapsed else "▾",
                        bg=t["card"], fg=t["subtext"], font=(FONT, 9),
                        cursor="hand2")
        chev.pack(side="left", padx=(0, 5))
        chev.bind("<Button-1>",
                  lambda e, p=proj: self._toggle_project_collapsed(p))
        _Tooltip(chev, "카드 접기 / 펴기")
        name = tk.Label(top, text=proj.name, bg=t["card"], fg=t["accent"],
                        font=(FONT, 10, "bold"), cursor="hand2")
        name.pack(side="left")
        name.bind("<Button-1>", lambda e, p=proj: self._open_path(p.status_path))
        tk.Label(top, text=f"{proj.percent}%", bg=t["card"], fg=t["text"],
                 font=(FONT, 10, "bold")).pack(side="right")

        # 진행바 (접혀 있어도 표시 — 진행률은 한눈에 보이게)
        self._draw_progress_bar(inner, proj.percent)

        # 접혀 있으면 세부 정보(완료 개수·메모·최근 변경)는 생략
        if not proj.collapsed:
            meta = f"완료 {proj.done} / {proj.total}"
            if proj.percent >= 100 and proj.total > 0:
                meta += "   🎉"
            tk.Label(inner, text=meta, bg=t["card"], fg=t["subtext"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))
            if proj.note:
                tk.Label(inner, text=proj.note, bg=t["card"], fg=t["subtext"],
                         font=(FONT, 8), anchor="w", justify="left",
                         wraplength=self.width - 44).pack(fill="x", pady=(2, 0))

            # 최근 변경 (update.md가 있을 때만, 클릭하면 update.md 열림)
            if proj.last_update:
                text = f"🕒 {proj.last_update}"
                if proj.last_change:
                    text += f"  ·  {proj.last_change}"
                upd = tk.Label(inner, text=text, bg=t["card"], fg=t["accent"],
                               font=(FONT, 8), anchor="w", justify="left",
                               wraplength=self.width - 44, cursor="hand2")
                upd.pack(fill="x", pady=(3, 0))
                if proj.update_path is not None:
                    upd.bind("<Button-1>",
                             lambda e, p=proj: self._open_path(p.update_path))

        # 카드 어디서든 우클릭 → 프로젝트 메뉴 (숨기기 / 파일 열기)
        self._bind_tree(card, "<Button-3>",
                        lambda e, p=proj: self._show_project_menu(e, p))
        return card, handle

    def _draw_progress_bar(self, parent: tk.Frame, percent: int) -> None:
        t = self.theme
        bar_w = self.width - 40
        height = 8
        cv = tk.Canvas(parent, width=bar_w, height=height, bg=t["card"],
                       highlightthickness=0, bd=0)
        cv.pack(anchor="w", pady=(6, 0))
        cv.create_rectangle(0, 0, bar_w, height, fill=t["bar_bg"], outline="")
        fill_w = max(0, min(bar_w, bar_w * percent / 100))
        if fill_w > 0:
            cv.create_rectangle(0, 0, fill_w, height,
                                fill=bar_color(percent), outline="")

    def _draw_todos(self, projects: list) -> None:
        t = self.theme
        # 접힌 카드의 프로젝트는 할 일 목록에서도 제외 (카드와 함께 접힘).
        # active = 펼쳐져 있고 남은 할 일이 있는 프로젝트들 (카드 순서 그대로).
        active = [p for p in projects if not p.collapsed and p.todos]
        collapsed_todos = sum(len(p.todos) for p in projects if p.collapsed)
        total = sum(len(p.todos) for p in active)

        # 구분선
        tk.Frame(self.body, bg=t["bar_bg"], height=1).pack(
            fill="x", padx=12, pady=(10, 0))

        # 헤더 (클릭하면 할 일 목록 전체 접기/펴기)
        collapsed = bool(self.wcfg.get("todos_collapsed", False))
        arrow = "▸" if collapsed else "▾"
        count = str(total)
        if collapsed_todos:
            count += f"  (접힌 카드 {collapsed_todos}개)"
        header = tk.Label(self.body, text=f"{arrow} 📋 할 일   {count}",
                          bg=t["bg"], fg=t["text"], font=(FONT, 9, "bold"),
                          anchor="w", cursor="hand2")
        header.pack(fill="x", padx=12, pady=(8, 4))
        header.bind("<Button-1>", lambda e: self._toggle_todos_collapsed())

        if collapsed:
            return  # 할 일 목록 전체가 접혀 있으면 생략

        if not active:
            if collapsed_todos:
                msg = "접힌 카드의 할 일만 있음 — 카드를 펴서 확인"
            else:
                msg = "모든 할 일 완료! 🎉"
            tk.Label(self.body, text=msg, bg=t["bg"], fg=t["subtext"],
                     font=(FONT, 9)).pack(padx=14, pady=6)
            return

        # 할 일 영역 전용 스크롤 캔버스 — 내용이 max 높이를 넘으면 여기서만 스크롤
        # (카드 영역과 분리돼 위젯 전체가 길어지지 않음).
        scroll_box = tk.Frame(self.body, bg=t["bg"])
        scroll_box.pack(fill="x", padx=0, pady=0)
        inner_canvas = tk.Canvas(scroll_box, bg=t["bg"], highlightthickness=0,
                                 bd=0)
        inner_canvas.pack(side="left", fill="x", expand=True)
        inner_frame = tk.Frame(inner_canvas, bg=t["bg"])
        win_id = inner_canvas.create_window((0, 0), window=inner_frame,
                                            anchor="nw")

        def _sync_scroll(_e=None) -> None:
            inner_canvas.configure(scrollregion=inner_canvas.bbox("all"))

        inner_frame.bind("<Configure>", _sync_scroll)
        # 캔버스 너비가 정해지면 내부 프레임을 그 너비에 맞춤 (자식 wraplength 작동)
        inner_canvas.bind(
            "<Configure>",
            lambda e: inner_canvas.itemconfigure(win_id, width=e.width))
        self._todo_canvas = inner_canvas

        # 프로젝트별로 묶어서 그림. 각 묶음은 자기만의 _DragReorder를 가져
        # 드래그 순서 변경이 같은 프로젝트 안에서만 일어남 (밖으로 못 나감).
        max_todos = int(self.wcfg.get("max_todos", 12))
        shown = 0
        for proj in active:
            if shown >= max_todos:
                break
            self._draw_todo_group_header(inner_frame, proj)
            drag = _DragReorder(inner_frame, t)
            for item in proj.todos:
                if shown >= max_todos:
                    break
                handle, row = self._draw_todo_row(inner_frame, proj, item)
                drag.add_row(handle, row, item)
                shown += 1
            drag.on_reorder = (
                lambda new_items, p=proj: self._reorder_todos(p, new_items))
            self._todo_drags.append(drag)

        # 내용 높이에 맞춰 캔버스 높이 결정 (최대 todos_max_height 까지)
        inner_frame.update_idletasks()
        max_h = int(self.wcfg.get("todos_max_height", 240))
        content_h = inner_frame.winfo_reqheight()
        inner_canvas.configure(height=min(content_h, max_h))

        # 오버플로 안내는 스크롤 영역 밖(항상 보이는 자리)에 둠
        overflow = total - shown
        if overflow > 0:
            tk.Label(self.body, text=f"…외 {overflow}개 (STATUS.md에서 확인)",
                     bg=t["bg"], fg=t["subtext"], font=(FONT, 8),
                     anchor="w").pack(fill="x", padx=14, pady=(2, 0))

    def _draw_todo_group_header(self, parent: tk.Widget, proj) -> None:
        """할 일 목록 안에서 한 프로젝트 묶음의 소제목."""
        t = self.theme
        tk.Label(parent, text=f"— {proj.name}", bg=t["bg"], fg=t["accent"],
                 font=(FONT, 8, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(6, 1))

    def _draw_todo_row(self, parent: tk.Widget, proj,
                       item) -> tuple[tk.Label, tk.Frame]:
        """할 일 한 줄을 그림. (드래그 핸들, 줄 프레임)을 반환."""
        t = self.theme
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(fill="x", padx=10, pady=1)

        handle = self._drag_handle(row, t["bg"])
        handle.pack(side="left", padx=(0, 2))
        box = tk.Label(row, text="☐", bg=t["bg"], fg=t["subtext"],
                       font=(FONT, 11), cursor="hand2")
        box.pack(side="left")
        txt = tk.Label(row, text=item.text, bg=t["bg"], fg=t["text"],
                       font=(FONT, 9), anchor="w", justify="left",
                       cursor="hand2", wraplength=self.width - 80)
        txt.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 핸들을 뺀 나머지를 누르면 완료 처리 (핸들은 드래그 전용)
        for w in (row, box, txt):
            w.bind("<Button-1>",
                   lambda e, p=proj, it=item: self._on_todo_click(p, it))
        return handle, row

    def _bind_tree(self, widget: tk.Widget, sequence: str, handler) -> None:
        """위젯과 그 안의 모든 하위 위젯에 같은 이벤트 핸들러를 연결."""
        widget.bind(sequence, handler, add="+")
        for child in widget.winfo_children():
            self._bind_tree(child, sequence, handler)

    def _draw_all_hidden(self) -> None:
        """프로젝트는 있으나 전부 숨겨졌을 때의 안내."""
        t = self.theme
        tk.Label(
            self.body,
            text="모든 프로젝트가 숨겨져 있음.\n아래 '숨김'을 펼쳐 다시 보이게 할 수 있음.",
            bg=t["bg"], fg=t["subtext"], font=(FONT, 9),
            justify="left").pack(padx=14, pady=16)

    def _draw_hidden_section(self, hidden_projects: list) -> None:
        """맨 아래 '숨김 N개' 줄. 펼치면 숨긴 프로젝트를 다시 보이게 할 수 있음."""
        if not hidden_projects:
            return
        t = self.theme
        tk.Frame(self.body, bg=t["bar_bg"], height=1).pack(
            fill="x", padx=12, pady=(10, 0))

        arrow = "▾" if self.hidden_expanded else "▸"
        header = tk.Label(
            self.body, text=f"{arrow} 숨김 {len(hidden_projects)}개",
            bg=t["bg"], fg=t["subtext"], font=(FONT, 8, "bold"),
            anchor="w", cursor="hand2")
        header.pack(fill="x", padx=12, pady=(6, 2))
        header.bind("<Button-1>", lambda e: self._toggle_hidden_expand())

        if not self.hidden_expanded:
            return
        for proj in hidden_projects:
            row = tk.Frame(self.body, bg=t["bg"], cursor="hand2")
            row.pack(fill="x", padx=16, pady=1)
            name = tk.Label(row, text=proj.name, bg=t["bg"], fg=t["subtext"],
                            font=(FONT, 8), anchor="w")
            name.pack(side="left")
            act = tk.Label(row, text="다시 보이기", bg=t["bg"], fg=t["accent"],
                           font=(FONT, 8))
            act.pack(side="right")
            for w in (row, name, act):
                w.bind("<Button-1>",
                       lambda e, p=proj: self._toggle_project_hidden(p))

    def _draw_footer(self) -> None:
        t = self.theme
        now = datetime.now().strftime("%H:%M:%S")
        self._footer_label = tk.Label(
            self.body, text=f"업데이트 {now}", bg=t["bg"],
            fg=t["subtext"], font=(FONT, 7), anchor="e")
        self._footer_label.pack(fill="x", padx=12, pady=(8, 8))

    def _update_footer_only(self) -> None:
        """변화가 없을 때 — 푸터 시간만 in-place로 갱신 (위젯 새로 안 만듦)."""
        if self._footer_label is None:
            return
        try:
            now = datetime.now().strftime("%H:%M:%S")
            self._footer_label.configure(text=f"업데이트 {now}")
        except tk.TclError:
            pass   # 라벨이 어떤 이유로 사라진 경우 조용히 무시

    def _draw_fingerprint(self, projects: list) -> tuple:
        """현재 그릴 내용의 지문 — 같으면 redraw가 필요 없음.

        화면에 보이는 모든 정보(프로젝트 데이터·관련 설정·UI 토글 상태)를
        포괄해야 함. 빠진 게 있으면 그 항목 변경 시 화면 갱신이 안 됨.
        """
        proj_part = tuple(
            (p.folder.name, p.name, p.note, p.hidden, p.collapsed,
             p.last_update, p.last_change,
             tuple((it.text, it.done) for it in p.items))
            for p in projects
        )
        cfg_part = (
            tuple(self.cfg.get("project_order", [])),
            bool(self.wcfg.get("todos_collapsed", False)),
            int(self.wcfg.get("max_todos", 12)),
            int(self.wcfg.get("todos_max_height", 240)),
            bool(self.hidden_expanded),
            int(self.width),
        )
        return (proj_part, cfg_part)

    # ------------------------------------------------------------------
    # 동작
    # ------------------------------------------------------------------
    def _on_todo_click(self, proj, item) -> None:
        """할 일 줄 클릭 → STATUS.md의 체크 상태를 토글하고 새로고침."""
        toggle_item(item, proj.status_path)
        self.refresh()

    def _show_project_menu(self, event, proj) -> None:
        """프로젝트 카드 우클릭 메뉴 — 접기 / 숨기기 / 파일 열기."""
        m = _PopupMenu(self.root, self.theme)
        m.add("편집...",
              lambda: editor.open_project_editor(
                  self.root, proj, self.theme, self.refresh))
        m.add("펴기" if proj.collapsed else "접기",
              lambda: self._toggle_project_collapsed(proj))
        m.add(f"'{proj.name}' 숨기기",
              lambda: self._toggle_project_hidden(proj))
        m.add_separator()
        m.add("STATUS.md 열기",
              lambda: self._open_path(proj.status_path))
        if proj.update_path is not None:
            m.add("update.md 열기",
                  lambda: self._open_path(proj.update_path))
        m.popup(event.x_root, event.y_root)

    def _toggle_project_hidden(self, proj) -> None:
        """프로젝트 숨김 ↔ 표시를 전환하고 새로고침."""
        toggle_hidden(self.cfg, proj.folder.name)
        self.refresh()

    def _toggle_project_collapsed(self, proj) -> None:
        """프로젝트 카드 접기 ↔ 펴기를 전환하고 새로고침."""
        toggle_collapsed(self.cfg, proj.folder.name)
        self.refresh()

    def _reorder_projects(self, new_projects: list) -> None:
        """카드를 드래그해 바뀐 프로젝트 순서를 config.json에 저장하고 새로고침."""
        set_project_order(self.cfg, [p.folder.name for p in new_projects])
        self.refresh()

    def _reorder_todos(self, proj, new_items: list) -> None:
        """한 프로젝트의 할 일을 드래그해 바뀐 순서대로 STATUS.md에 저장.

        new_items: 화면에 보이던 (미완료) 할 일들의 새 순서.
        max_todos로 잘려 화면에 없던 할 일은 원래 순서대로 뒤에 붙임.
        완료된 항목은 STATUS.md 안에서 자리를 그대로 지킴.
        """
        ordered = [it.text for it in new_items]
        shown = set(ordered)
        ordered += [it.text for it in proj.todos if it.text not in shown]
        texts = iter(ordered)
        # 완료 항목은 자기 텍스트, 미완료 항목 자리엔 새 순서를 차례로 채움
        full = [it.text if it.done else next(texts) for it in proj.items]
        reorder_items(proj.status_path, full)
        self.refresh()

    def _toggle_hidden_expand(self) -> None:
        """'숨김' 목록을 펼치거나 접음."""
        self.hidden_expanded = not self.hidden_expanded
        self.refresh()

    def _toggle_todos_collapsed(self) -> None:
        """'할 일' 목록을 접거나 폄 (상태는 config.json에 저장됨)."""
        self.wcfg["todos_collapsed"] = not bool(
            self.wcfg.get("todos_collapsed", False))
        self._save_config_safe()
        self.refresh()

    def _resize_to_content(self) -> None:
        """창 크기 결정 — 사용자가 정한 높이가 있으면 그걸 쓰고, 없으면 내용에 맞춤.

        wcfg["height"] = 0 (기본): 내용 높이에 맞춰 자동 크기 (화면 -160px 상한).
        wcfg["height"] > 0      : 사용자가 그립으로 정한 크기를 그대로 사용
                                  (내용이 더 작으면 빈 공간, 크면 본문이 스크롤).
        """
        self.body.update_idletasks()
        user_h = int(self.wcfg.get("height", 0))
        if user_h > 0:
            view_h = max(60, user_h - TITLEBAR_H)
        else:
            content_h = self.body.winfo_reqheight()
            max_h = self.root.winfo_screenheight() - 160
            view_h = max(60, min(content_h, max_h))
        self.canvas.configure(height=view_h)
        self.root.geometry(f"{self.width}x{TITLEBAR_H + view_h}")

    def _hotkey_poll(self) -> None:
        """전역 단축키·중복실행 신호를 받아 처리 (큐 → tkinter 스레드)."""
        try:
            while True:
                cmd = self._hotkey_q.get_nowait()
                if cmd == "collapse":
                    self._toggle_collapse()
                elif cmd == "hide":
                    (self.hide_action or self._toggle_window_hidden)()
        except queue.Empty:
            pass
        if self._show_q is not None:
            try:
                while True:
                    self._show_q.get_nowait()
                    self._show_self()
            except queue.Empty:
                pass
        self._hotkey_after = self.root.after(120, self._hotkey_poll)

    def _show_self(self) -> None:
        """다른 인스턴스가 '띄우기'를 요청 → 위젯을 보이게 함 (재실행 = 소환)."""
        self.root.deiconify()
        if self.collapsed:
            self._toggle_collapse()
        self.root.lift()
        self._window_hidden = False

    def _toggle_window_hidden(self) -> None:
        """닫기/열기 — 위젯 창 자체를 숨기거나 다시 보이게 함 (위젯 모드 기본)."""
        if self._window_hidden:
            self.root.deiconify()
            self.root.lift()
            self._window_hidden = False
        else:
            self._save_geometry()
            self.root.withdraw()
            self._window_hidden = True

    def _on_wheel(self, event) -> None:
        """마우스 휠 — 커서가 '할 일' 스크롤 영역 위면 그쪽을, 아니면 본문을 스크롤."""
        delta = -1 if event.delta > 0 else 1
        # 마우스 위치의 위젯에서 부모를 따라 올라가며 어느 캔버스에 속하는지 확인
        w = self.root.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is self._todo_canvas:
                self._todo_canvas.yview_scroll(delta, "units")
                return
            if w is self.canvas:
                break
            try:
                w = w.master
            except Exception:
                break
        self.canvas.yview_scroll(delta, "units")

    def _start_drag(self, event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event) -> None:
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _toggle_collapse(self) -> None:
        """제목 표시줄만 남기고 접기 / 다시 펼치기."""
        if self.collapsed:
            self.collapsed = False
            self.canvas.pack(side="top", fill="both", expand=True)
            self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-1, y=-1)
            self.resize_grip.lift()
            self._apply_titlebar_style()
            self.refresh()
        else:
            self.collapsed = True
            self.canvas.pack_forget()
            self.resize_grip.place_forget()
            self._apply_titlebar_style()
            self.root.geometry(f"{self.width}x{TITLEBAR_H}")

    def _apply_titlebar_style(self) -> None:
        """접힘 상태 + '색 강조' 설정에 따라 제목 표시줄 색을 갱신.

        접었을 때 색 강조가 켜져 있으면 막대가 눈에 띄는 색이 됨
        (다크 배경에서 접힌 위젯을 못 찾는 문제 방지).
        """
        t = self.theme
        highlight = self.collapsed and bool(
            self.wcfg.get("collapse_highlight", True))
        self._titlebar_bg = t["highlight"] if highlight else t["titlebar"]
        self._titlebar_fg = "#1e1e2e" if highlight else t["subtext"]

        self.titlebar.configure(bg=self._titlebar_bg)
        for child in self.titlebar.winfo_children():
            child.configure(bg=self._titlebar_bg)
        self.title_label.configure(fg="#1e1e2e" if highlight else t["text"])
        for btn in self._icon_buttons:
            btn.configure(fg=self._titlebar_fg)
        self._update_pin_icon()

    def _show_menu(self, event) -> None:
        self.menu.popup(event.x_root, event.y_root)

    def _new_project(self) -> None:
        """제목줄 메뉴 — 새 프로젝트 만들기 창을 엶."""
        editor.open_new_project(self.root, Path(self.cfg["root"]),
                                self.theme, self.refresh)

    def _toggle_pin(self) -> None:
        """📌 클릭 — '항상 위에 고정'을 켜고 끔."""
        new_state = not bool(self.wcfg.get("topmost", True))
        self.wcfg["topmost"] = new_state          # cfg["widget"]와 같은 객체
        self.root.attributes("-topmost", new_state)
        self._save_config_safe()
        self._update_pin_icon()

    def _update_pin_icon(self) -> None:
        """핀 상태에 따라 아이콘 색을 갱신 (켜짐=강조색, 꺼짐=흐림)."""
        on = bool(self.wcfg.get("topmost", True))
        if self.collapsed and bool(self.wcfg.get("collapse_highlight", True)):
            self.pin_btn.configure(fg="#1e1e2e")   # 강조 막대 위에서 잘 보이게
        else:
            self.pin_btn.configure(
                fg=self.theme["accent"] if on else self.theme["subtext"])

    def _switch_theme(self) -> None:
        """다크↔라이트 전환. 현재 위치를 저장하고 창을 다시 띄움."""
        new_theme = "light" if self.wcfg.get("theme") == "dark" else "dark"
        self._save_geometry()
        self.cfg["widget"]["theme"] = new_theme
        self._save_config_safe()
        self.restart = True
        self._destroy()

    def _open_settings(self) -> None:
        """헤더 ⚙ — 설정 창을 엶. 저장하면 새 설정으로 위젯을 다시 시작함."""
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        t = self.theme
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title("대시보드 설정")
        win.configure(bg=t["bg"])
        win.resizable(True, True)
        win.attributes("-topmost", True)
        win.geometry(f"+{self.root.winfo_x() + 30}+{self.root.winfo_y() + 30}")

        # 현재 설정값 (테마·체크박스는 아래에서 직접 관리)
        v_opacity = tk.IntVar(
            value=int(round(float(self.wcfg.get("opacity", 0.96)) * 100)))
        v_width = tk.IntVar(value=int(self.wcfg.get("width", 340)))
        v_maxtodos = tk.IntVar(value=int(self.wcfg.get("max_todos", 12)))
        v_todos_h = tk.IntVar(value=int(self.wcfg.get("todos_max_height", 240)))
        v_refresh = tk.IntVar(value=int(self.cfg.get("refresh_seconds", 30)))
        v_hotkey = tk.StringVar(value=self.wcfg.get("collapse_hotkey", ""))
        v_hide_hotkey = tk.StringVar(value=self.wcfg.get("hide_hotkey", ""))

        pad = tk.Frame(win, bg=t["bg"])
        pad.pack(fill="both", expand=True, padx=14, pady=12)

        def add_row(label_text: str) -> tk.Frame:
            r = tk.Frame(pad, bg=t["bg"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label_text, bg=t["bg"], fg=t["text"],
                     font=(FONT, 9), width=15, anchor="w").pack(side="left")
            return r

        # 테마 — 선택된 쪽이 또렷하게 보이도록 강조 버튼으로
        r = add_row("테마")
        theme_pick = {"value": self.wcfg.get("theme", "dark")}
        theme_btns: dict = {}

        def pick_theme(val: str) -> None:
            theme_pick["value"] = val
            for v, b in theme_btns.items():
                on = v == val
                b.configure(bg=t["accent"] if on else t["card"],
                            fg="#ffffff" if on else t["text"])

        for val, txt in (("dark", "다크"), ("light", "라이트")):
            b = tk.Label(r, text=txt, font=(FONT, 9), padx=12, pady=2,
                         cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, v=val: pick_theme(v))
            theme_btns[val] = b
        pick_theme(theme_pick["value"])

        # 항상 위 고정
        r = add_row("항상 위 고정")
        chk_topmost = editor.CheckLabel(
            r, t, checked=bool(self.wcfg.get("topmost", True)))
        chk_topmost.pack(side="left")

        # 접었을 때 색 강조
        r = add_row("접었을 때 색 강조")
        chk_highlight = editor.CheckLabel(
            r, t, checked=bool(self.wcfg.get("collapse_highlight", True)))
        chk_highlight.pack(side="left")
        tk.Label(r, text="접으면 막대가 눈에 띄는 색", bg=t["bg"],
                 fg=t["subtext"], font=(FONT, 8)).pack(side="left", padx=(4, 0))

        # 투명도
        r = add_row("투명도 (%)")
        tk.Scale(r, from_=50, to=100, orient="horizontal", variable=v_opacity,
                 bg=t["bg"], fg=t["text"], troughcolor=t["card"],
                 highlightthickness=0, length=150).pack(side="left")

        # 창 너비
        r = add_row("창 너비 (px)")
        tk.Scale(r, from_=280, to=520, orient="horizontal", variable=v_width,
                 bg=t["bg"], fg=t["text"], troughcolor=t["card"],
                 highlightthickness=0, length=150).pack(side="left")

        # 할 일 최대 개수
        r = add_row("할 일 최대 개수")
        tk.Spinbox(r, from_=3, to=200, textvariable=v_maxtodos, width=6,
                   bg=t["card"], fg=t["text"], buttonbackground=t["card"],
                   relief="flat").pack(side="left")

        # 할 일 영역 최대 높이 (이 높이를 넘으면 그 안에서 스크롤)
        r = add_row("할 일 영역 높이 (px)")
        tk.Scale(r, from_=120, to=600, orient="horizontal", variable=v_todos_h,
                 bg=t["bg"], fg=t["text"], troughcolor=t["card"],
                 highlightthickness=0, length=150, resolution=20).pack(
            side="left")

        # 새로고침 주기
        r = add_row("새로고침 (초)")
        tk.Spinbox(r, from_=5, to=600, increment=5, textvariable=v_refresh,
                   width=6, bg=t["card"], fg=t["text"],
                   buttonbackground=t["card"], relief="flat").pack(side="left")

        # 전역 단축키 — 접기/펴기와 닫기/열기를 따로 지정
        r = add_row("접기/펴기 단축키")
        tk.Entry(r, textvariable=v_hotkey, width=20, bg=t["card"],
                 fg=t["text"], insertbackground=t["text"], relief="flat",
                 font=(FONT, 9)).pack(side="left")
        r = add_row("닫기/열기 단축키")
        tk.Entry(r, textvariable=v_hide_hotkey, width=20, bg=t["card"],
                 fg=t["text"], insertbackground=t["text"], relief="flat",
                 font=(FONT, 9)).pack(side="left")
        tk.Label(pad, text="접기=내용만 접음 · 닫기=창을 숨김. 예: ctrl+alt+d · 비우면 끔",
                 bg=t["bg"], fg=t["subtext"], font=(FONT, 8)).pack(
            anchor="w", pady=(2, 0))

        tk.Label(pad, text="저장하면 위젯이 새 설정으로 다시 시작됨.",
                 bg=t["bg"], fg=t["subtext"], font=(FONT, 8)).pack(
            anchor="w", pady=(8, 0))

        def save() -> None:
            try:
                refresh = max(5, min(3600, int(v_refresh.get())))
                maxtodos = max(1, min(500, int(v_maxtodos.get())))
                todos_h = max(80, min(1200, int(v_todos_h.get())))
            except (tk.TclError, ValueError):
                return  # 숫자칸에 잘못된 값이 있으면 저장하지 않음
            disk = load_config()
            disk["refresh_seconds"] = refresh
            w = disk["widget"]
            w["x"] = self.root.winfo_x()       # 현재 창 위치 보존
            w["y"] = self.root.winfo_y()
            w["theme"] = theme_pick["value"]
            w["topmost"] = chk_topmost.checked
            w["collapse_highlight"] = chk_highlight.checked
            w["opacity"] = round(int(v_opacity.get()) / 100, 2)
            w["width"] = int(v_width.get())
            w["max_todos"] = maxtodos
            w["todos_max_height"] = todos_h
            w["collapse_hotkey"] = v_hotkey.get().strip()
            w["hide_hotkey"] = v_hide_hotkey.get().strip()
            save_config(disk)
            win.destroy()
            self.restart = True          # 새 설정으로 창을 다시 띄움
            self._destroy()

        btns = tk.Frame(pad, bg=t["bg"])
        btns.pack(fill="x", pady=(8, 0))
        tk.Button(btns, text="저장", command=save, bg=t["accent"],
                  fg="#ffffff", font=(FONT, 9, "bold"), relief="flat",
                  width=8, cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(btns, text="취소", command=win.destroy, bg=t["card"],
                  fg=t["text"], font=(FONT, 9), relief="flat",
                  width=8, cursor="hand2").pack(side="right")

        # 내용이 다 보이는 자연 크기를 최소 크기로 잡음 (그보다 크게 조절 가능)
        win.update_idletasks()
        win.minsize(win.winfo_reqwidth(), win.winfo_reqheight())

        # 내용을 다 채운 뒤 제목 표시줄을 다크로 (크기가 잡힌 후라야 함)
        editor.apply_dark_titlebar(win)

    def _open_path(self, path) -> None:
        """파일이나 폴더를 윈도우 기본 프로그램으로 엶."""
        try:
            os.startfile(str(path))
        except OSError as e:
            print(f"열기 실패: {path} ({e})")

    def _save_config_safe(self) -> None:
        """위젯이 소유한 설정(widget 블록)만 디스크 config에 반영.

        위젯이 떠 있는 동안 사용자가 config.json의 다른 항목(projects 등)을
        직접 고쳤어도 덮어쓰지 않도록, 저장 직전 디스크를 다시 읽어 병합함.
        (hidden·collapsed는 toggle 함수가 직접 디스크에 안전하게 기록함)
        """
        disk = load_config()
        disk["widget"] = self.cfg["widget"]
        save_config(disk)

    def _save_geometry(self) -> None:
        """현재 창 위치를 config.json에 기록."""
        self.cfg["widget"]["x"] = self.root.winfo_x()
        self.cfg["widget"]["y"] = self.root.winfo_y()
        self._save_config_safe()

    def _on_close(self) -> None:
        # 트레이 모드 등에서 ✕를 '숨기기'로 바꾸고 싶을 때
        if self.on_close_override is not None:
            self.on_close_override()
            return
        self._save_geometry()
        self.restart = False
        self._destroy()

    def _destroy(self) -> None:
        self._hotkey_collapse.stop()
        self._hotkey_hide.stop()
        for aid in (self._after_id, self._hotkey_after):
            if aid is not None:
                self.root.after_cancel(aid)
        self.root.destroy()


def run_widget(ipc_server=None) -> None:
    """위젯을 실행. 테마 전환 시 창을 새로 만들어 다시 띄움.

    ipc_server: 단일 실행 잠금 소켓. 다른 인스턴스가 신호하면 위젯을 띄움.
    """
    show_q: queue.Queue = queue.Queue()
    if ipc_server is not None:
        singleton.watch(ipc_server, lambda: show_q.put(1))
    while True:
        app = DashboardWidget(show_q=show_q)
        app.root.mainloop()
        if not app.restart:
            break


if __name__ == "__main__":
    run_widget()
