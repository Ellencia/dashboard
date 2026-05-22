"""프로젝트 대시보드 - 트레이 아이콘 모드.

작업표시줄 트레이에 아이콘을 띄움. 아이콘을 클릭하면 위젯 팝업이 뜨고,
✕로 닫으면 다시 트레이로 들어감 (바탕화면을 차지하지 않음).

필요 패키지: pystray, pillow   →   pip install pystray pillow

구조 메모:
  - tkinter는 메인 스레드에서 mainloop를 돌려야 함.
  - pystray 아이콘은 별도 스레드에서 돌림.
  - 트레이 스레드 → tkinter 스레드 통신은 queue.Queue로 (스레드 안전).
"""
from __future__ import annotations

import queue
import threading

import pystray
from PIL import Image, ImageDraw

from core import load_config, scan_projects
from widget import DashboardWidget, bar_color


def _summary() -> tuple[int, str]:
    """숨기지 않은 프로젝트들의 전체 진행률(%)과 트레이 툴팁 문구를 반환."""
    projects = [p for p in scan_projects(load_config()) if not p.hidden]
    done = sum(p.done for p in projects)
    total = sum(p.total for p in projects)
    todo = sum(len(p.todos) for p in projects)
    percent = round(done / total * 100) if total else 0
    title = f"프로젝트 보드 — {len(projects)}개 · 진행 {percent}% · 할 일 {todo}개"
    return percent, title


def _make_icon_image(percent: int) -> Image.Image:
    """진행률 색으로 채운 원형 트레이 아이콘 이미지."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=bar_color(percent))
    return img


def run_tray(ipc_server=None) -> None:
    """트레이 모드 실행 — 트레이 아이콘 + 클릭 시 위젯 팝업.

    ipc_server: 단일 실행 잠금 소켓. 다른 인스턴스가 신호하면 팝업을 띄움.
    """
    # 트레이 스레드가 보낸 명령을 tkinter 스레드가 꺼내 처리하기 위한 큐
    cmd_q: queue.Queue[str] = queue.Queue()

    # 중복 실행 감지 — 다른 인스턴스가 뜨면 이 인스턴스의 팝업을 띄움
    if ipc_server is not None:
        import singleton
        singleton.watch(ipc_server, lambda: cmd_q.put("show"))
    state = {"visible": False}   # 팝업이 현재 보이는 중인지

    percent, title = _summary()
    icon = pystray.Icon(
        "project_dashboard",
        icon=_make_icon_image(percent),
        title=title,
        menu=pystray.Menu(
            pystray.MenuItem("열기", lambda *a: cmd_q.put("show"), default=True),
            pystray.MenuItem("숨기기", lambda *a: cmd_q.put("hide")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", lambda *a: cmd_q.put("quit")),
        ),
    )

    def _on_ready(tray_icon) -> None:
        tray_icon.visible = True
        tray_icon.notify("프로젝트 보드가 트레이에 있음. 아이콘을 클릭하세요.",
                          "대시보드")

    # 트레이 아이콘은 별도 스레드 (메인 스레드는 tkinter mainloop가 차지)
    threading.Thread(target=lambda: icon.run(setup=_on_ready),
                     daemon=True).start()

    # 설정 저장 시 위젯이 다시 만들어질 수 있으므로 루프로 감쌈
    while True:
        app = DashboardWidget()
        # 트레이 모드에서 ✕는 종료가 아니라 트레이로 '숨기기'
        app.on_close_override = lambda: cmd_q.put("hide")
        # 닫기/열기 단축키는 팝업 보이기/숨기기를 토글
        app.hide_action = lambda: cmd_q.put("toggle")
        if state["visible"]:
            app.root.deiconify()
        else:
            app.root.withdraw()   # 시작 시엔 트레이에만 있음

        def poll() -> None:
            """트레이 스레드가 보낸 명령을 tkinter 쪽에서 처리."""
            try:
                while True:
                    cmd = cmd_q.get_nowait()
                    if cmd == "show":
                        app.root.deiconify()
                        app.root.lift()
                        state["visible"] = True
                    elif cmd == "hide":
                        app._save_geometry()
                        app.root.withdraw()
                        state["visible"] = False
                    elif cmd == "toggle":
                        if state["visible"]:
                            app._save_geometry()
                            app.root.withdraw()
                            state["visible"] = False
                        else:
                            app.root.deiconify()
                            app.root.lift()
                            state["visible"] = True
                    elif cmd == "quit":
                        app.restart = False
                        app._destroy()
                        return   # 더 이상 poll 예약 안 함
            except queue.Empty:
                pass
            app.root.after(200, poll)

        app.root.after(200, poll)
        app.root.mainloop()

        if not app.restart:
            break   # 종료 (설정 저장이면 restart=True → 루프 계속)

    icon.stop()


if __name__ == "__main__":
    run_tray()
