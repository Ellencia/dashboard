"""프로젝트 대시보드 - 편집 창.

STATUS.md / update.md 를 텍스트로 직접 안 고치고 GUI로 다루기 위한 창.
  - 프로젝트 편집 창: 이름·메모·할 일 수정, update.md에 변경 기록 추가
  - 새 프로젝트 창: 폴더 + STATUS.md / update.md 생성

파일은 core.py의 편집 함수로 '해당 줄만' 고쳐 씀 (다른 내용 보존).
각 동작은 즉시 파일에 반영되고 on_change() 콜백으로 위젯을 새로고침함.
"""
from __future__ import annotations

import ctypes
import tkinter as tk

import core

FONT = "Malgun Gothic"


def apply_dark_titlebar(window: tk.Toplevel | tk.Tk) -> None:
    """창의 네이티브 제목 표시줄(헤더)을 다크색으로 칠함 (Windows 10/11).

    tk.Toplevel은 운영체제가 그리는 흰 제목 표시줄을 갖는데, 위젯 다크
    테마와 안 어울림. Windows의 DWM에 'immersive dark mode' 속성을 켜서
    제목 표시줄을 검게 만듦. 구버전 윈도우 등에서 실패하면 조용히 넘어감.

    update()로 창이 실제로 만들어진 뒤 속성을 켜고, 이미 흰색으로
    그려진 제목 표시줄은 잠깐 숨겼다 다시 띄워 다크로 다시 그리게 함.
    숨겼다 띄우면 위치가 좌상단으로 튀므로 원래 위치를 기억했다 복원함.
    구버전 윈도우 등에서 실패하면 조용히 넘어감.
    """
    try:
        window.update()   # 창과 제목 표시줄(HWND)이 완전히 만들어지도록
        # tk의 winfo_id는 내부 창 → 제목 표시줄을 가진 건 그 부모 창
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 2004+ / 11)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int))
        # 이미 흰색으로 그려진 제목 표시줄을 다크로 다시 그리게 강제.
        # 숨김→표시 과정에서 위치가 흐트러지므로 기억한 위치로 되돌림.
        geo = window.geometry()           # "WxH+X+Y"
        window.withdraw()
        window.geometry(geo)              # 숨긴 채 원래 위치 지정
        window.deiconify()                # 그 위치에 다크로 나타남
    except Exception:
        pass


def _bind_wheel(widget: tk.Widget, canvas: tk.Canvas) -> None:
    """위젯과 그 하위 위젯에 마우스 휠 → 캔버스 스크롤을 연결."""
    widget.bind(
        "<MouseWheel>",
        lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"),
        add="+")
    for child in widget.winfo_children():
        _bind_wheel(child, canvas)


def _entry(parent, theme, textvar, width=20):
    return tk.Entry(parent, textvariable=textvar, width=width,
                    bg=theme["card"], fg=theme["text"],
                    insertbackground=theme["text"], relief="flat",
                    font=(FONT, 9))


def _button(parent, theme, text, cmd, accent=False):
    return tk.Button(parent, text=text, command=cmd, relief="flat",
                     cursor="hand2", padx=9,
                     bg=theme["accent"] if accent else theme["card"],
                     fg="#ffffff" if accent else theme["text"],
                     font=(FONT, 9, "bold") if accent else (FONT, 9))


class CheckLabel:
    """다크 테마에서도 잘 보이는 ☐/☑ 체크박스 (tk.Checkbutton 대체).

    tk.Checkbutton은 체크 표시가 배경과 색이 비슷해 잘 안 보여서,
    라벨에 ☐/☑ 문자를 직접 그리고 색을 또렷하게 줌.
    """

    def __init__(self, parent, theme, checked=False, command=None) -> None:
        self.theme = theme
        self.checked = checked
        self.command = command
        self.label = tk.Label(parent, bg=theme["bg"], font=(FONT, 11),
                              cursor="hand2", width=2)
        self._refresh()
        self.label.bind("<Button-1>", lambda e: self.toggle())

    def _refresh(self) -> None:
        self.label.configure(
            text="☑" if self.checked else "☐",
            fg=self.theme["accent"] if self.checked else self.theme["subtext"])

    def toggle(self) -> None:
        self.checked = not self.checked
        self._refresh()
        if self.command is not None:
            self.command(self.checked)

    def set(self, checked: bool) -> None:
        self.checked = checked
        self._refresh()

    def pack(self, **kw):
        self.label.pack(**kw)
        return self


