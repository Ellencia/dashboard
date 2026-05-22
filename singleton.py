"""프로젝트 대시보드 - 단일 실행(중복 방지) + 재실행 시 기존 창 띄우기.

localhost 포트 하나를 '잠금' 겸 '신호 채널'로 씀.
  - 포트 bind 성공  = 첫 인스턴스 → 그 소켓을 watch()로 감시
  - 포트 bind 실패  = 이미 실행 중 → 그 인스턴스에 'show'를 보내고 자신은 종료

→ run.bat을 또 눌러도 새 창이 뜨는 게 아니라 기존 창이 떠오름.
"""
from __future__ import annotations

import socket
import threading

# 단일 실행 잠금 + IPC용 고정 포트 (loopback 전용, 외부 노출 없음)
_PORT = 50573


def acquire() -> socket.socket | None:
    """첫 인스턴스면 잠금 소켓을 반환. 이미 실행 중이면 신호만 보내고 None."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", _PORT))
    except OSError:
        # 포트가 잡혀 있음 = 이미 대시보드가 실행 중
        srv.close()
        _signal_existing()
        return None
    srv.listen(1)
    return srv


def _signal_existing() -> None:
    """이미 떠 있는 인스턴스에 '창을 띄워라' 신호를 보냄."""
    try:
        conn = socket.create_connection(("127.0.0.1", _PORT), timeout=1.0)
        conn.sendall(b"show")
        conn.close()
    except OSError:
        pass   # 그 사이 종료됐을 수도 있음 — 조용히 무시


def watch(srv: socket.socket, on_signal) -> None:
    """별도 스레드에서 srv를 감시. 다른 인스턴스가 접속하면 on_signal()을 호출.

    on_signal은 워커 스레드에서 불리므로, 큐에 넣는 등 스레드 안전하게 쓸 것.
    """
    def loop() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return            # 소켓이 닫힘 → 감시 종료
            try:
                conn.recv(16)
            except OSError:
                pass
            finally:
                conn.close()
            on_signal()

    threading.Thread(target=loop, daemon=True).start()
