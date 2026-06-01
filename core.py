"""프로젝트 대시보드 - 데이터 수집 모듈.

각 프로젝트 폴더의 STATUS.md(진행률·할 일)와 update.md(변경 이력)를 읽음.
표시 방식(위젯 / 배경 합성 / 트레이)과 무관하게 모든 모드가 이 모듈을 공용으로 사용함.

STATUS.md 형식 예시:
    # 표시할 프로젝트 이름
    > 한 줄 메모 (선택)
    - [x] 끝난 작업
    - [ ] 남은 작업

update.md 형식 예시 (최신 날짜를 위에):
    # 변경 이력
    ## 2026-05-20
    - 가장 최근에 한 일
    ## 2026-05-19
    - 그 전에 한 일
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# 이 파일(core.py)이 들어있는 폴더 = 대시보드 폴더
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATUS_FILENAME = "STATUS.md"
UPDATE_FILENAME = "update.md"

# 마크다운 체크박스 한 줄을 인식하는 정규식.
#   "- [ ] 할 일"  /  "- [x] 끝난 일"  /  "* [X] ..." 모두 매칭
# 그룹1 = 체크 표시(공백/x/X), 그룹2 = 항목 텍스트
_CHECK_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.+?)\s*$")

# update.md 파싱용 정규식
_HEADING2_RE = re.compile(r"^##\s+(.+?)\s*$")            # "## 제목"
_DATE_RE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}")  # 2026-05-20 등
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")          # "- 내용"


@dataclass
class TodoItem:
    """STATUS.md의 체크박스 한 줄."""

    text: str
    done: bool
    line_no: int          # STATUS.md 안에서 몇 번째 줄인지 (0부터 시작)
    project_name: str     # 어느 프로젝트에 속한 항목인지


@dataclass
class Project:
    """STATUS.md 한 개에서 읽어낸 프로젝트 한 개."""

    name: str
    folder: Path
    status_path: Path
    note: str = ""
    items: list[TodoItem] = field(default_factory=list)
    update_path: Path | None = None   # update.md 경로 (없으면 None)
    last_update: str = ""             # 가장 최근 변경 날짜
    last_change: str = ""             # 가장 최근 변경 요약 한 줄
    hidden: bool = False              # 위젯에서 숨김 처리됐는지
    collapsed: bool = False           # 카드가 접힌 상태인지

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def done(self) -> int:
        return sum(1 for it in self.items if it.done)

    @property
    def percent(self) -> int:
        """완료 비율(0~100). 항목이 없으면 0."""
        if self.total == 0:
            return 0
        return round(self.done / self.total * 100)

    @property
    def todos(self) -> list[TodoItem]:
        """아직 완료되지 않은 항목만."""
        return [it for it in self.items if not it.done]


# config.json이 없거나 키가 빠졌을 때 사용하는 기본값
DEFAULT_CONFIG = {
    # 프로젝트들을 찾을 최상위 폴더 (기본: 대시보드 폴더의 부모)
    "root": str(BASE_DIR.parent),
    # 명시적으로 추적할 프로젝트 경로 목록 (비우면 auto_discover만 사용)
    "projects": [],
    # True면 root 아래를 재귀적으로 훑어 STATUS.md가 있는 폴더를 자동으로 찾음
    "auto_discover": True,
    # 자동 탐색 시 root에서 몇 단계까지 내려가 STATUS.md를 찾을지
    "scan_depth": 4,
    # 자동 탐색에서 제외할 폴더 이름 목록
    "exclude": [],
    # 위젯에서 숨긴 프로젝트들의 폴더 이름 목록
    "hidden": [],
    # 위젯에서 카드를 접어 둔 프로젝트들의 폴더 이름 목록
    "collapsed": [],
    # 카드를 드래그해 정한 프로젝트 표시 순서 (폴더 이름 목록)
    "project_order": [],
    # 몇 초마다 파일을 다시 읽어 화면을 갱신할지
    "refresh_seconds": 30,
    # 표시 모드: "widget"(항상 위 위젯 창) 또는 "tray"(트레이 아이콘)
    "display_mode": "widget",
    # 위젯 모드 전용 설정
    "widget": {
        "x": 60,              # 창 가로 위치(px)
        "y": 60,              # 창 세로 위치(px)
        "width": 340,         # 창 너비(px)
        "height": 0,          # 창 높이(px). 0이면 내용에 맞춰 자동
        "opacity": 0.96,      # 투명도 (0.0~1.0)
        "theme": "dark",      # "dark" 또는 "light"
        "topmost": True,      # 항상 다른 창 위에 표시
        "max_todos": 12,      # 할 일 목록에 한 번에 보여줄 최대 개수
        "todos_max_height": 240,   # 할 일 목록 영역 최대 높이(px) — 넘으면 스크롤
        "todos_collapsed": False,  # 할 일 목록을 접어 뒀는지
        "collapse_highlight": True,  # 접었을 때 제목 막대를 강조색으로
        "collapse_hotkey": "ctrl+alt+d",  # 접기/펴기 전역 단축키 (빈 값=끔)
        "hide_hotkey": "ctrl+alt+s",      # 닫기/열기 전역 단축키 (빈 값=끔)
    },
}


def load_config() -> dict:
    """config.json을 읽어 dict로 반환. 빠진 키는 기본값으로 채움."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_cfg = json.load(f)
    else:
        user_cfg = {}

    # 최상위 키는 얕게, widget은 한 단계 더 깊게 병합
    merged = {**DEFAULT_CONFIG, **user_cfg}
    merged["widget"] = {**DEFAULT_CONFIG["widget"], **user_cfg.get("widget", {})}
    return merged