class _ProjectEditor:
    """프로젝트 한 개의 STATUS.md / update.md 를 편집하는 창."""

    def __init__(self, parent_root, project, theme, on_change) -> None:
        self.theme = theme
        self.on_change = on_change
        self.status_path = project.status_path
        self.update_path = project.folder / core.UPDATE_FILENAME
        self.name = project.name
        self.note = project.note
        t = theme

        self.win = tk.Toplevel(parent_root)
        self.win.title(f"편집 — {project.name}")
        self.win.configure(bg=t["bg"])
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.geometry(
            f"+{parent_root.winfo_x() + 40}+{parent_root.winfo_y() + 30}")
        apply_dark_titlebar(self.win)   # 제목 표시줄을 다크로

        pad = tk.Frame(self.win, bg=t["bg"])
        pad.pack(padx=14, pady=12)

        # 이름 / 메모
        self.v_name = tk.StringVar(value=project.name)
        self._field_row(pad, "이름", self.v_name, self._save_name)
        self.v_note = tk.StringVar(value=project.note)
        self._field_row(pad, "메모", self.v_note, self._save_note)

        # 할 일 목록 (스크롤 영역)
        tk.Label(pad, text="할 일", bg=t["bg"], fg=t["text"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x",
                                                          pady=(10, 2))
        self.canvas = tk.Canvas(pad, bg=t["bg"], highlightthickness=0,
                                width=400, height=240)
        self.canvas.pack()
        self.task_frame = tk.Frame(self.canvas, bg=t["bg"])
        self.canvas.create_window((0, 0), window=self.task_frame,
                                  anchor="nw", width=400)
        self.task_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
        _bind_wheel(self.canvas, self.canvas)

        for item in project.items:
            self._add_task_row(item.text, item.done)

        # 새 할 일 추가
        addrow = tk.Frame(pad, bg=t["bg"])
        addrow.pack(fill="x", pady=(6, 0))
        self.v_newtask = tk.StringVar()
        ent = _entry(addrow, t, self.v_newtask)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self._add_task())
        _button(addrow, t, "+ 추가", self._add_task).pack(side="left",
                                                         padx=(4, 0))

        # update.md 변경 기록
        tk.Frame(pad, bg=t["card"], height=1).pack(fill="x", pady=(12, 6))
        tk.Label(pad, text="변경 기록 (update.md)", bg=t["bg"], fg=t["text"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        uprow = tk.Frame(pad, bg=t["bg"])
        uprow.pack(fill="x", pady=(2, 0))
        self.v_update = tk.StringVar()
        uent = _entry(uprow, t, self.v_update)
        uent.pack(side="left", fill="x", expand=True)
        uent.bind("<Return>", lambda e: self._add_update())
        _button(uprow, t, "기록", self._add_update).pack(side="left",
                                                        padx=(4, 0))
        self.up_msg = tk.Label(pad, text="오늘 한 일을 한 줄로 적으면 날짜별로 쌓임.",
                               bg=t["bg"], fg=t["subtext"], font=(FONT, 8),
                               anchor="w")
        self.up_msg.pack(fill="x", pady=(2, 0))

        _button(pad, t, "닫기", self.win.destroy).pack(anchor="e",
                                                      pady=(12, 0))

    # ------------------------------------------------------------------
    def _field_row(self, parent, label, var, save_fn) -> None:
        """라벨 + 입력칸 한 줄. 입력칸은 Enter/포커스 이동 시 저장."""
        t = self.theme
        r = tk.Frame(parent, bg=t["bg"])
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label, bg=t["bg"], fg=t["subtext"], font=(FONT, 9),
                 width=5, anchor="w").pack(side="left")
        ent = _entry(r, t, var, 34)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: save_fn())
        ent.bind("<FocusOut>", lambda e: save_fn())

    def _add_task_row(self, text: str, done: bool) -> None:
        """할 일 한 줄 (체크 / 텍스트 수정 / 삭제)."""
        t = self.theme
        state = {"text": text}        # 파일에서 줄을 찾을 때 쓰는 현재 텍스트
        row = tk.Frame(self.task_frame, bg=t["bg"])
        row.pack(fill="x", pady=1)

        def on_check(checked):
            core.set_item_done(self.status_path, state["text"], checked)
            self.on_change()

        CheckLabel(row, t, checked=done, command=on_check).pack(side="left")

        text_var = tk.StringVar(value=text)
        ent = _entry(row, t, text_var)
        ent.pack(side="left", fill="x", expand=True, padx=(2, 2))

        def commit_rename(_e=None):
            new = text_var.get().strip()
            if not new:
                text_var.set(state["text"])      # 빈 값이면 되돌림
                return
            if new != state["text"]:
                core.rename_item(self.status_path, state["text"], new)
                state["text"] = new
                self.on_change()

        ent.bind("<Return>", commit_rename)
        ent.bind("<FocusOut>", commit_rename)

        def on_delete():
            core.delete_item(self.status_path, state["text"])
            row.destroy()
            self.on_change()

        delbtn = tk.Label(row, text="✕", bg=t["bg"], fg=t["subtext"],
                          font=(FONT, 9), cursor="hand2", width=2)
        delbtn.pack(side="right")
        delbtn.bind("<Button-1>", lambda e: on_delete())

        _bind_wheel(row, self.canvas)

    # ------------------------------------------------------------------
    def _save_name(self) -> None:
        name = self.v_name.get().strip()
        if name and name != self.name:
            core.set_project_name(self.status_path, name)
            self.name = name
            self.win.title(f"편집 — {name}")
            self.on_change()

    def _save_note(self) -> None:
        note = self.v_note.get().strip()
        if note != self.note:
            core.set_project_note(self.status_path, note)
            self.note = note
            self.on_change()

    def _add_task(self) -> None:
        text = self.v_newtask.get().strip()
        if not text:
            return
        core.add_item(self.status_path, text)
        self._add_task_row(text, False)
        self.v_newtask.set("")
        self.on_change()

    def _add_update(self) -> None:
        text = self.v_update.get().strip()
        if not text:
            return
        core.add_update_entry(self.update_path, text)
        self.v_update.set("")
        self.up_msg.configure(text="기록됨 ✓", fg=self.theme["accent"])
        self.on_change()


