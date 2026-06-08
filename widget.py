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
import re
import queue
import tkinter as tk
from datetime import datetime
from pathlib import Path

from core import (
    BASE_DIR,
    CONFIG_PATH,
    add_quick_todo,
    load_config,
    log_completion,
    process_drop_folder,
    reorder_items,
    save_config,
    scan_projects,
    set_project_order,
    toggle_collapsed,
    toggle_hidden,
    toggle_item,
    weekly_completion_stats,
)
from hotkey import GlobalHotkey
import editor
import singleton

FONT = "Malgun Gothic"   # 윈도우 기본 한글 폰트
TITLEBAR_H = 34          # 제목 표시줄 높이(px)

# 할 일 텍스트에서 #태그 부분(앞 공백 포함)을 떼어 표시용 글자만 남기는 정규식
_TAG_STRIP_RE = re.compile(r"\s*#\w+")
# 마감일 (!YYYY-MM-DD)도 표시용 글자에서 제거
_DUE_STRIP_RE = re.compile(r"\s*!\d{4}-\d{1,2}-\d{1,2}")

# 같은 태그는 항상 같은 색이 되도록 결정적으로 매핑하는 작은 팔레트
_TAG_PALETTE = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e",
                "#bb9af7", "#7dcfff", "#ff9e64", "#73daca"]


def _tag_color_default(tag: str) -> str:
    """태그 문자열의 해시값으로 팔레트의 한 색을 골라줌 (같은 태그=같은 색)."""
    return _TAG_PALETTE[hash(tag) % len(_TAG_PALETTE)]