def save_config(cfg: dict) -> None:
    """config.json에 설정을 저장 (한글 깨짐 방지 위해 UTF-8)."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _parse_status(path: Path, project_name: str) -> tuple[str, list[TodoItem]]:
    """STATUS.md 파일 한 개를 읽어 (메모, 항목목록)을 반환."""
    note = ""
    items: list[TodoItem] = []
    lines = path.read_text(encoding="utf-8").splitlines()

    for line_no, line in enumerate(lines):
        m = _CHECK_RE.match(line)
        if m:
            items.append(
                TodoItem(
                    text=m.group(2),
                    done=m.group(1).lower() == "x",
                    line_no=line_no,
                    project_name=project_name,
                )
            )
        elif not note and line.startswith(">"):
            # 첫 번째 인용(>) 줄을 한 줄 메모로 사용
            note = line.lstrip("> ").strip()

    return note, items


def _parse_update(path: Path) -> tuple[str, str]:
    """update.md에서 가장 최근 변경의 (날짜, 요약 한 줄)을 뽑음.

    날짜가 들어간 첫 번째 "## 제목"을 최신 항목으로 봄.
    ("## Current State" 처럼 날짜 없는 제목은 건너뜀 → PPS 형식과도 호환)
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    for i, line in enumerate(lines):
        hm = _HEADING2_RE.match(line)
        if not hm:
            continue
        heading = hm.group(1)
        dm = _DATE_RE.search(heading)
        if not dm:
            continue  # 날짜 없는 제목은 최신 항목으로 보지 않음

        date = dm.group(0).replace(".", "-").replace("/", "-")

        # 제목에서 날짜 뒷부분을 요약으로 사용 ("— 설명" 형태면 그 뒤만)
        desc = heading[dm.end():].strip(" —–-()[]·:")
        for sep in ("—", "–", " - "):
            if sep in desc:
                desc = desc.split(sep)[-1].strip()
                break

        # 제목에 설명이 없으면 그 아래 첫 번째 글머리표를 요약으로 사용
        if not desc:
            for nxt in lines[i + 1:]:
                if _HEADING2_RE.match(nxt):
                    break  # 다음 항목 시작 전까지만 탐색
                bm = _BULLET_RE.match(nxt)
                if bm:
                    desc = bm.group(1).strip()
                    break

        return date, desc

    return "", ""


def _read_project(folder: Path) -> Project | None:
    """폴더 하나를 읽어 Project 객체로. STATUS.md가 없으면 None."""
    status_path = folder / STATUS_FILENAME
    if not status_path.exists():
        return None

    text = status_path.read_text(encoding="utf-8")

    # 첫 번째 "# 제목"을 표시 이름으로, 없으면 폴더 이름을 사용
    name = folder.name
    for line in text.splitlines():
        if line.startswith("# "):
            name = line[2:].strip()
            break

    note, items = _parse_status(status_path, name)

    # update.md가 있으면 최근 변경 정보도 읽음 (없어도 무방)
    update_path = folder / UPDATE_FILENAME
    last_update, last_change = "", ""
    if update_path.exists():
        last_update, last_change = _parse_update(update_path)
    else:
        update_path = None

    return Project(name=name, folder=folder, status_path=status_path,
                   note=note, items=items, update_path=update_path,
                   last_update=last_update, last_change=last_change)


