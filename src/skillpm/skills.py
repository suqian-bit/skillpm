"""装 Skill、算本地改动、报冲突。冲突只报告不动手，像 git 那样交给用户处理。"""
import difflib
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path

from skillpm.config import backup_dir
from skillpm.console import (BLUE, BOLD, DIM, GREEN, PATH_C, RED, RESET, YELLOW,
                              die, info, say, warn)

MAX_DIFF_FILES = 5          # 超过这么多文件就只列文件名，不然刷屏
MAX_DIFF_LINES = 24         # 每个文件最多显示这么多行差异
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_version(skill_dir):
    f = Path(skill_dir) / "SKILL.md"
    if not f.exists():
        return None
    m = re.search(r"^\s*version:\s*(\S+)", f.read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1) if m else None


def install(repo_dir, name, info_entry, dest_dir, backup_existing=False):
    """把仓库里的 Skill 复制到宿主目录。能走到这儿说明冲突检查已经放行。

    backup_existing：`--force` 覆盖别人的东西时传 True。
    「覆盖掉就找不回来」这种话不该出现在一个管理工具里，所以先备份再覆盖。
    """
    src = Path(repo_dir) / "skills" / name
    dst = Path(dest_dir) / name
    if not src.is_dir():
        die(f"仓库里没有 {name}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if backup_existing:
            b = backup(dest_dir, name, read_version(dst) or "未知版本")
            if b:
                say(f"  {DIM}原来那份已备份到 {b}{RESET}")
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)
    # 记「实际落盘的」哈希，不是 manifest 里的那份。
    # 这条记录的用途是「用户后来改没改过」，那就必须以写下去的内容为准；
    # 借用 manifest 的哈希，只要检出环节动过一个字节（比如 Windows 的 CRLF 转换），
    # 装完第一眼就会被判成「本地已修改」。
    return {"version": info_entry["version"],
            "files": {rel: digest(dst / rel)
                      for rel in (info_entry.get("files") or {})
                      if (dst / rel).exists()},
            "installed_at": f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S}"}


