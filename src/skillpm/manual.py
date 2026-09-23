"""图文使用手册：随工具一起发的 docs/使用手册.html。

HTML 由 tools/manual_html/build.py 从几份 md 生成（要 markdown 库，只有发版的人需要）。
生成时把「来源指纹」和版本号写进 <meta>；tools/check_release.py 用这里同一个函数重新算，
md 改了没重新生成、或者版本号对不上就不让发——用户手里的手册不会和工具对不上。
"""
import hashlib
import re
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ["docs/快速上手.md", "docs/命令手册.md", "docs/接入自己的Skill仓库.md", "CHANGELOG.md"]
HTML = "docs/使用手册.html"


def source_files(root=ROOT):
    """生成手册用到的全部文件：几份 md、CHANGELOG，以及 docs/img/ 下的截图。"""
    imgs = sorted(p.relative_to(root).as_posix() for p in (Path(root) / "docs" / "img").glob("*.svg"))
    return SOURCES + imgs


def source_hash(root=ROOT):
    h = hashlib.sha256()
    for rel in source_files(root):
        h.update(rel.encode())
        # 换行统一成 \n：Windows 上 git 可能把 md 检出成 CRLF，内容没变指纹不该变
        h.update((Path(root) / rel).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def html_path(root=ROOT):
    return Path(root) / HTML


def browser_url(root=ROOT):
    """手册的绝对地址，复制到浏览器地址栏就能打开。

    带 file:// 前缀：Chrome 认光秃秃的 /Users/… 路径，Safari 不认，带上前缀哪个浏览器都行。
    中文不做百分号编码——地址栏认得，编码了反而没人看得懂。
    """
    return file_url(html_path(root).resolve().as_posix())


def file_url(posix):
    """macOS：file:///Users/…；Windows：file:///C:/Users/…（反斜杠换成正斜杠，盘符前补一个 /）。

    空格换成 %20：Windows 用户名常带空格，地址里有空格，浏览器可能当成搜索词而不是地址。
    """
    posix = posix.replace(" ", "%20")
    return "file://" + (posix if posix.startswith("/") else "/" + posix)


def open_command(root=ROOT):
    """在终端里打开手册的命令，复制粘贴就能用。

    macOS 自带的「终端」点不开 file:// 链接（⌘ 单击、双击、右键都不行，实测），
    所以给一条各系统自己的「打开文件」命令，哪个终端都能用。
    也不带 OSC 8 超链接转义：Windows 的老式 cmd 不认识，会原样打成乱码。
    Windows 用 explorer 而不用 start：start 在 PowerShell 里是 Start-Process，`start "" 路径` 会报错。
    """
    import sys
    p = html_path(root).resolve()
    if sys.platform.startswith("win"):
        return f'explorer "{p}"'
    home = Path.home()
    try:
        shown = "~/" + p.relative_to(home).as_posix()
    except ValueError:
        shown = str(p)
    return ("open " if sys.platform == "darwin" else "xdg-open ") + shown


def html_meta(path):
    """从生成好的 HTML 里读出 (版本号, 来源指纹)；没有就 (None, None)。"""
    try:
        text = Path(path).read_text(encoding="utf-8")[:4000]
    except OSError:
        return None, None
    ver = re.search(r'<meta name="skillpm-version" content="([^"]+)"', text)
    src = re.search(r'<meta name="skillpm-source" content="([^"]+)"', text)
    return (ver.group(1) if ver else None), (src.group(1) if src else None)


def open_manual(root=ROOT):
    """用默认浏览器打开。返回 (文件路径, 是否打开成功)；文件不在返回 (None, False)。"""
    p = html_path(root)
    if not p.exists():
        return None, False
    try:
        opened = webbrowser.open(p.resolve().as_uri())
    except Exception:            # 没有图形界面、没有浏览器
        opened = False
    return p, opened