def open_project_editor(parent_root, project, theme, on_change) -> None:
    """프로젝트 편집 창을 엶."""
    _ProjectEditor(parent_root, project, theme, on_change)


def open_new_project(parent_root, root_dir, theme, on_change) -> None:
    """새 프로젝트 창 — 이름만 입력하면 폴더·STATUS.md·update.md를 자동 생성."""
    t = theme
    win = tk.Toplevel(parent_root)
    win.title("새 프로젝트")
    win.configure(bg=t["bg"])
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.geometry(f"+{parent_root.winfo_x() + 50}+{parent_root.winfo_y() + 50}")
    apply_dark_titlebar(win)   # 제목 표시줄을 다크로

    pad = tk.Frame(win, bg=t["bg"])
    pad.pack(padx=16, pady=14)

    tk.Label(pad, text="새 프로젝트 이름", bg=t["bg"], fg=t["text"],
             font=(FONT, 10, "bold"), anchor="w").pack(fill="x")
    v_name = tk.StringVar()
    ent = _entry(pad, t, v_name, 24)
    ent.pack(fill="x", pady=(6, 3))
    ent.focus_set()
    tk.Label(pad, text="이름만 적으면 폴더와 STATUS.md·update.md를 자동으로 만듭니다.",
             bg=t["bg"], fg=t["subtext"], font=(FONT, 8),
             anchor="w").pack(fill="x")

    msg = tk.Label(pad, text="", bg=t["bg"], fg="#f7768e", font=(FONT, 8),
                   anchor="w")
    msg.pack(fill="x", pady=(4, 0))

    def create(_e=None) -> None:
        name = v_name.get().strip()
        if not name:
            msg.configure(text="프로젝트 이름을 입력하세요")
            return
        folder = core.safe_folder_name(name)
        if not folder:
            msg.configure(text="이름에 쓸 수 있는 글자가 없습니다")
            return
        if (root_dir / folder).exists():
            msg.configure(text="같은 이름의 프로젝트가 이미 있습니다")
            return
        try:
            core.create_project(root_dir, folder, name)
        except OSError as e:
            msg.configure(text=f"생성 실패: {e}")
            return
        on_change()
        win.destroy()

    ent.bind("<Return>", create)

    btns = tk.Frame(pad, bg=t["bg"])
    btns.pack(fill="x", pady=(12, 0))
    _button(btns, t, "만들기", create, accent=True).pack(side="right",
                                                       padx=(6, 0))
    _button(btns, t, "취소", win.destroy).pack(side="right")
