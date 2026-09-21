"""终端输出与交互。所有对用户说的话都从这里过，方便统一上色、打码、静音。"""
import os
import platform
import re
import sys

IS_WIN = platform.system() == "Windows"
_COLOR = not (IS_WIN and not os.environ.get("WT_SESSION")) and sys.stdout.isatty() \
    and not os.environ.get("NO_COLOR")

# 配色原则：黄色在浅色终端上最难读，所以只用来标「要你注意但没出错」，
# 而且配合前缀符号，不靠颜色单独传信息。主色走青/绿/蓝这一挂。
#   青  标题、命令、Skill 名        绿  成功、已完成
#   蓝  路径                        橙  警告（比黄色深，浅背景也看得清）
#   红  错误                        灰  补充说明
RESET, BOLD, DIM = ("\033[0m", "\033[1m", "\033[90m") if _COLOR else ("", "", "")
RED = "\033[91m" if _COLOR else ""
GREEN = "\033[92m" if _COLOR else ""
YELLOW = "\033[38;5;208m" if _COLOR else ""      # 橙，替掉原来那个发虚的亮黄
BLUE = "\033[96m" if _COLOR else ""              # 青，标题和名字
PATH_C = "\033[94m" if _COLOR else ""            # 蓝，路径
OKC = "\033[92m" if _COLOR else ""

_SECRETS = set()


