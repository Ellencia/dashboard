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
    save_config,
    scan_projects,
    toggle_collapsed,
    toggle_hidden,
    toggle_item,
)
from hotkey import GlobalHotkey

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


class DashboardWidget:
    """항상 위에 떠 있는 대시보드 창 한 개."""

    def __init__(self) -> None:
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
        self._settings_win: tk.Toplevel | None = None
        self._icon_buttons: list[tk.Label] = []
        # 설정 시 ✕가 종료 대신 이 콜백을 호출 (트레이 모드에서 '숨기기'로 씀)
        self.on_close_override = None
        # 전역 단축키가 눌렸을 때 실행할 동작 (None이면 보드 접기/펴기)
        self.hotkey_action = None
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

        # 마우스 휠로 스크롤
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        # Alt+F4 등으로 닫혀도 창 위치를 저장하도록
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh()

        # 전역 단축키 (보드 접기/펴기). 눌리면 큐에 신호 → poll이 처리
        self._hotkey_q: queue.Queue = queue.Queue()
        self._hotkey = GlobalHotkey(self.wcfg.get("collapse_hotkey", ""),
                                    lambda: self._hotkey_q.put(1))
        self._hotkey.start()
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

        # 우클릭 메뉴
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="설정...", command=self._open_settings)
        self.menu.add_command(label="새로고침", command=self.refresh)
        self.menu.add_command(label="테마 전환 (다크/라이트)", command=self._switch_theme)
        self.menu.add_separator()
        self.menu.add_command(label="설정 파일 열기 (config.json)",
                              command=lambda: self._open_path(CONFIG_PATH))
        self.menu.add_command(label="대시보드 폴더 열기",
                              command=lambda: self._open_path(BASE_DIR))
        self.menu.add_separator()
        self.menu.add_command(label="종료", command=self._on_close)

        # 프로젝트 카드 우클릭용 메뉴 (열 때마다 내용을 다시 채움)
        self.proj_menu = tk.Menu(self.root, tearoff=0)

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

    # ------------------------------------------------------------------
    # 내용 그리기
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """STATUS.md들을 다시 읽어 화면을 새로 그림."""
        # 다음 자동 새로고침 예약 (이전 예약은 취소)
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        interval = int(self.cfg.get("refresh_seconds", 30)) * 1000
        self._after_id = self.root.after(interval, self.refresh)

        if self.collapsed:
            return  # 접혀 있으면 그리지 않음

        # 기존 내용 제거
        for child in self.body.winfo_children():
            child.destroy()

        projects = scan_projects(self.cfg)
        visible = [p for p in projects if not p.hidden]
        hidden = [p for p in projects if p.hidden]

        if not projects:
            self._draw_empty()
        elif not visible:
            # 프로젝트는 있지만 전부 숨겨진 경우
            self._draw_all_hidden()
        else:
            self._draw_summary(visible)
            for proj in visible:
                self._draw_project_card(proj)
            self._draw_todos(visible)

        self._draw_hidden_section(hidden)
        self._draw_footer()
        self._resize_to_content()

    def _draw_empty(self) -> None:
        t = self.theme
        msg = (
            "추적할 STATUS.md 파일을 찾지 못함.\n\n"
            "각 프로젝트 폴더에 STATUS.md 를 만들고\n"
            "체크리스트를 적으면 여기에 표시됨.\n\n"
            "(STATUS_TEMPLATE.md 참고)"
        )
        tk.Label(self.body, text=msg, bg=t["bg"], fg=t["subtext"],
                 font=(FONT, 9), justify="left").pack(padx=14, pady=20)

    def _draw_summary(self, projects: list) -> None:
        t = self.theme
        todo_count = sum(len(p.todos) for p in projects)
        text = f"프로젝트 {len(projects)}개 · 남은 할 일 {todo_count}개"
        tk.Label(self.body, text=text, bg=t["bg"], fg=t["subtext"],
                 font=(FONT, 8), anchor="w").pack(fill="x", padx=12, pady=(8, 2))

    def _draw_project_card(self, proj) -> None:
        t = self.theme
        card = tk.Frame(self.body, bg=t["card"])
        card.pack(fill="x", padx=8, pady=4)
        inner = tk.Frame(card, bg=t["card"])
        inner.pack(fill="x", padx=10, pady=8)

        # 윗줄: [접기 화살표] 이름(클릭 시 STATUS.md 열기) + 퍼센트
        top = tk.Frame(inner, bg=t["card"])
        top.pack(fill="x")
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
        # 접힌 카드의 프로젝트는 할 일 목록에서도 제외 (카드와 함께 접힘)
        pairs = [(p, it) for p in projects if not p.collapsed for it in p.todos]
        collapsed_todos = sum(len(p.todos) for p in projects if p.collapsed)

        # 구분선
        tk.Frame(self.body, bg=t["bar_bg"], height=1).pack(
            fill="x", padx=12, pady=(10, 0))

        # 헤더 (클릭하면 할 일 목록 전체 접기/펴기)
        collapsed = bool(self.wcfg.get("todos_collapsed", False))
        arrow = "▸" if collapsed else "▾"
        count = str(len(pairs))
        if collapsed_todos:
            count += f"  (접힌 카드 {collapsed_todos}개)"
        header = tk.Label(self.body, text=f"{arrow} 📋 할 일   {count}",
                          bg=t["bg"], fg=t["text"], font=(FONT, 9, "bold"),
                          anchor="w", cursor="hand2")
        header.pack(fill="x", padx=12, pady=(8, 4))
        header.bind("<Button-1>", lambda e: self._toggle_todos_collapsed())

        if collapsed:
            return  # 할 일 목록 전체가 접혀 있으면 생략

        if not pairs:
            if collapsed_todos:
                msg = "접힌 카드의 할 일만 있음 — 카드를 펴서 확인"
            else:
                msg = "모든 할 일 완료! 🎉"
            tk.Label(self.body, text=msg, bg=t["bg"], fg=t["subtext"],
                     font=(FONT, 9)).pack(padx=14, pady=6)
            return

        max_todos = int(self.wcfg.get("max_todos", 12))
        for proj, item in pairs[:max_todos]:
            self._draw_todo_row(proj, item)

        overflow = len(pairs) - max_todos
        if overflow > 0:
            tk.Label(self.body, text=f"…외 {overflow}개 (STATUS.md에서 확인)",
                     bg=t["bg"], fg=t["subtext"], font=(FONT, 8),
                     anchor="w").pack(fill="x", padx=14, pady=(2, 0))

    def _draw_todo_row(self, proj, item) -> None:
        t = self.theme
        row = tk.Frame(self.body, bg=t["bg"], cursor="hand2")
        row.pack(fill="x", padx=10, pady=1)

        box = tk.Label(row, text="☐", bg=t["bg"], fg=t["subtext"],
                       font=(FONT, 11))
        box.pack(side="left")
        tag = tk.Label(row, text=proj.folder.name, bg=t["bg"], fg=t["accent"],
                       font=(FONT, 7))
        tag.pack(side="right", padx=(4, 0))
        txt = tk.Label(row, text=item.text, bg=t["bg"], fg=t["text"],
                       font=(FONT, 9), anchor="w", justify="left",
                       wraplength=self.width - 100)
        txt.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 줄 어디를 눌러도 완료 처리되도록 모든 자식에 같은 핸들러 연결
        for w in (row, box, txt, tag):
            w.bind("<Button-1>",
                   lambda e, p=proj, it=item: self._on_todo_click(p, it))

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
        tk.Label(self.body, text=f"업데이트 {now}", bg=t["bg"],
                 fg=t["subtext"], font=(FONT, 7), anchor="e").pack(
            fill="x", padx=12, pady=(8, 8))

    # ------------------------------------------------------------------
    # 동작
    # ------------------------------------------------------------------
    def _on_todo_click(self, proj, item) -> None:
        """할 일 줄 클릭 → STATUS.md의 체크 상태를 토글하고 새로고침."""
        toggle_item(item, proj.status_path)
        self.refresh()

    def _show_project_menu(self, event, proj) -> None:
        """프로젝트 카드 우클릭 메뉴 — 접기 / 숨기기 / 파일 열기."""
        m = self.proj_menu
        m.delete(0, "end")
        m.add_command(label="펴기" if proj.collapsed else "접기",
                      command=lambda: self._toggle_project_collapsed(proj))
        m.add_command(label=f"'{proj.name}' 숨기기",
                      command=lambda: self._toggle_project_hidden(proj))
        m.add_separator()
        m.add_command(label="STATUS.md 열기",
                      command=lambda: self._open_path(proj.status_path))
        if proj.update_path is not None:
            m.add_command(label="update.md 열기",
                          command=lambda: self._open_path(proj.update_path))
        m.tk_popup(event.x_root, event.y_root)

    def _toggle_project_hidden(self, proj) -> None:
        """프로젝트 숨김 ↔ 표시를 전환하고 새로고침."""
        toggle_hidden(self.cfg, proj.folder.name)
        self.refresh()

    def _toggle_project_collapsed(self, proj) -> None:
        """프로젝트 카드 접기 ↔ 펴기를 전환하고 새로고침."""
        toggle_collapsed(self.cfg, proj.folder.name)
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
        """내용 높이에 맞춰 창 크기를 조절 (화면 높이를 넘으면 스크롤)."""
        self.body.update_idletasks()
        content_h = self.body.winfo_reqheight()
        max_h = self.root.winfo_screenheight() - 160
        view_h = max(60, min(content_h, max_h))
        self.canvas.configure(height=view_h)
        self.root.geometry(f"{self.width}x{TITLEBAR_H + view_h}")

    def _hotkey_poll(self) -> None:
        """전역 단축키가 눌렸으면(큐에 신호) 보드 접기/펴기를 실행."""
        try:
            while True:
                self._hotkey_q.get_nowait()
                (self.hotkey_action or self._toggle_collapse)()
        except queue.Empty:
            pass
        self._hotkey_after = self.root.after(120, self._hotkey_poll)

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

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
            self._apply_titlebar_style()
            self.refresh()
        else:
            self.collapsed = True
            self.canvas.pack_forget()
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
        self.menu.tk_popup(event.x_root, event.y_root)

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
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.geometry(f"+{self.root.winfo_x() + 30}+{self.root.winfo_y() + 30}")

        # 현재 설정값을 담는 변수들
        v_theme = tk.StringVar(value=self.wcfg.get("theme", "dark"))
        v_topmost = tk.BooleanVar(value=bool(self.wcfg.get("topmost", True)))
        v_highlight = tk.BooleanVar(
            value=bool(self.wcfg.get("collapse_highlight", True)))
        v_opacity = tk.IntVar(
            value=int(round(float(self.wcfg.get("opacity", 0.96)) * 100)))
        v_width = tk.IntVar(value=int(self.wcfg.get("width", 340)))
        v_maxtodos = tk.IntVar(value=int(self.wcfg.get("max_todos", 12)))
        v_refresh = tk.IntVar(value=int(self.cfg.get("refresh_seconds", 30)))
        v_hotkey = tk.StringVar(value=self.wcfg.get("collapse_hotkey", ""))

        pad = tk.Frame(win, bg=t["bg"])
        pad.pack(padx=14, pady=12)

        def add_row(label_text: str) -> tk.Frame:
            r = tk.Frame(pad, bg=t["bg"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label_text, bg=t["bg"], fg=t["text"],
                     font=(FONT, 9), width=15, anchor="w").pack(side="left")
            return r

        # 테마
        r = add_row("테마")
        for val, txt in (("dark", "다크"), ("light", "라이트")):
            tk.Radiobutton(r, text=txt, value=val, variable=v_theme,
                           bg=t["bg"], fg=t["text"], selectcolor=t["card"],
                           activebackground=t["bg"], activeforeground=t["text"],
                           font=(FONT, 9)).pack(side="left")

        # 항상 위 고정
        r = add_row("항상 위 고정")
        tk.Checkbutton(r, variable=v_topmost, bg=t["bg"],
                       activebackground=t["bg"], selectcolor=t["card"]).pack(side="left")

        # 접었을 때 색 강조
        r = add_row("접었을 때 색 강조")
        tk.Checkbutton(r, variable=v_highlight, bg=t["bg"],
                       activebackground=t["bg"], selectcolor=t["card"]).pack(side="left")
        tk.Label(r, text="접으면 막대가 눈에 띄는 색", bg=t["bg"],
                 fg=t["subtext"], font=(FONT, 8)).pack(side="left")

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
        tk.Spinbox(r, from_=3, to=40, textvariable=v_maxtodos, width=6,
                   bg=t["card"], fg=t["text"], buttonbackground=t["card"],
                   relief="flat").pack(side="left")

        # 새로고침 주기
        r = add_row("새로고침 (초)")
        tk.Spinbox(r, from_=5, to=600, increment=5, textvariable=v_refresh,
                   width=6, bg=t["card"], fg=t["text"],
                   buttonbackground=t["card"], relief="flat").pack(side="left")

        # 보드 접기 단축키 (전역)
        r = add_row("보드 접기 단축키")
        tk.Entry(r, textvariable=v_hotkey, width=20, bg=t["card"],
                 fg=t["text"], insertbackground=t["text"], relief="flat",
                 font=(FONT, 9)).pack(side="left")
        tk.Label(pad, text="예: ctrl+alt+d  ·  ctrl+shift+f9  ·  비우면 단축키 끔",
                 bg=t["bg"], fg=t["subtext"], font=(FONT, 8)).pack(
            anchor="w", pady=(2, 0))

        tk.Label(pad, text="저장하면 위젯이 새 설정으로 다시 시작됨.",
                 bg=t["bg"], fg=t["subtext"], font=(FONT, 8)).pack(
            anchor="w", pady=(8, 0))

        def save() -> None:
            try:
                refresh = max(5, min(3600, int(v_refresh.get())))
                maxtodos = max(1, min(60, int(v_maxtodos.get())))
            except (tk.TclError, ValueError):
                return  # 숫자칸에 잘못된 값이 있으면 저장하지 않음
            disk = load_config()
            disk["refresh_seconds"] = refresh
            w = disk["widget"]
            w["x"] = self.root.winfo_x()       # 현재 창 위치 보존
            w["y"] = self.root.winfo_y()
            w["theme"] = v_theme.get()
            w["topmost"] = bool(v_topmost.get())
            w["collapse_highlight"] = bool(v_highlight.get())
            w["opacity"] = round(int(v_opacity.get()) / 100, 2)
            w["width"] = int(v_width.get())
            w["max_todos"] = maxtodos
            w["collapse_hotkey"] = v_hotkey.get().strip()
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
        self._hotkey.stop()
        for aid in (self._after_id, self._hotkey_after):
            if aid is not None:
                self.root.after_cancel(aid)
        self.root.destroy()


def run_widget() -> None:
    """위젯을 실행. 테마 전환 시 창을 새로 만들어 다시 띄움."""
    while True:
        app = DashboardWidget()
        app.root.mainloop()
        if not app.restart:
            break


if __name__ == "__main__":
    run_widget()