def same_but_for_line_endings(path, sha):
    """磁盘上这个文件，除了行尾之外和记录里的是不是一回事。

    1.14.1 之前的安装记录存的是 manifest 里的哈希（Mac 上按 LF 算的），
    而 Git for Windows 会把检出的文件转成 CRLF——老记录配上新磁盘文件，
    每一个都对不上，升级后满屏「本地改过」。那不是用户改的，是行尾。

    把磁盘内容的 CRLF 折回 LF 再比一次：能对上就说明内容没动过。
    真改了一个字的，折完照样对不上，照报不误。
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return False
    if b"\r\n" not in raw:
        return False
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == sha


def local_changes(dest_dir, name, record):
    """装的时候记了哈希，现在再算一遍看动没动过。目录整个没了返回 None。"""
    root = Path(dest_dir) / name
    if not root.is_dir():
        return None
    changed, missing = [], []
    for rel, sha in (record.get("files") or {}).items():
        f = root / rel
        if not f.exists():
            missing.append(rel)
        elif digest(f) != sha and not same_but_for_line_endings(f, sha):
            changed.append(rel)
    return {"changed": sorted(changed), "missing": sorted(missing)}


def backup(dest_dir, name, version):
    src = Path(dest_dir) / name
    if not src.is_dir():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = backup_dir() / name / f"{version}-{stamp}"
    n = 2
    while dst.exists():        # 同一秒里备份两次不能互相覆盖
        dst = backup_dir() / name / f"{version}-{stamp}-{n}"
        n += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=IGNORE)
    return dst


def _read_lines(path):
    try:
        return Path(path).read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        return None


def print_file_diff(local, remote, rel):
    """把「本地这份」和「仓库那份」的差异按 diff 格式打出来，带行号。"""
    say(f"    {BOLD}{rel}{RESET}")
    a, b = _read_lines(remote), _read_lines(local)
    if a is None or b is None:
        ls = Path(local).stat().st_size if Path(local).exists() else 0
        rs = Path(remote).stat().st_size if Path(remote).exists() else 0
        say(f"      {DIM}二进制文件，内容不同（本地 {ls} 字节，仓库 {rs} 字节）{RESET}")
        return
    lines = list(difflib.unified_diff(a, b, fromfile="仓库版本", tofile="你本地的", lineterm="", n=2))
    shown = 0
    for ln in lines[2:]:                       # 前两行是文件名，上面已经标了
        if shown >= MAX_DIFF_LINES:
            say(f"      {DIM}…… 还有 {len(lines) - 2 - shown} 行差异{RESET}")
            break
        text = ln.rstrip("\n")
        color = {"@": BLUE, "+": GREEN, "-": RED}.get(text[:1] if not text.startswith("@@") else "@", DIM)
        say(f"      {color}{text}{RESET}")
        shown += 1


def _wrap_names(names, width=84):
    """一行塞几个名字，别一个名字占一行也别拖成超长一行。"""
    lines, cur = [], ""
    for n in names:
        piece = n if not cur else f"{cur}、{n}"
        if len(piece) > width:
            lines.append(cur)
            cur = n
        else:
            cur = piece
    if cur:
        lines.append(cur)
    return lines


def _names_of(items, *kinds):
    """这几类冲突涉及哪些 Skill，去重排序——用来拼成能直接粘的命令。"""
    return sorted({c["name"] for c in items if c["kind"] in kinds})


class ConflictLog:
    """收集冲突，最后统一报告。工具本身不做取舍。"""

    def __init__(self):
        self.items = []

    def __len__(self):
        return len(self.items)

    def add(self, host, name, why, detail=None, how=None, brief=None, kind="other", path=None):
        """brief 给「一句话就说清」的冲突用，detail 留给真要展开看的（本地改过）。

        kind 决定最后给哪种解法——「不是本工具装的」根本没法 uninstall，
        给错解法比不给还糟。
        """
        self.items.append({"host": host, "name": name, "why": why, "how": how,
                           "kind": kind, "path": str(path) if path else None})
        if brief:
            warn(f"{name}　{brief}")
        else:
            warn(f"{name} 冲突：{why}")
        for line in (detail or []):
            say(f"    {line}")

    def check(self, host, dest_dir, name, record, force=False, repo_dir=None):
        """返回 True 表示有冲突、这一项不要动。"""
        if force:
            return False
        dst = Path(dest_dir) / name
        if record is None:
            if dst.exists():
                ver = read_version(dst) or "看不出来"
                # 这类冲突一句话就够：目标已经有了、是哪一版。路径都一样，没必要每条都印一遍
                self.add(host, name, "目标位置已经有一份，不是本工具装的",
                         how="本工具不覆盖自己没装过的东西",
                         brief=f"已存在 {BOLD}{ver}{RESET}，不是本工具装的 → 跳过",
                         kind="foreign", path=dst)
                return True
            return False
        diff = local_changes(dest_dir, name, record)
        if diff is None:
            self.add(host, name, "安装记录里有，但目录已经不在了", [f"位置：{dst}"],
                     "可以直接重装：加 --force 或先 uninstall", kind="gone", path=dst)
            return True
        if diff["changed"] or diff["missing"]:
            n = len(diff["changed"]) + len(diff["missing"])
            self.add(host, name, f"本地改过，{n} 个文件和仓库不一致", kind="ours", path=dst)
            if repo_dir is not None:
                self._detail(dest_dir, name, diff, repo_dir)
            return True
        return False

    def _detail(self, dest_dir, name, diff, repo_dir):
        root, src = Path(dest_dir) / name, Path(repo_dir) / "skills" / name
        say(f"  位置：{PATH_C}{root}{RESET}")
        for rel in diff["changed"][:MAX_DIFF_FILES]:
            print_file_diff(root / rel, src / rel, rel)
        if len(diff["changed"]) > MAX_DIFF_FILES:
            rest = diff["changed"][MAX_DIFF_FILES:]
            say(f"    {DIM}还有 {len(rest)} 个文件也不一样：{'、'.join(rest)}{RESET}")
        for rel in diff["missing"]:
            say(f"    {BOLD}{rel}{RESET}")
            say(f"      {DIM}本地这个文件没了{RESET}")

    def report(self):
        """返回退出码：有冲突 1，没有 0。"""
        if not self.items:
            return 0
        say()
        say(f"{YELLOW}{BOLD}有 {len(self.items)} 处冲突没处理{RESET}")
        grouped = {}
        for c in self.items:
            grouped.setdefault((c["why"], c["how"]), []).append((c["host"], c["name"]))
        for (why, how), items in grouped.items():
            hosts = {h for h, _ in items}
            # 都在同一个宿主就把宿主名提出来，别每条都带一遍
            head = f"  {YELLOW}{why}{RESET}　{DIM}（{len(items)} 项"
            head += f"，都在 {hosts.pop()}）{RESET}" if len(hosts) == 1 else f"）{RESET}"
            say(head)
            names = [n for _, n in items] if len(hosts) == 0 else [f"{h}/{n}" for h, n in items]
            for line in _wrap_names(sorted(names)):
                say(f"    {line}")
            if how:
                say(f"    {DIM}{how}{RESET}")
        say()
        kinds = {c["kind"] for c in self.items}
        if "ours" in kinds or "gone" in kinds:
            mine = _names_of(self.items, "ours", "gone")
            info("本工具装的那些（本地改过）——两条路：")
            # 把名字直接拼进命令里：写 <Skill名> 等于让人再翻一遍上面的列表
            say(f"  1. 不要本地改动了：{BOLD}skillpm uninstall {' '.join(mine)}{RESET}，再 skillpm install")
            say("  2. 想留着：自己把改动合进去，或者先拷走再装")
        if "foreign" in kinds:
            foreign = [c for c in self.items if c["kind"] == "foreign"]
            names = _names_of(self.items, "foreign")
            say()
            info("不是本工具装的那些——uninstall 卸不掉（它只管自己装的），要这么处理：")
            say(f"  1. 让本工具接管（只动这{'一个' if len(names) == 1 else '几个'}，别的不受影响）：")
            say(f"     {BOLD}skillpm install --force --only {' '.join(names)}{RESET}")
            say(f"     {DIM}覆盖前会把原来那份完整备份到 ~/.skillpm/backup/{RESET}")
            if len(names) > 1:
                say(f"     {DIM}不加 --only 就是把上面这 {len(names)} 个一起接管{RESET}")
            say("  2. 自己处理：把目录挪走或删掉，再 skillpm install")
            for c in foreign[:3]:
                if c["path"]:
                    say(f"     {DIM}{c['name']}：{RESET}{PATH_C}{c['path']}{RESET}")
            if len(foreign) > 3:
                say(f"     {DIM}…… 还有 {len(foreign) - 3} 个，位置在同一个目录下{RESET}")
        return 1