def _due_badge(due: str) -> tuple[str, str] | None:
    """마감일 문자열 → (배지 라벨, 배경색). 잘못된 형식이면 None.

    당일/지남 = 빨강, D-3 이내 = 주황, D-7 이내 = 노랑, 그 외 = 회청색.
    """
    if not due:
        return None
    try:
        from datetime import date
        y, m, d = (int(x) for x in due.split("-"))
        target = date(y, m, d)
    except (ValueError, TypeError):
        return None
    days = (target - date.today()).days
    if days < 0:
        return (f"D+{-days}", "#f7768e")   # 지난 마감 — 빨강
    if days == 0:
        return ("오늘", "#ff9e64")          # 당일 — 주황
    if days <= 3:
        return (f"D-{days}", "#e0af68")    # 임박 — 노랑
    if days <= 7:
        return (f"D-{days}", "#9ece6a")    # 일주일 이내 — 초록
    return (f"D-{days}", "#7aa2f7")        # 여유 있음 — 파랑

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
        self._snap_indicator: tk.Frame | None = None   # 리사이즈 시 snap 가이드선
        # 방금 추가된 할 일 — refresh 직후 그 행에 펄스 + 자동 스크롤
        # (folder_name, normalized_text) tuple, 한 번 소비되면 None
        self._just_added: tuple[str, str] | None = None
        # 깜빡임 방지: 마지막으로 그린 내용의 지문 — 같으면 redraw 건너뜀
        self._last_draw_fp = None
        self._footer_label: tk.Label | None = None
        # Retained-mode: 토글 같은 빈번한 동작을 in-place로 처리하기 위한 ref 캐시
        self._card_refs: dict = {}        # folder.name → {percent, bar, meta}
        self._todo_row_refs: dict = {}    # (folder.name, item.text) → row Frame
        self._todo_group_refs: dict = {}  # folder.name → {header, drag}
        self._summary_count: tk.Label | None = None
        self._todo_header_label: tk.Label | None = None
        # 활성 태그 필터 — 칩 클릭 시 그 태그의 할 일만 표시
        self._tag_filter: str | None = None
        # 검색 상태 — 🔍 토글로 검색 바 표시, 비어 있으면 필터링 X
        self._search_active = False
        self._search_var: tk.StringVar | None = None    # __init__ root 만든 뒤 초기화
        self._search_after_id: str | None = None        # 디바운스 타이머
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

        # 검색 StringVar — root가 생긴 뒤에야 만들 수 있음
        self._search_var = tk.StringVar()
        # 빠른 입력 StringVar
        self._quick_var = tk.StringVar()
        # _drop/*.json 검사 타이머
        self._drop_after_id: str | None = self.root.after(
            3000, self._check_drop_folder)

        # 마우스 휠로 스크롤
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        # 키보드 단축키 — Ctrl+F=검색 토글, Ctrl+N=빠른입력 포커스, Esc=모든 필터 해제
        self.root.bind_all("<Control-f>", lambda e: self._toggle_search())
        self.root.bind_all("<Control-n>", lambda e: self._focus_quick_input())
        self.root.bind_all("<Escape>", lambda e: self._clear_all_filters())
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
        self._icon_button(bar, "?", self._show_shortcuts_popup,
                          tip="단축키·입력 형식 안내")
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
        # snap 안내선용 — 자연 크기를 한 번만 계산 (드래그 중엔 컨텐츠가
        # 안 바뀌므로 stale해도 무관)
        self.body.update_idletasks()
        self._resize_natural_h = (self.body.winfo_reqheight() + TITLEBAR_H)

    def _on_resize(self, event) -> None:
        """드래그 중에는 창 크기(root.geometry)만 갱신 — 매끄럽게.

        본문 너비, 할 일 영역 fit 등의 무거운 레이아웃 캐스케이드는 release
        시점에만 한 번. 안 그러면 매 모션마다 body.winfo_reqheight + 자식
        layout 재계산이 30~60Hz로 발생해 저프레임처럼 느껴짐.

        자연 크기보다 더 끌면 그 지점에 강조색 가이드선 → "여기서 자동 줄어듦" 안내.
        """
        new_w = max(240, self._resize_w0 + (event.x_root - self._resize_x0))
        new_h = max(TITLEBAR_H + 60,
                    self._resize_h0 + (event.y_root - self._resize_y0))
        self.root.geometry(f"{new_w}x{new_h}")
        # 자연 크기 넘기면 snap 위치에 가이드선 표시
        if new_h > self._resize_natural_h + 4:
            self._show_snap_indicator(self._resize_natural_h, new_w)
        else:
            self._hide_snap_indicator()

    def _show_snap_indicator(self, snap_y: int, width: int) -> None:
        """자연 크기 위치에 강조색 가로선 + 작은 라벨 — 거기까지 줄어든다는 표시."""
        t = self.theme
        if self._snap_indicator is None:
            wrap = tk.Frame(self.root, bg=self.root.cget("bg"))
            line = tk.Frame(wrap, bg=t["accent"], height=2)
            line.pack(fill="x")
            tag = tk.Label(wrap, text="↕ 여기까지 자동 조절",
                           bg=t["accent"], fg="#1e1e2e",
                           font=(FONT, 7, "bold"), padx=4)
            tag.pack(anchor="e")
            self._snap_indicator = wrap
        self._snap_indicator.place(x=0, y=snap_y - 1, width=width)
        self._snap_indicator.lift()

    def _hide_snap_indicator(self) -> None:
        if self._snap_indicator is not None:
            try:
                self._snap_indicator.place_forget()
            except tk.TclError:
                pass

    def _end_resize(self, event) -> None:
        """리사이즈 종료 — 본문 너비·내부 캔버스·텍스트 줄바꿈을 한 번에 갱신."""
        # snap 가이드선 정리
        if self._snap_indicator is not None:
            try:
                self._snap_indicator.destroy()
            except tk.TclError:
                pass
            self._snap_indicator = None
        self.width = self.root.winfo_width()
        self.canvas.itemconfigure(self._body_id, width=self.width)
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
        self._quick_entry = None
        self._card_refs = {}
        self._todo_row_refs = {}
        self._todo_group_refs = {}
        self._summary_count = None
        self._todo_header_label = None

        visible = [p for p in projects if not p.hidden]
        hidden = [p for p in projects if p.hidden]

        if not projects:
            self._draw_empty()
            self._draw_quick_input()   # 빈 상태에서도 빠른 입력으로 추가 가능
        elif not visible:
            # 프로젝트는 있지만 전부 숨겨진 경우
            self._draw_all_hidden()
            self._draw_quick_input()
        else:
            self._draw_quick_input()
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

    def _draw_quick_input(self) -> None:
        """빠른 입력 한 줄 + 포커스 시 형식 hint.

        형식: `[프로젝트] 텍스트 #태그 !날짜` (Enter 또는 + 클릭)
        프로젝트 안 적으면 Inbox(받은 편지함)로. 빈 줄은 무시. Ctrl+N으로 포커스.
        """
        t = self.theme
        wrap = tk.Frame(self.body, bg=t["bg"])
        wrap.pack(fill="x", padx=12, pady=(6, 0))
        row = tk.Frame(wrap, bg=t["bg"])
        row.pack(fill="x")
        plus = tk.Label(row, text="+", bg=t["bg"], fg=t["accent"],
                        font=(FONT, 12, "bold"), cursor="hand2", padx=2)
        plus.pack(side="left")
        _Tooltip(plus, "할 일 추가 (Enter). 형식: [프로젝트] 내용 #태그 !날짜")
        entry = tk.Entry(row, textvariable=self._quick_var, bg=t["card"],
                         fg=t["text"], insertbackground=t["text"],
                         relief="flat", font=(FONT, 9))
        entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._quick_entry = entry
        # 포커스 받으면 형식 hint 표시, 잃으면 숨김
        hint = tk.Label(
            wrap,
            text="[프로젝트] 내용 #태그 !날짜  ·  자연어: !오늘 !내일 !금 !+3 !+1w",
            bg=t["bg"], fg=t["subtext"], font=(FONT, 7), anchor="w")

        def show_hint(_e=None):
            hint.pack(fill="x", padx=(22, 0), pady=(1, 0))

        def hide_hint(_e=None):
            hint.pack_forget()

        entry.bind("<FocusIn>", show_hint, add="+")
        entry.bind("<FocusOut>", hide_hint, add="+")

        def submit(_e=None) -> str | None:
            line = self._quick_var.get().strip()
            if not line:
                return None
            result = add_quick_todo(self.cfg, line)
            if result is not None:
                from core import normalize_due_in_text
                folder, content = result
                self._just_added = (folder.name, normalize_due_in_text(content))
                self._quick_var.set("")
                self._last_draw_fp = None
                self.refresh()
            return "break"

        entry.bind("<Return>", submit)
        plus.bind("<Button-1>", submit)
        self._attach_tag_completer(entry)

    def _draw_summary(self, projects: list) -> None:
        t = self.theme
        todo_count = sum(len(p.todos) for p in projects)
        row = tk.Frame(self.body, bg=t["bg"])
        row.pack(fill="x", padx=12, pady=(8, 2))
        text = f"프로젝트 {len(projects)}개 · 남은 할 일 {todo_count}개"
        # in-place 업데이트용 ref 저장
        self._summary_count = tk.Label(row, text=text, bg=t["bg"],
                                       fg=t["subtext"], font=(FONT, 8),
                                       anchor="w")
        self._summary_count.pack(side="left")
        add = tk.Label(row, text="+ 새 프로젝트", bg=t["bg"], fg=t["accent"],
                       font=(FONT, 8, "bold"), cursor="hand2")
        add.pack(side="right")
        add.bind("<Button-1>", lambda e: self._new_project())

        # 주간 완료 통계 배지 (이력이 있을 때만)
        this_w, last_w = weekly_completion_stats(self.cfg)
        if this_w or last_w:
            diff = this_w - last_w
            if diff > 0:
                tail = f" (↑{diff})"
            elif diff < 0:
                tail = f" (↓{-diff})"
            else:
                tail = " (=)"
            stats = tk.Label(row, text=f"📈 이번주 {this_w}{tail}",
                             bg=t["bg"], fg=t["text"],
                             font=(FONT, 8, "bold"))
            stats.pack(side="right", padx=(0, 10))
            _Tooltip(stats, f"이번 주 완료 {this_w}개 · 저번 주 {last_w}개")

    def _tag_color(self, tag: str) -> str:
        """태그 색 — 사용자 설정이 있으면 그걸, 없으면 해시 팔레트."""
        custom = self.wcfg.get("tag_colors") or {}
        return custom.get(tag) or _tag_color_default(tag)

    def _toggle_tag_filter(self, tag: str) -> None:
        """태그 칩 클릭 — 같은 태그면 필터 해제, 다른 태그면 그걸로 전환."""
        self._tag_filter = None if self._tag_filter == tag else tag
        self._last_draw_fp = None   # 필터 바뀌면 강제 redraw
        self.refresh()

    def _clear_tag_filter(self) -> None:
        """필터 배너의 ✕ — 필터 해제."""
        self._tag_filter = None
        self._last_draw_fp = None
        self.refresh()

    def _toggle_search(self) -> None:
        """🔍 클릭 또는 Ctrl+F — 검색 바 표시 토글. 닫을 땐 쿼리도 비움."""
        self._search_active = not self._search_active
        if not self._search_active and self._search_var is not None:
            self._search_var.set("")
        self._last_draw_fp = None
        self.refresh()

    def _clear_all_filters(self) -> None:
        """Esc — 태그 필터·검색을 한 번에 해제."""
        changed = False
        if self._tag_filter is not None:
            self._tag_filter = None
            changed = True
        if self._search_var is not None and self._search_var.get():
            self._search_var.set("")
            changed = True
        if self._search_active:
            self._search_active = False
            changed = True
        if changed:
            self._last_draw_fp = None
            self.refresh()

    def _search_query(self) -> str:
        """현재 검색 쿼리 (없으면 빈 문자열)."""
        if self._search_var is None:
            return ""
        return self._search_var.get().strip()

    def _on_search_key(self, event) -> None:
        """검색 입력칸 KeyRelease — 200ms 디바운스 후 refresh."""
        if event.keysym == "Escape":
            self._clear_all_filters()
            return
        if self._search_after_id is not None:
            try:
                self.root.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.root.after(
            200, self._do_search_refresh)

    def _do_search_refresh(self) -> None:
        self._search_after_id = None
        self._last_draw_fp = None
        self.refresh()

    def _toggle_sort_due(self) -> None:
        """마감일순 정렬 ON/OFF (config에 저장 + 새로고침)."""
        self.wcfg["sort_by_due"] = not bool(
            self.wcfg.get("sort_by_due", False))
        self._save_config_safe()
        self._last_draw_fp = None
        self.refresh()

    def _toggle_show_completed(self) -> None:
        """완료 보기 ON/OFF (config에 저장 + 새로고침)."""
        self.wcfg["show_completed"] = not bool(
            self.wcfg.get("show_completed", False))
        self._save_config_safe()
        self._last_draw_fp = None
        self.refresh()

    def _get_all_tags(self) -> list[str]:
        """모든 프로젝트의 unique 태그 알파벳순 목록 (자동완성 후보)."""
        tags = set()
        for p in scan_projects(self.cfg):
            for it in p.items:
                for tag in it.tags:
                    tags.add(tag)
        return sorted(tags)

    def _attach_tag_completer(self, entry: tk.Entry) -> None:
        """Entry에 #태그 자동완성 popup 부착.

        '#' 친 직후부터 다음 공백/특수문자 전까지의 부분 문자열이 'partial'.
        매칭 태그를 다크 Listbox로 entry 바로 아래에 띄움. ↑↓로 이동,
        Enter/Tab 으로 선택, Esc 닫기. 빈 entry에서 #만 쳐도 전체 태그 표시.
        """
        state: dict = {"popup": None, "listbox": None}
        t = self.theme

        def get_tag_prefix():
            text = entry.get()
            cur = entry.index(tk.INSERT)
            m = re.search(r"#([^\s#!]*)$", text[:cur])
            return (m.start(), m.group(1)) if m else None

        def close_popup():
            if state["popup"] is not None:
                try:
                    state["popup"].destroy()
                except tk.TclError:
                    pass
                state["popup"] = None
                state["listbox"] = None

        def show_popup(matches):
            if state["popup"] is None:
                popup = tk.Toplevel(entry)
                popup.overrideredirect(True)
                popup.attributes("-topmost", True)
                popup.configure(bg=t["bar_bg"])
                inner = tk.Frame(popup, bg=t["card"])
                inner.pack(padx=1, pady=1)
                lb = tk.Listbox(inner, bg=t["card"], fg=t["text"],
                                selectbackground=t["accent"],
                                selectforeground="#ffffff",
                                relief="flat", font=(FONT, 9),
                                borderwidth=0, highlightthickness=0,
                                activestyle="none")
                lb.pack(fill="both")
                state["popup"] = popup
                state["listbox"] = lb
            lb = state["listbox"]
            lb.delete(0, tk.END)
            for tag in matches:
                lb.insert(tk.END, tag)
            lb.configure(height=min(6, len(matches)))
            lb.selection_clear(0, tk.END)
            lb.selection_set(0)
            # entry 바로 아래에 위치
            state["popup"].update_idletasks()
            x = entry.winfo_rootx()
            y = entry.winfo_rooty() + entry.winfo_height()
            state["popup"].geometry(f"+{x}+{y}")

        def accept_selection():
            if state["listbox"] is None:
                return False
            sel = state["listbox"].curselection()
            if not sel:
                return False
            chosen = state["listbox"].get(sel[0])
            info = get_tag_prefix()
            if info is None:
                return False
            start, _ = info
            text = entry.get()
            cur = entry.index(tk.INSERT)
            new_text = text[:start] + f"#{chosen}" + text[cur:]
            entry.delete(0, tk.END)
            entry.insert(0, new_text)
            entry.icursor(start + len(chosen) + 1)
            close_popup()
            return True

        def on_key(e):
            # popup 활성 시 화살표/Enter/Tab/Esc 가로채기
            if state["listbox"] is not None:
                if e.keysym in ("Down", "Up"):
                    lb = state["listbox"]
                    cur = lb.curselection()
                    if cur:
                        new = cur[0] + (1 if e.keysym == "Down" else -1)
                    else:
                        new = 0
                    if 0 <= new < lb.size():
                        lb.selection_clear(0, tk.END)
                        lb.selection_set(new)
                        lb.see(new)
                    return "break"
                if e.keysym in ("Return", "Tab"):
                    if accept_selection():
                        return "break"
                if e.keysym == "Escape":
                    close_popup()
                    return "break"

            info = get_tag_prefix()
            if info is None:
                close_popup()
                return None
            _, partial = info
            all_tags = self._get_all_tags()
            if partial:
                matches = [tg for tg in all_tags if partial.lower() in tg.lower()]
            else:
                matches = all_tags
            if matches:
                show_popup(matches)
            else:
                close_popup()
            return None

        entry.bind("<KeyRelease>", on_key, add="+")
        entry.bind("<FocusOut>",
                   lambda e: entry.after(200, close_popup), add="+")

    def _show_due_picker(self, proj, item, anchor: tk.Widget) -> None:
        """할 일에 마감일을 빠르게 설정하는 다크 팝업.

        프리셋(오늘/내일/모레/금/월/+1주/+2주/+1개월) + 마감 제거.
        선택 시 `core.parse_natural_due`로 ISO 변환 → rename_item으로 텍스트 갱신.
        """
        from core import parse_natural_due
        presets = [
            ("오늘", "오늘"),
            ("내일", "내일"),
            ("모레", "모레"),
            ("이번 주 금", "금"),
            ("다음 주 월", "월"),
            ("+ 1주", "+1w"),
            ("+ 2주", "+2w"),
            ("+ 1개월", "+1m"),
        ]
        m = _PopupMenu(self.root, self.theme)
        for label, token in presets:
            iso = parse_natural_due(token)
            if iso is None:
                continue
            m.add(f"{label}    {iso}",
                  lambda iso_=iso: self._set_item_due(proj, item, iso_))
        if item.due:
            m.add_separator()
            m.add(f"마감 제거  ({item.due})",
                  lambda: self._set_item_due(proj, item, ""))
        # anchor 위젯 바로 아래에 띄움
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        m.popup(x, y)

    def _set_item_due(self, proj, item, iso_date: str) -> None:
        """item의 마감일을 iso_date로 설정 (빈 문자열이면 마감 제거).

        text에서 기존 `!YYYY-MM-DD` 토큰을 떼고, iso_date가 있으면 끝에 추가.
        rename_item으로 STATUS.md 갱신 + pulse 피드백.
        """
        from core import rename_item
        stripped = _DUE_STRIP_RE.sub("", item.text)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        new_text = f"{stripped} !{iso_date}".strip() if iso_date else stripped
        if not new_text or new_text == item.text:
            return
        try:
            rename_item(proj.status_path, item.text, new_text)
        except OSError:
            return
        self._just_added = (proj.folder.name, new_text)
        self._last_draw_fp = None
        self.refresh()

    def _show_project_due_picker(self, proj, anchor: tk.Widget) -> None:
        """프로젝트 자체 마감을 빠르게 설정하는 다크 팝업.

        todo 마감 picker와 같은 패턴 — 다만 프리셋이 더 멀리 잡힘
        (프로젝트 마감은 보통 며칠~수개월 단위라 +1주 / +1개월 / +3개월).
        """
        from core import parse_natural_due
        presets = [
            ("오늘", "오늘"),
            ("내일", "내일"),
            ("이번 주 금", "금"),
            ("다음 주 월", "월"),
            ("+ 1주", "+1w"),
            ("+ 2주", "+2w"),
            ("+ 1개월", "+1m"),
            ("+ 3개월", "+3m"),
        ]
        m = _PopupMenu(self.root, self.theme)
        for label, token in presets:
            iso = parse_natural_due(token)
            if iso is None:
                continue
            m.add(f"{label}    {iso}",
                  lambda iso_=iso: self._set_project_due(proj, iso_))
        if proj.due:
            m.add_separator()
            m.add(f"마감 제거  ({proj.due})",
                  lambda: self._set_project_due(proj, ""))
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        m.popup(x, y)

    def _set_project_due(self, proj, iso_date: str) -> None:
        """프로젝트 STATUS.md '# 제목' 줄의 마감을 갈아끼움 + refresh."""
        from core import set_project_due
        try:
            set_project_due(proj.status_path, iso_date)
        except OSError:
            return
        self._last_draw_fp = None
        self.refresh()

    def _show_shortcuts_popup(self) -> None:
        """? 버튼 — 단축키·입력 형식을 다크 팝업으로 안내. 각 항목은 정보용(no-op)."""
        m = _PopupMenu(self.root, self.theme)
        m.add("Ctrl + F     검색 토글", lambda: None)
        m.add("Ctrl + N     빠른 입력에 포커스", lambda: None)
        m.add("Esc          검색·필터 해제", lambda: None)
        m.add_separator()
        m.add("↕ 핸들 드래그   할 일·카드 순서 바꾸기", lambda: None)
        m.add("카드 우클릭    편집·접기·숨기기", lambda: None)
        m.add("◢ 그립 드래그   위젯 크기 조절", lambda: None)
        m.add_separator()
        m.add("입력 형식    [프로젝트] 텍스트 #태그 !날짜", lambda: None)
        m.add("자연어 마감   !오늘 !내일 !금 !+3 !+1w", lambda: None)
        # 제목 표시줄 가운데 즈음
        x = self.root.winfo_rootx() + max(40, self.width // 2 - 130)
        y = self.root.winfo_rooty() + TITLEBAR_H
        m.popup(x, y)

    def _focus_quick_input(self) -> None:
        """Ctrl+N — 빠른 입력 칸에 포커스."""
        if getattr(self, "_quick_entry", None) is not None:
            try:
                self._quick_entry.focus_set()
            except tk.TclError:
                pass

    def _check_drop_folder(self) -> None:
        """주기적으로 root/_drop/*.json 검사 → 발견 시 처리·새로고침."""
        try:
            added = process_drop_folder(self.cfg)
            if added:
                self._last_draw_fp = None
                self.refresh()
        except Exception:
            pass
        # 다음 검사 예약 (5초 간격)
        self._drop_after_id = self.root.after(5000, self._check_drop_folder)

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
        percent_lbl = tk.Label(top, text=f"{proj.percent}%", bg=t["card"],
                               fg=t["text"], font=(FONT, 10, "bold"))
        percent_lbl.pack(side="right")
        # 이 프로젝트의 가장 임박한 마감 todo를 작은 배지로 (% 왼쪽)
        nearest_due = ""
        for it in proj.todos:
            if it.due and (not nearest_due or it.due < nearest_due):
                nearest_due = it.due
        if nearest_due:
            info = _due_badge(nearest_due)
            if info is not None:
                near_text, near_color = info
                tk.Label(top, text=near_text, bg=near_color, fg="#1e1e2e",
                         font=(FONT, 7, "bold"), padx=4).pack(
                    side="right", padx=(0, 6))
        # 프로젝트 자체 마감 — 🏁 접두로 todo 배지와 시각 구분, 클릭 시 picker
        proj_due_info = _due_badge(proj.due) if proj.due else None
        if proj_due_info is not None:
            pd_text, pd_color = proj_due_info
            proj_due_widget = tk.Label(
                top, text=f"🏁 {pd_text}", bg=pd_color, fg="#1e1e2e",
                font=(FONT, 7, "bold"), padx=4, cursor="hand2")
        else:
            # 마감 없을 땐 무딘 🏁 — 클릭으로 설정
            proj_due_widget = tk.Label(
                top, text="🏁", bg=t["card"], fg=t["subtext"],
                font=(FONT, 9), cursor="hand2")
        proj_due_widget.pack(side="right", padx=(0, 6))
        proj_due_widget.bind(
            "<Button-1>",
            lambda e, p=proj, w=proj_due_widget:
            self._show_project_due_picker(p, w))
        _Tooltip(proj_due_widget,
                 "프로젝트 마감 설정" if not proj.due
                 else "프로젝트 마감 변경 / 제거")

        # 진행바 (접혀 있어도 표시 — 진행률은 한눈에 보이게)
        bar_canvas = self._draw_progress_bar(inner, proj.percent)

        # 접혀 있으면 세부 정보(완료 개수·메모·최근 변경)는 생략
        meta_lbl: tk.Label | None = None
        if not proj.collapsed:
            meta = f"완료 {proj.done} / {proj.total}"
            if proj.percent >= 100 and proj.total > 0:
                meta += "   🎉"
            meta_lbl = tk.Label(inner, text=meta, bg=t["card"],
                                fg=t["subtext"], font=(FONT, 8), anchor="w")
            meta_lbl.pack(fill="x", pady=(3, 0))
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
        # in-place 갱신용 ref 저장 (% / 진행바 / 메타)
        self._card_refs[proj.folder.name] = {
            "percent": percent_lbl,
            "bar": bar_canvas,
            "meta": meta_lbl,
        }
        return card, handle

    def _draw_progress_bar(self, parent: tk.Frame, percent: int) -> tk.Canvas:
        t = self.theme
        bar_w = self.width - 40
        height = 8
        cv = tk.Canvas(parent, width=bar_w, height=height, bg=t["card"],
                       highlightthickness=0, bd=0)
        cv.pack(anchor="w", pady=(6, 0))
        self._fill_progress_bar(cv, percent)
        return cv

    def _fill_progress_bar(self, cv: tk.Canvas, percent: int) -> None:
        """진행바 캔버스의 내용물만 다시 그림 (in-place 갱신용)."""
        t = self.theme
        cv.delete("all")
        bar_w = int(cv["width"])
        height = int(cv["height"])
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
        flt = self._tag_filter
        query = self._search_query().lower()
        sort_by_due = bool(self.wcfg.get("sort_by_due", False))
        show_done = bool(self.wcfg.get("show_completed", False))
        # show_done이면 완료 항목도 포함하므로 active 기준을 items로 다시 잡음
        if show_done:
            active = [p for p in projects if not p.collapsed and p.items]
        # 필터·검색·정렬·완료보기 활성 시 각 프로젝트 todos를 추림
        def todos_for(p):
            src = p.items if show_done else p.todos
            out = []
            for it in src:
                if flt is not None and flt not in it.tags:
                    continue
                if query and query not in it.text.lower():
                    continue
                out.append(it)
            if sort_by_due:
                out.sort(key=lambda it: it.due or "9999-99-99")
            return out
        active_filtered = [(p, todos_for(p)) for p in active]
        active_filtered = [(p, ts) for p, ts in active_filtered if ts]
        total = sum(len(ts) for _, ts in active_filtered)

        # 구분선
        tk.Frame(self.body, bg=t["bar_bg"], height=1).pack(
            fill="x", padx=12, pady=(10, 0))

        # 헤더 (클릭하면 할 일 목록 전체 접기/펴기) + 🔍 검색 토글
        collapsed = bool(self.wcfg.get("todos_collapsed", False))
        arrow = "▸" if collapsed else "▾"
        count = str(total)
        if flt:
            count += f"  (#{flt} 필터)"
        if query:
            count += f"  (\"{query}\" 검색)"
        if collapsed_todos:
            count += f"  (접힌 카드 {collapsed_todos}개)"
        header_row = tk.Frame(self.body, bg=t["bg"])
        header_row.pack(fill="x", padx=12, pady=(8, 4))
        header = tk.Label(header_row, text=f"{arrow} 📋 할 일   {count}",
                          bg=t["bg"], fg=t["text"], font=(FONT, 9, "bold"),
                          anchor="w", cursor="hand2")
        header.pack(side="left", fill="x", expand=True)
        header.bind("<Button-1>", lambda e: self._toggle_todos_collapsed())
        self._todo_header_label = header   # in-place 갱신용
        # 🔍 검색 토글 (Ctrl+F 도 같은 동작)
        search_btn = tk.Label(
            header_row, text="🔍",
            bg=t["accent"] if self._search_active else t["bg"],
            fg="#1e1e2e" if self._search_active else t["subtext"],
            font=(FONT, 9), cursor="hand2", padx=3)
        search_btn.pack(side="right")
        search_btn.bind("<Button-1>", lambda e: self._toggle_search())
        _Tooltip(search_btn, "검색 (Ctrl+F · Esc로 해제)")
        # 마감일순 정렬 토글
        sort_btn = tk.Label(
            header_row, text="📅",
            bg=t["accent"] if sort_by_due else t["bg"],
            fg="#1e1e2e" if sort_by_due else t["subtext"],
            font=(FONT, 9), cursor="hand2", padx=3)
        sort_btn.pack(side="right", padx=(0, 2))
        sort_btn.bind("<Button-1>", lambda e: self._toggle_sort_due())
        _Tooltip(sort_btn,
                 "마감일순 정렬 (켜면 드래그 순서 변경 비활성)")
        # 완료 보기 토글
        done_btn = tk.Label(
            header_row, text="✓",
            bg=t["accent"] if show_done else t["bg"],
            fg="#1e1e2e" if show_done else t["subtext"],
            font=(FONT, 9, "bold"), cursor="hand2", padx=3)
        done_btn.pack(side="right", padx=(0, 2))
        done_btn.bind("<Button-1>", lambda e: self._toggle_show_completed())
        _Tooltip(done_btn, "완료된 할 일 같이 보기 (☑ + 취소선)")

        # 검색 바 (활성 시) — 필터 배너보다 위에 둠
        if self._search_active and not collapsed:
            sbar = tk.Frame(self.body, bg=t["bg"])
            sbar.pack(fill="x", padx=14, pady=(0, 4))
            tk.Label(sbar, text="검색:", bg=t["bg"], fg=t["subtext"],
                     font=(FONT, 8)).pack(side="left")
            entry = tk.Entry(sbar, textvariable=self._search_var,
                             bg=t["card"], fg=t["text"],
                             insertbackground=t["text"], relief="flat",
                             font=(FONT, 9))
            entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
            entry.bind("<KeyRelease>", self._on_search_key)
            # 새로 그려질 때마다 포커스 복원 (입력 끊김 방지)
            entry.focus_set()
            entry.icursor(tk.END)

        # 필터 배너 — 활성 시 헤더 아래에 표시 (✕로 해제)
        if flt:
            banner = tk.Frame(self.body, bg=t["bg"])
            banner.pack(fill="x", padx=14, pady=(0, 4))
            tk.Label(banner, text="필터:", bg=t["bg"], fg=t["subtext"],
                     font=(FONT, 8)).pack(side="left")
            chip = tk.Label(banner, text=f"#{flt}", bg=self._tag_color(flt),
                            fg="#1e1e2e", font=(FONT, 8, "bold"), padx=5,
                            cursor="hand2")
            chip.pack(side="left", padx=(4, 4))
            chip.bind("<Button-1>", lambda e: self._clear_tag_filter())
            x = tk.Label(banner, text="✕ 해제", bg=t["bg"], fg=t["accent"],
                         font=(FONT, 8, "bold"), cursor="hand2")
            x.pack(side="left")
            x.bind("<Button-1>", lambda e: self._clear_tag_filter())

        if collapsed:
            return  # 할 일 목록 전체가 접혀 있으면 생략

        if not active_filtered:
            if flt:
                msg = f"'#{flt}' 태그를 가진 할 일이 없음"
            elif collapsed_todos:
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
        # max_todos = 0 (또는 음수) → 무제한 (스크롤 영역에서 다 보여 줌).
        max_todos = int(self.wcfg.get("max_todos", 0))
        unlimited = max_todos <= 0
        shown = 0
        for proj, todos_in_proj in active_filtered:
            if not unlimited and shown >= max_todos:
                break
            group_header = self._draw_todo_group_header(inner_frame, proj)
            # 마감일순 정렬 중에는 드래그가 의미 없어 등록 안 함
            drag = _DragReorder(inner_frame, t) if not sort_by_due else None
            for item in todos_in_proj:
                if not unlimited and shown >= max_todos:
                    break
                handle, row = self._draw_todo_row(inner_frame, proj, item)
                if drag is not None:
                    drag.add_row(handle, row, item)
                # in-place 갱신용 — (folder, text)로 행 위젯 캐시
                self._todo_row_refs[(proj.folder.name, item.text)] = row
                shown += 1
            if drag is not None:
                drag.on_reorder = (
                    lambda new_items, p=proj: self._reorder_todos(p, new_items))
                self._todo_drags.append(drag)
            # 그룹 끝에 그 프로젝트 전용 빠른 추가 입력칸
            self._draw_group_quick_add(inner_frame, proj)
            self._todo_group_refs[proj.folder.name] = {
                "header": group_header, "drag": drag,
            }

        # 내용 높이에 맞춰 캔버스 높이 결정.
        # 자동 크기 모드(height=0)에선 todos_max_height로 캡 — 위젯 무한 성장 방지.
        # 사용자 지정 크기 모드(height>0)에선 cap 무시 — 내용 전체를 보여 inner
        # 스크롤 자체를 없앰 (자연 snap 시 deezel inner-scroll 잔여물 없게).
        inner_frame.update_idletasks()
        max_h = int(self.wcfg.get("todos_max_height", 240))
        content_h = inner_frame.winfo_reqheight()
        if int(self.wcfg.get("height", 0)) > 0:
            inner_canvas.configure(height=content_h)
        else:
            inner_canvas.configure(height=min(content_h, max_h))

        # 오버플로 안내는 스크롤 영역 밖(항상 보이는 자리)에 둠 (cap 켰을 때만)
        overflow = total - shown
        if not unlimited and overflow > 0:
            tk.Label(self.body, text=f"…외 {overflow}개 (STATUS.md에서 확인)",
                     bg=t["bg"], fg=t["subtext"], font=(FONT, 8),
                     anchor="w").pack(fill="x", padx=14, pady=(2, 0))

    def _draw_group_quick_add(self, parent: tk.Widget, proj) -> None:
        """프로젝트 묶음 끝에 그 프로젝트 전용 빠른 추가 한 줄.

        [프로젝트] 안 적어도 그 카드 STATUS.md에 바로 추가. #태그·!날짜는
        그대로 텍스트에 포함돼 저장(다음 scan에서 자연히 추출).
        """
        from core import add_item
        t = self.theme
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(fill="x", padx=10, pady=(1, 4))
        plus = tk.Label(row, text="+", bg=t["bg"], fg=t["subtext"],
                        font=(FONT, 10, "bold"), cursor="hand2", padx=4)
        plus.pack(side="left")
        var = tk.StringVar()
        ent = tk.Entry(row, textvariable=var, bg=t["card"], fg=t["text"],
                       insertbackground=t["text"], relief="flat",
                       font=(FONT, 9))
        ent.pack(side="left", fill="x", expand=True, padx=(2, 0))
        _Tooltip(plus,
                 f"'{proj.name}'에 할 일 추가 (Enter) — #태그 !날짜 가능")

        def submit(_e=None):
            text = var.get().strip()
            if not text:
                return
            from core import normalize_due_in_text
            add_item(proj.status_path, text)
            self._just_added = (proj.folder.name, normalize_due_in_text(text))
            var.set("")
            self._last_draw_fp = None
            self.refresh()

        ent.bind("<Return>", submit)
        plus.bind("<Button-1>", submit)
        self._attach_tag_completer(ent)

    def _draw_todo_group_header(self, parent: tk.Widget, proj) -> tk.Frame:
        """할 일 목록 안에서 한 프로젝트 묶음의 소제목 + 태그별 개수 칩.

        칩 클릭 시 그 태그로 필터됨 → 묶음 간 빠른 카테고리 전환.
        카운트는 필터와 무관하게 그 프로젝트 전체 미완료 기준 (다른 태그가
        어떤 게 있는지도 보여 줌). 헤더 Frame을 반환 (in-place에서 숨김 처리용).
        """
        t = self.theme
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(fill="x", padx=14, pady=(6, 1))
        tk.Label(row, text=f"— {proj.name}", bg=t["bg"], fg=t["accent"],
                 font=(FONT, 8, "bold"), anchor="w").pack(side="left")

        # 미완료 할 일들에서 태그별 개수 모음 (순서: 등장 순)
        counts: dict[str, int] = {}
        for it in proj.todos:
            for tag in it.tags:
                counts[tag] = counts.get(tag, 0) + 1
        for tag, c in counts.items():
            label = f"#{tag}·{c}"
            chip = tk.Label(row, text=label, bg=self._tag_color(tag),
                            fg="#1e1e2e", font=(FONT, 7, "bold"), padx=3,
                            cursor="hand2")
            chip.pack(side="left", padx=(3, 0))
            chip.bind("<Button-1>",
                      lambda e, tg=tag: self._toggle_tag_filter(tg))
        return row

    def _draw_todo_row(self, parent: tk.Widget, proj,
                       item) -> tuple[tk.Label, tk.Frame]:
        """할 일 한 줄을 그림. (드래그 핸들, 줄 프레임)을 반환.

        텍스트 안의 #태그 들은 떼어서 오른쪽 끝에 색 칩으로 표시.
        같은 태그는 항상 같은 색이라 한눈에 카테고리 구분이 됨.
        완료 항목(show_completed 켰을 때 보임)은 ☑ + 취소선 + 흐린 색.
        """
        t = self.theme
        sort_by_due = bool(self.wcfg.get("sort_by_due", False))
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(fill="x", padx=10, pady=1)

        # 마감일순 정렬 모드에선 드래그가 의미 없어서 핸들 자리만 비워둠
        if sort_by_due:
            handle = tk.Label(row, text=" ", bg=t["bg"], width=2)
            handle.pack(side="left", padx=(0, 2))
        else:
            handle = self._drag_handle(row, t["bg"])
            handle.pack(side="left", padx=(0, 2))
        box_text = "☑" if item.done else "☐"
        box_fg = t["accent"] if item.done else t["subtext"]
        box = tk.Label(row, text=box_text, bg=t["bg"], fg=box_fg,
                       font=(FONT, 11), cursor="hand2")
        box.pack(side="left")

        # 태그 칩을 오른쪽에 배치. side="right"은 마지막 pack이 가장 오른쪽이 되므로
        # 원문 순서를 시각적으로도 유지하려면 reversed로 거꾸로 pack.
        chips: list[tk.Label] = []
        for tag in reversed(item.tags):
            chip = tk.Label(row, text=f"#{tag}", bg=self._tag_color(tag),
                            fg="#1e1e2e", font=(FONT, 7, "bold"), padx=4,
                            cursor="hand2")
            chip.pack(side="right", padx=(3, 0))
            chips.append(chip)

        # 마감일 영역 — 있으면 색 배지, 없으면 무딘 🕒 아이콘. 둘 다 클릭 시 마감 picker
        due_extra = 0
        badge_info = _due_badge(item.due)
        if badge_info:
            badge_text, badge_color = badge_info
            due_widget: tk.Label = tk.Label(
                row, text=badge_text, bg=badge_color, fg="#1e1e2e",
                font=(FONT, 7, "bold"), padx=4, cursor="hand2")
            due_widget.pack(side="right", padx=(3, 0))
            due_extra = 40
            _Tooltip(due_widget, "마감일 변경 / 제거")
        else:
            due_widget = tk.Label(
                row, text="🕒", bg=t["bg"], fg=t["subtext"],
                font=(FONT, 8), cursor="hand2")
            due_widget.pack(side="right", padx=(3, 2))
            due_extra = 18
            _Tooltip(due_widget, "마감일 설정")
        due_widget.bind(
            "<Button-1>",
            lambda e, p=proj, it=item, b=due_widget: self._show_due_picker(p, it, b))

        # 표시용 텍스트 — #태그/마감일 부분 제거, 공백 정리. 빈 문자열이면 원본
        display = _TAG_STRIP_RE.sub("", item.text)
        display = _DUE_STRIP_RE.sub("", display)
        display = re.sub(r"\s+", " ", display).strip() or item.text
        # 칩·배지가 차지할 가로폭 (태그 1개당 ~35px, 마감 배지 ~40px)
        chip_room = 35 * len(item.tags) + due_extra
        # 완료 항목은 흐린 색 + 취소선 (tk font의 4번째 modifier)
        txt_font = (FONT, 9, "overstrike") if item.done else (FONT, 9)
        txt_fg = t["subtext"] if item.done else t["text"]
        # cursor="xterm" — 클릭하면 인라인 편집된다는 시각적 힌트
        txt = tk.Label(row, text=display, bg=t["bg"], fg=txt_fg,
                       font=txt_font, anchor="w", justify="left",
                       cursor="xterm",
                       wraplength=max(80, self.width - 80 - chip_room))
        txt.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 클릭 영역 분리:
        #   체크박스 = 완료 토글
        #   텍스트   = 인라인 편집 (Entry로 교체 → Enter/FocusOut 저장, Esc 취소)
        #   태그 칩  = 그 태그로 필터링
        box.bind("<Button-1>",
                 lambda e, p=proj, it=item: self._on_todo_click(p, it))
        txt.bind("<Button-1>",
                 lambda e, p=proj, it=item, t_lbl=txt, r=row:
                 self._start_inline_edit(p, it, t_lbl, r))
        for chip, tag in zip(chips, reversed(item.tags)):
            chip.bind("<Button-1>",
                      lambda e, tg=tag: self._toggle_tag_filter(tg))

        # 방금 추가된 할 일이면 펄스 + 스크롤 (한 번만 소비)
        if (self._just_added is not None
                and self._just_added == (proj.folder.name, item.text)):
            self._just_added = None
            original_bg = t["bg"]
            # layout이 정착한 뒤 실행 (after_idle → 첫 펄스 step)
            self.root.after(50, lambda r=row: self._scroll_to_row(r))
            self.root.after(80,
                            lambda r=row, bg=original_bg: self._pulse_row(r, bg))

        return handle, row

    def _pulse_row(self, row: tk.Frame, original_bg: str) -> None:
        """방금 추가된 할 일 행의 bg를 강조색→원래색으로 ~1.2초간 fade.

        라이트 메모리 작동 — row 와 같은 bg를 가진 자식(handle/box/txt)만
        함께 갱신. 칩·배지는 자기 색이 있으므로 건드리지 않음. row가 destroy
        됐어도(예: 새로운 refresh로) 조용히 무시.
        """
        if not row.winfo_exists():
            return
        targets: list[tk.Widget] = [row]
        for child in row.winfo_children():
            try:
                if child.cget("bg") == original_bg:
                    targets.append(child)
            except tk.TclError:
                pass

        def hex_to_rgb(h: str) -> tuple[int, int, int]:
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        accent = self.theme["accent"]
        ar, ag, ab = hex_to_rgb(accent)
        br, bg_, bb = hex_to_rgb(original_bg)
        n_steps = 10
        duration_ms = 1200

        def set_step(step: int) -> None:
            f = step / n_steps   # 0→accent, 1→original_bg
            r = int(ar * (1 - f) + br * f)
            g = int(ag * (1 - f) + bg_ * f)
            b = int(ab * (1 - f) + bb * f)
            color = f"#{r:02x}{g:02x}{b:02x}"
            for w in targets:
                try:
                    if w.winfo_exists():
                        w.configure(bg=color)
                except tk.TclError:
                    pass

        for i in range(n_steps + 1):
            delay = int(i * duration_ms / n_steps)
            self.root.after(delay, lambda s=i: set_step(s))

    def _scroll_to_row(self, row: tk.Frame) -> None:
        """방금 추가된 할 일 행이 viewport 밖이면 inner_canvas를 스크롤해 보이게."""
        if self._todo_canvas is None or not row.winfo_exists():
            return
        canvas = self._todo_canvas
        try:
            if not canvas.winfo_exists():
                return
            canvas.update_idletasks()
            row_y = row.winfo_y()
            row_h = row.winfo_height()
            sr = canvas.cget("scrollregion") or ""
            parts = sr.split()
            if len(parts) != 4:
                return
            sr_h = float(parts[3])
            if sr_h <= 0:
                return
            top_frac, bot_frac = canvas.yview()
            view_top = top_frac * sr_h
            view_bottom = bot_frac * sr_h
            # 이미 view 안이면 스크롤 안 함
            if view_top <= row_y and (row_y + row_h) <= view_bottom:
                return
            # row가 살짝 위에 보이도록 (top - 10px)
            canvas.yview_moveto(max(0.0, (row_y - 10) / sr_h))
        except tk.TclError:
            pass

    def _start_inline_edit(self, proj, item, txt_label: tk.Label,
                           row: tk.Frame) -> None:
        """할 일 텍스트 클릭 — 그 자리에 Entry로 교체해 바로 편집.

        Enter / FocusOut: rename_item으로 STATUS.md에 반영 후 refresh.
        Esc / 빈 값: 원래 라벨 복구 (수정 안 함).
        """
        from core import rename_item
        t = self.theme
        # 옛 라벨 숨김 (위젯은 살려둠 — Esc로 복구 시 다시 pack)
        txt_label.pack_forget()
        var = tk.StringVar(value=item.text)
        entry = tk.Entry(row, textvariable=var, bg=t["card"], fg=t["text"],
                         insertbackground=t["text"], relief="flat",
                         font=(FONT, 9))
        # chips는 이미 side="right"로 packed 됨 → 새 entry는 가운데 슬롯을 차지
        entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        entry.focus_set()
        entry.icursor(tk.END)
        entry.select_range(0, tk.END)

        done = {"v": False}   # 중복 commit 방지 (FocusOut와 Return가 동시에 fire)

        def restore_label():
            try:
                entry.destroy()
            except tk.TclError:
                pass
            try:
                txt_label.pack(side="left", fill="x", expand=True, padx=(4, 0))
            except tk.TclError:
                pass

        def commit(_e=None):
            if done["v"]:
                return "break"
            done["v"] = True
            new = var.get().strip()
            if not new or new == item.text:
                restore_label()
                return "break"
            try:
                rename_item(proj.status_path, item.text, new)
            except OSError:
                restore_label()
                return "break"
            self._last_draw_fp = None   # rename은 데이터 변화 → 전체 redraw
            self.refresh()
            return "break"

        def cancel(_e=None):
            if done["v"]:
                return "break"
            done["v"] = True
            restore_label()
            return "break"

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

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
             p.due, p.last_update, p.last_change,
             tuple((it.text, it.done, it.due) for it in p.items))
            for p in projects
        )
        cfg_part = (
            tuple(self.cfg.get("project_order", [])),
            bool(self.wcfg.get("todos_collapsed", False)),
            int(self.wcfg.get("max_todos", 12)),
            int(self.wcfg.get("todos_max_height", 240)),
            bool(self.hidden_expanded),
            int(self.width),
            self._tag_filter or "",
            tuple(sorted((self.wcfg.get("tag_colors") or {}).items())),
            self._search_active,
            self._search_query(),
            bool(self.wcfg.get("sort_by_due", False)),
            bool(self.wcfg.get("show_completed", False)),
        )
        return (proj_part, cfg_part)

    # ------------------------------------------------------------------
    # 동작
    # ------------------------------------------------------------------
    def _on_todo_click(self, proj, item) -> None:
        """할 일 줄 클릭 → STATUS.md의 체크 상태를 토글.

        Retained-mode: 미완료→완료 시 그 줄·카드·합계만 in-place 갱신.
        완료→미완료(완료 보기 모드에서만 가능)는 행 복귀가 복잡해 일반 refresh.
        실패하면 일반 refresh로 폴백.
        """
        was_done = item.done
        toggle_item(item, proj.status_path)
        if not was_done:
            log_completion(self.cfg, proj.folder.name, item.text)
        new_projects = scan_projects(self.cfg)
        new_proj = next((p for p in new_projects
                         if p.folder.name == proj.folder.name), None)
        if new_proj is None or was_done:
            self.refresh()
            return
        if not self._inplace_toggle_todo(proj, item, new_proj, new_projects):
            self.refresh()

    def _inplace_toggle_todo(self, proj, item, new_proj, new_projects) -> bool:
        """토글 후 줄·카드·합계 in-place 갱신. 실패면 False (호출자가 refresh)."""
        try:
            # 1. 토글된 줄을 pack_forget (위젯은 살려둠 — 다음 refresh에서 정리)
            row_key = (proj.folder.name, item.text)
            row = self._todo_row_refs.pop(row_key, None)
            if row is not None and row.winfo_exists():
                row.pack_forget()
                # DragReorder의 rows에서도 제거 → 드래그 좌표 계산 안 깨짐
                group = self._todo_group_refs.get(proj.folder.name)
                if group is not None:
                    drag = group.get("drag")
                    if drag is not None:
                        drag.rows = [(r, p) for r, p in drag.rows if r is not row]

            # 2. 카드의 % / 진행바 / 메타 갱신
            card_ref = self._card_refs.get(proj.folder.name)
            if card_ref is not None:
                pct = card_ref.get("percent")
                if pct is not None and pct.winfo_exists():
                    pct.configure(text=f"{new_proj.percent}%")
                bar = card_ref.get("bar")
                if bar is not None and bar.winfo_exists():
                    self._fill_progress_bar(bar, new_proj.percent)
                meta = card_ref.get("meta")
                if meta is not None and meta.winfo_exists():
                    meta_text = f"완료 {new_proj.done} / {new_proj.total}"
                    if new_proj.percent >= 100 and new_proj.total > 0:
                        meta_text += "   🎉"
                    meta.configure(text=meta_text)

            # 3. 미완료가 0이 된 프로젝트는 묶음 헤더도 숨김
            if not new_proj.todos:
                group = self._todo_group_refs.get(proj.folder.name)
                if group is not None:
                    h = group.get("header")
                    if h is not None and h.winfo_exists():
                        h.pack_forget()

            # 4. 상단 요약 count
            visible = [p for p in new_projects if not p.hidden]
            if (self._summary_count is not None
                    and self._summary_count.winfo_exists()):
                total_todo = sum(len(p.todos) for p in visible)
                self._summary_count.configure(
                    text=f"프로젝트 {len(visible)}개 · 남은 할 일 {total_todo}개")

            # 5. 할 일 헤더 카운트 (필터·검색 상태 반영해 _draw_todos와 동일하게)
            if (self._todo_header_label is not None
                    and self._todo_header_label.winfo_exists()):
                flt = self._tag_filter
                query = self._search_query().lower()
                active = [p for p in visible if not p.collapsed and p.todos]
                collapsed_todos = sum(len(p.todos) for p in visible if p.collapsed)
                def passes_count(p_):
                    n = 0
                    for it in p_.todos:
                        if flt is not None and flt not in it.tags:
                            continue
                        if query and query not in it.text.lower():
                            continue
                        n += 1
                    return n
                total = sum(passes_count(p) for p in active)
                collapsed_ui = bool(self.wcfg.get("todos_collapsed", False))
                arrow = "▸" if collapsed_ui else "▾"
                count = str(total)
                if flt:
                    count += f"  (#{flt} 필터)"
                if query:
                    count += f"  (\"{query}\" 검색)"
                if collapsed_todos:
                    count += f"  (접힌 카드 {collapsed_todos}개)"
                self._todo_header_label.configure(
                    text=f"{arrow} 📋 할 일   {count}")

            # 6. 다음 auto-tick에서 skip되도록 지문 캐시 갱신
            self._last_draw_fp = self._draw_fingerprint(new_projects)
            return True
        except (tk.TclError, AttributeError, KeyError):
            return False

    def _fresh_proj(self, folder_name: str):
        """folder.name으로 최신 Project 객체를 다시 읽어 반환 (없으면 None).

        Retained-mode 토글 이후엔 closure에 잡힌 옛 proj.items가 stale해서
        편집창 등이 옛 상태를 보임. 이 헬퍼로 액션 시점에 최신화.
        """
        for p in scan_projects(self.cfg):
            if p.folder.name == folder_name:
                return p
        return None

    def _show_project_menu(self, event, proj) -> None:
        """프로젝트 카드 우클릭 메뉴 — 접기 / 숨기기 / 파일 열기."""
        m = _PopupMenu(self.root, self.theme)
        # 편집창은 액션 시점에 최신 proj로 + cfg를 함께 넘겨 포커스 받을 때마다
        # 파일과 자동 동기화 (위젯에서 토글한 변경이 즉시 반영되도록)
        m.add("편집...",
              lambda: editor.open_project_editor(
                  self.root,
                  self._fresh_proj(proj.folder.name) or proj,
                  self.theme, self.refresh, self.cfg))
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
        """창 크기 결정 — 사용자 지정 크기와 자연 크기 중 작은 쪽 사용.

        - wcfg["height"] = 0: 자연 크기 (내용 + 화면 -160px 상한).
        - wcfg["height"] > 0:
            user가 자연 크기보다 큼 → 자연 크기로 snap (빈 공간 방지)
            user가 자연 크기보다 작음 → user 크기 사용, 할 일 영역에 가용 공간을 줘 그 안에서 스크롤
        이렇게 하면 어디에도 의미없는 빈 공간이 안 남음.
        """
        self.body.update_idletasks()
        content_h = self.body.winfo_reqheight()
        max_h = self.root.winfo_screenheight() - 160
        natural_view_h = max(60, min(content_h, max_h))
        user_h = int(self.wcfg.get("height", 0))
        if user_h > 0:
            user_view_h = max(60, user_h - TITLEBAR_H)
            # 사용자가 자연 크기보다 크게 잡았으면 자연 크기로 snap (빈 BG 안 만듦)
            view_h = min(user_view_h, natural_view_h)
        else:
            view_h = natural_view_h
        self.canvas.configure(height=view_h)
        self.root.geometry(f"{self.width}x{TITLEBAR_H + view_h}")
        # 사용자가 작게 잡아 내용이 안 들어갈 때만 할 일 영역 축소(외부 스크롤 대신 내부 스크롤로)
        if user_h > 0 and view_h < natural_view_h:
            self._fit_todo_canvas_to_available(view_h)

    def _fit_todo_canvas_to_available(self, view_h: int) -> None:
        """할 일 스크롤 영역을 본문 가용 공간 전체로 확장 (사용자 지정 크기일 때).

        chrome_h = 본문 reqheight - 현재 할 일 캔버스 높이 (다른 모든 요소).
        available = view_h - chrome_h = 할 일 영역이 차지할 수 있는 높이.

        할 일 영역을 항상 available 만큼 키움 — 내용이 작으면 그 안에 빈
        BG(자연스러움), 크면 그 안에서 스크롤. 이렇게 안 하면 외부 canvas
        아래에 빈 BG가 떠 사용자가 "상단 여백" 으로 인식함.

        주의: update_idletasks()는 호출하지 않음 — 드래그 중 모션마다 호출
        하면 동기 재페인트로 깜빡임 발생.
        """
        if self._todo_canvas is None or not self._todo_canvas.winfo_exists():
            return
        inner_h_now = self._todo_canvas.winfo_height()
        chrome_h = self.body.winfo_reqheight() - inner_h_now
        available = max(60, view_h - chrome_h)
        # 작은 변화는 무시 — 모션 이벤트마다 configure 호출 안 함
        if abs(available - inner_h_now) > 4:
            self._todo_canvas.configure(height=available)

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
            # 펴기 시점에 데이터가 안 바뀌었으면 refresh가 skip 경로로 빠져
            # _resize_to_content가 호출되지 않아 창이 짜부라진 채로 남음.
            # 명시적으로 크기를 복원한 뒤 refresh를 부름.
            self._resize_to_content()
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

        # 할 일 최대 개수 — 0이면 무제한 (스크롤 영역에서 다 보임)
        r = add_row("할 일 표시 상한")
        tk.Spinbox(r, from_=0, to=500, textvariable=v_maxtodos, width=6,
                   bg=t["card"], fg=t["text"], buttonbackground=t["card"],
                   relief="flat").pack(side="left")
        tk.Label(r, text="  (0 = 무제한)", bg=t["bg"], fg=t["subtext"],
                 font=(FONT, 8)).pack(side="left")

        # 할 일 영역 최대 높이 (이 높이를 넘으면 그 안에서 스크롤)
        r = add_row("할 일 영역 높이 (px)")
        tk.Scale(r, from_=120, to=600, orient="horizontal", variable=v_todos_h,
                 bg=t["bg"], fg=t["text"], troughcolor=t["card"],
                 highlightthickness=0, length=150, resolution=20).pack(
            side="left")

        # 태그별 색 지정 — 빈 매핑이면 해시 팔레트로 자동 할당, 지정한 태그만 고정
        tag_color_state: dict = dict(self.wcfg.get("tag_colors") or {})
        tag_rows_holder: list[tuple[tk.StringVar, tk.StringVar]] = []
        tag_section = tk.Frame(pad, bg=t["bg"])
        tag_section.pack(fill="x", pady=(6, 0))
        tk.Label(tag_section, text="태그 색 (지정 안 한 태그는 자동 색)",
                 bg=t["bg"], fg=t["text"], font=(FONT, 9, "bold"),
                 anchor="w").pack(fill="x")
        tag_list_frame = tk.Frame(tag_section, bg=t["bg"])
        tag_list_frame.pack(fill="x", pady=(2, 0))

        def render_tag_rows() -> None:
            for child in tag_list_frame.winfo_children():
                child.destroy()
            tag_rows_holder.clear()
            for tag_name, color in tag_color_state.items():
                row = tk.Frame(tag_list_frame, bg=t["bg"])
                row.pack(fill="x", pady=1)
                v_tag = tk.StringVar(value=tag_name)
                v_color = tk.StringVar(value=color)
                tag_rows_holder.append((v_tag, v_color))
                tk.Label(row, text="#", bg=t["bg"], fg=t["subtext"],
                         font=(FONT, 9)).pack(side="left")
                tk.Entry(row, textvariable=v_tag, width=10, bg=t["card"],
                         fg=t["text"], insertbackground=t["text"],
                         relief="flat", font=(FONT, 9)).pack(side="left")
                swatch = tk.Label(row, text="    ", bg=color, cursor="hand2")
                swatch.pack(side="left", padx=(6, 0))

                def pick(_e=None, s=swatch, v=v_color):
                    from tkinter import colorchooser
                    chosen = colorchooser.askcolor(
                        initialcolor=v.get(), parent=win)
                    if chosen and chosen[1]:
                        v.set(chosen[1])
                        s.configure(bg=chosen[1])

                swatch.bind("<Button-1>", pick)

                def remove(_e=None, name=tag_name):
                    tag_color_state.pop(name, None)
                    # 현재 입력값을 임시 보존 (사용자가 막 바꾼 게 있으면)
                    fresh = {v_t.get().strip().lstrip("#"): v_c.get()
                             for v_t, v_c in tag_rows_holder
                             if v_t.get().strip().lstrip("#") != name
                             and v_t.get().strip().lstrip("#")}
                    tag_color_state.clear()
                    tag_color_state.update(fresh)
                    render_tag_rows()

                tk.Label(row, text="✕", bg=t["bg"], fg=t["subtext"],
                         font=(FONT, 9), cursor="hand2").pack(
                    side="left", padx=(6, 0))
                row.winfo_children()[-1].bind("<Button-1>", remove)

        def add_tag_color() -> None:
            # 현재 입력값 보존 + 새 항목 추가
            fresh = {v_t.get().strip().lstrip("#"): v_c.get()
                     for v_t, v_c in tag_rows_holder
                     if v_t.get().strip().lstrip("#")}
            i = 1
            while f"태그{i}" in fresh:
                i += 1
            fresh[f"태그{i}"] = _tag_color_default(f"태그{i}")
            tag_color_state.clear()
            tag_color_state.update(fresh)
            render_tag_rows()

        render_tag_rows()
        add_btn = tk.Label(tag_section, text="+ 태그 색 추가", bg=t["bg"],
                           fg=t["accent"], font=(FONT, 8, "bold"),
                           cursor="hand2")
        add_btn.pack(anchor="w", pady=(3, 0))
        add_btn.bind("<Button-1>", lambda e: add_tag_color())

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
                maxtodos = max(0, min(500, int(v_maxtodos.get())))
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
            # 태그 색 매핑 — 입력칸의 현재 값들로 다시 모음 (빈 태그·빈 색 제외)
            tag_colors_final = {}
            for v_t, v_c in tag_rows_holder:
                tag = v_t.get().strip().lstrip("#")
                color = v_c.get().strip()
                if tag and color:
                    tag_colors_final[tag] = color
            w["tag_colors"] = tag_colors_final
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