# 자동 탐색에서 건너뛸 폴더 이름 (코드/빌드 부산물 등)
_SKIP_DIR_NAMES = {"__pycache__", "node_modules", "site-packages",
                   "dist", "build"}


def _should_skip_dir(name: str) -> bool:
    """자동 탐색에서 건너뛸 폴더 이름인지 (숨김 폴더·venv·빌드 폴더)."""
    if name.startswith("."):
        return True
    if "venv" in name.lower():
        return True
    return name in _SKIP_DIR_NAMES


def _discover(root: Path, max_depth: int, exclude: set[str]) -> list[Path]:
    """root 아래에서 STATUS.md가 있는 폴더(=프로젝트)를 재귀적으로 찾음.

    - STATUS.md를 찾으면 그 폴더 안으로는 더 내려가지 않음 (프로젝트 루트로 봄)
    - 숨김 폴더·venv·__pycache__ 등과 exclude 목록은 건너뜀
    - root에서 max_depth 단계까지만 내려감
    """
    found: list[Path] = []

    def walk(folder: Path, depth: int) -> None:
        if (folder / STATUS_FILENAME).exists():
            found.append(folder)
            return                       # 프로젝트 폴더 — 내부는 더 안 봄
        if depth >= max_depth:
            return
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return                       # 권한 없음 등은 조용히 건너뜀
        for child in children:
            if not child.is_dir():
                continue
            if child.name in exclude or _should_skip_dir(child.name):
                continue
            walk(child, depth + 1)

    walk(root, 0)
    return found


def scan_projects(cfg: dict) -> list[Project]:
    """설정에 따라 프로젝트들을 찾아 Project 목록으로 반환."""
    root = Path(cfg["root"]).resolve()
    folders: list[Path] = []

    # 1) config.json의 projects 목록에 명시된 폴더 (root 밖이거나 강제 포함용)
    for entry in cfg.get("projects", []):
        p = Path(entry)
        if not p.is_absolute():
            p = root / p
        folders.append(p.resolve())

    # 2) auto_discover: root 아래를 재귀적으로 훑어 STATUS.md 폴더 자동 추가
    if cfg.get("auto_discover", True) and root.exists():
        max_depth = int(cfg.get("scan_depth", 4))
        exclude = set(cfg.get("exclude", []))
        for child in _discover(root, max_depth, exclude):
            rp = child.resolve()
            if rp not in folders:
                folders.append(rp)

    hidden_names = set(cfg.get("hidden", []))
    collapsed_names = set(cfg.get("collapsed", []))
    projects: list[Project] = []
    for folder in folders:
        proj = _read_project(folder)
        if proj is not None:
            proj.hidden = proj.folder.name in hidden_names
            proj.collapsed = proj.folder.name in collapsed_names
            projects.append(proj)

    # 사용자가 카드 드래그로 정한 순서대로 정렬.
    # project_order에 없는 새 프로젝트는 맨 뒤로 (정렬이 안정적이라 발견 순서 유지).
    order = cfg.get("project_order", [])
    rank = {name: i for i, name in enumerate(order)}
    projects.sort(key=lambda p: rank.get(p.folder.name, len(order)))
    return projects


def _toggle_in_config_list(key: str, folder_name: str) -> tuple[bool, list]:
    """config.json의 리스트형 키(hidden/collapsed)에서 항목을 넣거나 뺌.

    저장 직전 디스크의 config를 다시 읽으므로, 위젯이 떠 있는 동안 사용자가
    직접 고친 다른 항목(projects 등)은 덮어쓰지 않음.
    반환: (새 상태 True=목록에 있음, 갱신된 목록)
    """
    disk = load_config()
    items = disk.get(key, [])
    if folder_name in items:
        items.remove(folder_name)
        new_state = False
    else:
        items.append(folder_name)
        new_state = True
    disk[key] = items
    save_config(disk)
    return new_state, items


def toggle_hidden(cfg: dict, folder_name: str) -> bool:
    """프로젝트의 숨김 상태를 뒤집어 config.json에 저장. 새 상태(True=숨김)를 반환."""
    new_state, items = _toggle_in_config_list("hidden", folder_name)
    cfg["hidden"] = items   # 호출한 쪽(위젯)의 메모리 상태도 맞춰 줌
    return new_state


def toggle_collapsed(cfg: dict, folder_name: str) -> bool:
    """프로젝트 카드의 접힘 상태를 뒤집어 config.json에 저장. 새 상태(True=접힘)를 반환."""
    new_state, items = _toggle_in_config_list("collapsed", folder_name)
    cfg["collapsed"] = items
    return new_state