def ensure_utf8_stdio():
    """输出流不是 UTF-8 时改成 UTF-8。

    Windows 上输出被重定向（管道、写文件、CI）时，Python 用系统代码页编码——英文系统是 cp1252，
    一打中文就 UnicodeEncodeError 崩掉。中文系统的代码页恰好能编中文，所以平时看不出来。
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def remember_secret(value):
    """记下一个不该出现在输出里的串（访问令牌之类）。"""
    if value and len(value) >= 6:
        _SECRETS.add(value)


def mask(text):
    text = str(text)
    for s in _SECRETS:
        text = text.replace(s, "***")
    return text


def say(text=""):
    print(mask(text))


def ok(text):
    say(f"{GREEN}✓{RESET} {text}")


def warn(text):
    say(f"{YELLOW}!{RESET} {text}")


def info(text):
    """说明性文字。用灰色但不加 dim，保证还读得清。"""
    say(f"  {DIM}{text}{RESET}")


def path(text):
    """路径单独上色，从灰字里拎出来。"""
    return f"{PATH_C}{text}{RESET}"


class Abort(Exception):
    """带解释的中止，由 cli 统一转成退出码。"""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


def die(message, hint=None):
    raise Abort(message, hint)


def _read(prompt):
    """读一行。管道/CI 这类没有交互的环境下给个能看懂的提示，别抛裸 EOFError。"""
    try:
        return input(mask(prompt))
    except EOFError:
        say()
        raise Abort("这一步要你选，但当前没有可交互的输入",
                    "在终端里直接跑，或者用参数把选择写死："
                    "--repo <仓库名>、--only <Skill名>、--all、-a <宿主>")


def ask(prompt, default=None, secret=False):
    tip = f" {DIM}[{default}]{RESET}" if default else ""
    while True:
        if secret:
            import getpass
            try:
                got = getpass.getpass(mask(f"{prompt}{tip}: ")).strip()
            except EOFError:
                raise Abort("需要输入令牌，但当前没有可交互的输入")
        else:
            got = _read(f"{prompt}{tip}: ").strip()
        if got:
            if secret:
                remember_secret(got)
            return got
        if default is not None:
            return default
        info("这项必须填")


def confirm(prompt, default=True):
    got = _read(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not got else got in ("y", "yes", "是")


ALL_WORDS = {"a", "all", "*", "全部", "全选"}


def _looks_like_path(part):
    return part.startswith(("~", "/", ".", "\\")) or "/" in part or "\\" in part \
        or (len(part) > 2 and part[1] == ":")                       # Windows 盘符 C:\...


def choose(prompt, options, preselect=None, allow_all=True, paths=None):
    """从列表里多选，返回选中的元素。

    能填的：
      回车          ＝ 选带 * 号的那几个（没有带 * 的就是一个都不选）
      a / all / * ＝ 全部（allow_all=False 时不给，比如卸载）
      1,3,5 或 1 3 5 或 2-4 ＝ 只要这几个
      0            ＝ 一个都不要
      路径         ＝ 只在传了 paths（一个 list）时认：填的路径追加进 paths，可以和序号混着填
    """
    preselect = set(range(len(options)) if preselect is None else preselect)
    if prompt:
        say(prompt)
    import unicodedata
    cols = lambda t: sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(t))
    width = max((cols(label) for label, _ in options), default=0)
    num_w = len(str(len(options)))
    for i, (label, note) in enumerate(options, 1):
        mark = "*" if i - 1 in preselect else " "
        pad = " " * (width - cols(label)) if note else ""      # 说明那一列对齐，中文按两列算
        say(f"  {mark} {str(i).rjust(num_w)}. {label}{pad}" + (f"  {DIM}{note}{RESET}" if note else ""))
    n = len(options)
    tips = []
    if not preselect:
        tips.append("回车＝一个都不选")
    elif len(preselect) == n:
        tips.append(f"回车＝全部 {n} 个")
    else:
        tips.append(f"回车＝只选带 * 号的这 {len(preselect)} 个")
    if allow_all and len(preselect) != n:
        tips.append(f"a＝全部 {n} 个")
    tips.append("只要其中几个就填序号（1,3,5 或 2-4）")
    if paths is not None:
        tips.append("列表里没有就直接填目录路径")
    tips.append("0＝都不要")
    hint = "；".join(tips)
    while True:
        got = _read(f"{DIM}{hint}{RESET}: ").strip()
        if not got:
            return [options[i] for i in sorted(preselect)]
        if got == "0":
            return []
        if got.lower() in ALL_WORDS:
            if allow_all:
                return list(options)
            info("这里不支持一次全选，请填序号")
            continue
        picked, bad, typed = [], [], []
        for chunk in re.split(r"[,，;；]+", got):
            # 逐个词看：序号/范围就是序号；其余的词如果开头像路径，就连同后面的词拼成一个路径
            # （路径里可能有空格）。这样「1,3 ~/foo/skills」「/opt/my agent/skills」都认得对。
            words = chunk.split()
            i = 0
            while i < len(words):
                part = words[i]
                m = re.fullmatch(r"(\d+)\s*[-~～]\s*(\d+)", part)
                if m and 1 <= int(m[1]) <= int(m[2]) <= n:
                    picked += [options[k - 1] for k in range(int(m[1]), int(m[2]) + 1)]
                elif part.isdigit() and 1 <= int(part) <= n:
                    picked.append(options[int(part) - 1])
                elif paths is not None and _looks_like_path(part):
                    j = i + 1
                    while j < len(words) and not re.fullmatch(r"\d+(\s*[-~～]\s*\d+)?", words[j]):
                        j += 1
                    typed.append(" ".join(words[i:j]))
                    i = j
                    continue
                else:
                    bad.append(part)
                i += 1
        if (picked or typed) and not bad:
            seen, out = set(), []
            for o in picked:                         # 去重、保持顺序
                if id(o) not in seen:
                    seen.add(id(o))
                    out.append(o)
            if paths is not None:
                paths.extend(typed)
            return out
        # 看不懂就重问，别默默当成「一个都没选」
        more = "，或者直接填目录路径" if paths is not None else ""
        info(f"没看懂「{' '.join(bad) or got}」，请填 1~{n} 之间的序号（多个用逗号隔开，范围写 2-4）{more}")


def link(url, text=None):
    """可以点的链接：输出到终端时加上 OSC 8 超链接转义（⌘/Ctrl + 点击打开）；
    接管道、写文件时只输出文字，别把转义字符混进日志。"""
    text = text or url
    if sys.stdout.isatty():
        return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"
    return text


def md_line(line):
    """更新日志是 Markdown，在终端里别把 ** 和 ` 原样打出来：
    `## 版本` 标题加粗，**加粗** 变成真加粗，`代码` 去掉反引号、换成青色。"""
    if line.startswith("## "):
        return f"{BOLD}{line[3:]}{RESET}"
    if line.startswith("### "):
        return f"{BOLD}{line[4:]}{RESET}"
    line = re.sub(r"\*\*(.+?)\*\*", lambda m: f"{BOLD}{m.group(1)}{RESET}", line)
    line = re.sub(r"`([^`]+)`", lambda m: f"{BLUE}{m.group(1)}{RESET}", line)
    return line