def set_project_order(cfg: dict, folder_names: list[str]) -> None:
    """프로젝트 표시 순서(폴더 이름 목록)를 config.json에 저장.

    저장 직전 디스크 config를 다시 읽으므로 다른 항목은 덮어쓰지 않음.
    호출한 쪽(위젯)의 cfg 메모리 상태도 함께 맞춰 줌.
    """
    disk = load_config()
    disk["project_order"] = list(folder_names)
    save_config(disk)
    cfg["project_order"] = list(folder_names)


def toggle_item(item: TodoItem, status_path: Path) -> None:
    """STATUS.md에서 해당 항목의 체크 상태를 뒤집고 파일을 다시 저장.

    line_no가 외부 편집으로 어긋났을 수 있으므로, 그 줄이 더 이상
    체크박스가 아니면 같은 텍스트를 가진 줄을 다시 찾아 처리함.
    """
    lines = status_path.read_text(encoding="utf-8").splitlines()
    idx = item.line_no

    # 저장해 둔 줄 번호가 여전히 유효한지 확인
    if not (0 <= idx < len(lines) and _CHECK_RE.match(lines[idx])):
        idx = None
        for i, line in enumerate(lines):
            m = _CHECK_RE.match(line)
            if m and m.group(2) == item.text:
                idx = i
                break
        if idx is None:
            return  # 해당 항목을 찾지 못하면 아무것도 하지 않음

    line = lines[idx]
    if "[ ]" in line:
        lines[idx] = line.replace("[ ]", "[x]", 1)
    else:
        lines[idx] = re.sub(r"\[[xX]\]", "[ ]", line, count=1)

    status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------
# GUI 편집용 — STATUS.md / update.md 를 해당 줄만 고쳐 쓰는 함수들
# ------------------------------------------------------------------
def _write_lines(path: Path, lines: list[str]) -> None:
    """줄 목록을 UTF-8로 저장 (끝에 줄바꿈 1개 보장)."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_project_name(status_path: Path, name: str) -> None:
    """STATUS.md의 '# 제목' 줄을 새 이름으로 교체 (없으면 맨 위에 추가)."""
    lines = status_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i] = f"# {name}"
            break
    else:
        lines.insert(0, f"# {name}")
    _write_lines(status_path, lines)


def set_project_note(status_path: Path, note: str) -> None:
    """STATUS.md의 첫 '> 메모' 줄을 교체. 빈 값이면 메모 줄을 지움."""
    lines = status_path.read_text(encoding="utf-8").splitlines()
    note_idx = next((i for i, ln in enumerate(lines) if ln.startswith(">")),
                    None)
    if not note.strip():
        if note_idx is not None:
            del lines[note_idx]
    elif note_idx is not None:
        lines[note_idx] = f"> {note}"
    else:
        # 메모 줄이 없으면 '# 제목' 바로 다음에 끼워 넣음
        title_idx = next((i for i, ln in enumerate(lines)
                          if ln.startswith("# ")), -1)
        lines.insert(title_idx + 1, f"> {note}")
    _write_lines(status_path, lines)


def add_item(status_path: Path, text: str) -> None:
    """STATUS.md에 '- [ ] text' 한 줄 추가 (마지막 체크박스 다음, 없으면 맨 끝)."""
    lines = status_path.read_text(encoding="utf-8").splitlines()
    last = -1
    for i, line in enumerate(lines):
        if _CHECK_RE.match(line):
            last = i
    new_line = f"- [ ] {text}"
    if last >= 0:
        lines.insert(last + 1, new_line)
    else:
        lines.append(new_line)
    _write_lines(status_path, lines)


def rename_item(status_path: Path, old_text: str, new_text: str) -> None:
    """STATUS.md에서 old_text 항목의 텍스트만 교체 (체크 상태는 유지)."""
    lines = status_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = _CHECK_RE.match(line)
        if m and m.group(2) == old_text:
            mark = "x" if m.group(1).lower() == "x" else " "
            lines[i] = f"- [{mark}] {new_text}"
            break
    _write_lines(status_path, lines)


def delete_item(status_path: Path, text: str) -> None:
    """STATUS.md에서 해당 텍스트의 체크박스 줄을 삭제."""
    lines = status_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = _CHECK_RE.match(line)
        if m and m.group(2) == text:
            del lines[i]
            break
    _write_lines(status_path, lines)


def set_item_done(status_path: Path, text: str, done: bool) -> None:
    """STATUS.md에서 해당 항목의 체크 상태를 done 값으로 맞춤."""
    lines = status_path.read_text(encoding="utf-8").splitlines()
    mark = "x" if done else " "
    for i, line in enumerate(lines):
        m = _CHECK_RE.match(line)
        if m and m.group(2) == text:
            lines[i] = f"- [{mark}] {text}"
            break
    _write_lines(status_path, lines)


def reorder_items(status_path: Path, ordered_texts: list[str]) -> None:
    """STATUS.md의 체크박스 줄들을 ordered_texts 순서대로 재배치.

    체크박스가 아닌 줄(제목·메모·빈 줄 등)의 위치는 그대로 두고,
    체크박스 줄들이 있던 자리에만 새 순서로 다시 채움.
    ordered_texts에 없는 체크박스 줄은 원래 순서대로 맨 뒤에 둠
    (드래그 도중 다른 편집이 겹쳐도 줄이 사라지지 않게 하는 안전장치).
    """
    lines = status_path.read_text(encoding="utf-8").splitlines()
    check_idx = [i for i, l in enumerate(lines) if _CHECK_RE.match(l)]
    remaining = [lines[i] for i in check_idx]   # 아직 배치 안 한 체크박스 줄

    ordered: list[str] = []
    for text in ordered_texts:
        for j, line in enumerate(remaining):
            if _CHECK_RE.match(line).group(2) == text:
                ordered.append(remaining.pop(j))
                break
    ordered.extend(remaining)   # 목록에 없던 줄은 원래 순서로 뒤에

    for slot, line in zip(check_idx, ordered):
        lines[slot] = line
    _write_lines(status_path, lines)


def add_update_entry(update_path: Path, text: str) -> None:
    """update.md 오늘 날짜 블록에 변경 한 줄 추가 (블록/파일 없으면 만듦)."""
    today = date.today().isoformat()
    if update_path.exists():
        lines = update_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = ["# 변경 이력", ""]
    bullet = f"- {text}"

    today_idx = None
    for i, line in enumerate(lines):
        m = _HEADING2_RE.match(line)
        if m and today in m.group(1):
            today_idx = i
            break

    if today_idx is not None:
        # 오늘 블록 헤더 다음(빈 줄은 건너뜀)에 글머리표 삽입 = 맨 위 항목
        pos = today_idx + 1
        while pos < len(lines) and lines[pos].strip() == "":
            pos += 1
        lines.insert(pos, bullet)
    else:
        # 오늘 블록을 새로 만들어 첫 ## 블록 앞에 삽입
        first_h2 = next((i for i, ln in enumerate(lines)
                         if _HEADING2_RE.match(ln)), None)
        block = [f"## {today}", "", bullet, ""]
        if first_h2 is not None:
            lines[first_h2:first_h2] = block
        else:
            if lines and lines[-1].strip() != "":
                lines.append("")
            lines.extend(block)
    _write_lines(update_path, lines)


def safe_folder_name(name: str) -> str:
    """프로젝트 이름을 폴더 이름으로 쓸 수 있게 정리 (윈도우 금지 문자 제거)."""
    bad = set('\\/:*?"<>|')
    cleaned = "".join(c for c in name if c not in bad)
    return cleaned.strip().rstrip(". ")   # 끝의 마침표·공백은 윈도우에서 불가


def create_project(parent: Path, folder_name: str, display_name: str) -> Path:
    """새 프로젝트 폴더와 STATUS.md / update.md 를 만들고 폴더 경로를 반환."""
    folder = parent / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    status_path = folder / STATUS_FILENAME
    if not status_path.exists():
        status_path.write_text(
            f"# {display_name}\n\n- [ ] 첫 할 일\n", encoding="utf-8")

    update_path = folder / UPDATE_FILENAME
    if not update_path.exists():
        update_path.write_text(
            f"# 변경 이력\n\n## {date.today().isoformat()}\n\n- 프로젝트 시작\n",
            encoding="utf-8")
    return folder


if __name__ == "__main__":
    # 디버그용: 현재 인식되는 프로젝트들을 터미널에 출력
    config = load_config()
    print(f"root = {config['root']}")
    found = scan_projects(config)
    if not found:
        print("STATUS.md가 있는 프로젝트를 찾지 못함.")
    for proj in found:
        print(f"\n[{proj.name}] {proj.percent}%  ({proj.done}/{proj.total})")
        if proj.note:
            print(f"  메모: {proj.note}")
        if proj.last_update:
            print(f"  최근: {proj.last_update}  {proj.last_change}")
        for it in proj.todos:
            print(f"  - [ ] {it.text}")
