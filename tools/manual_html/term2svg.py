#!/usr/bin/env python3
"""把一段真实的终端输出（带 ANSI 颜色）渲染成「终端窗口截图」样子的 SVG。

手册里的截图都是这么来的：在沙箱里真实跑命令、录下原始输出，再用这个脚本出图。
不截屏幕是因为：截屏要屏幕控制权限，放进手册又糊又大；SVG 清晰、几 KB、每个字都是真实输出。

中英混排对齐：浏览器里中文字宽和英文不是精确的 2:1，所以**每个字单独给横坐标**，按终端的列摆放
（SVG 的 x 可以给一串坐标）。字形保持原本宽度、不拉伸——以前用 textLength 钉整段宽度，中文被拉宽约 20%，看着扁。

用法：
    python3 term2svg.py 原始输出.log "敲的命令" 输出.svg [保留行数]
保留行数写 16 就是只留前 16 行；写 16:2 是留前 16 行 + 最后 2 行，中间标「省略」。
环境变量 PROMPT_DIR 改提示符里显示的当前目录（默认 ~）；DEMO_HOME 设成演示 HOME，输出里的它会显示成 ~。
"""
import html
import re
import sys
import unicodedata

CW, LH, FS = 8.4, 22, 14           # 每列宽（=等宽字体 14px 时一个英文字的宽度）、行高、字号
PAD_X, PAD_TOP, PAD_BOTTOM, BAR = 18, 14, 16, 34
MAX_COLS = 104
FG, BG = "#e2e8f0", "#0f172a"
PALETTE = {"90": "#7d8ba1", "91": "#f87171", "92": "#4ade80", "94": "#60a5fa", "96": "#22d3ee",
           "38;5;208": "#fb923c"}


def width(ch):
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def parse(text):
    """→ [[(文字, 颜色, 粗体), …], …]，一行一个列表。"""
    lines, cur, color, bold = [], [], FG, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", text):
        m = re.fullmatch(r"\x1b\[([0-9;]*)m", part)
        if m:
            code = m.group(1)
            if code in ("0", ""):
                color, bold = FG, False
            elif code == "1":
                bold = True
            elif code in PALETTE:
                color = PALETTE[code]
            continue
        for i, seg in enumerate(part.split("\n")):
            if i:
                lines.append(cur)
                cur = []
            if seg:
                cur.append((seg, color, bold))
    lines.append(cur)
    return lines


def wrap(line):
    """超过 MAX_COLS 的行按列折行（和真终端一样）。"""
    out, cur, col = [], [], 0
    for text, color, bold in line:
        buf = ""
        for ch in text:
            w = width(ch)
            if col + w > MAX_COLS:
                if buf:
                    cur.append((buf, color, bold))
                out.append(cur)
                cur, buf, col = [], "", 0
            buf += ch
            col += w
        if buf:
            cur.append((buf, color, bold))
    out.append(cur)
    return out


def render(raw, cmd, max_lines=None, title="zsh"):
    raw = raw.replace("\r\n", "\n").replace("\r", "")
    import os
    home = os.environ.get("DEMO_HOME")          # 演示用的 HOME 显示成 ~（别把录制人的用户名带进截图）
    if home:
        raw = raw.replace(home.rstrip("/"), "~")
    raw = "\n".join(ln for ln in raw.split("\n") if not ln.startswith("spawn "))
    raw = raw.strip("\n")
    body = [w for ln in parse(raw) for w in wrap(ln)]
    head, tail = (max_lines if isinstance(max_lines, tuple) else (max_lines, 0)) if max_lines else (None, 0)
    if head and len(body) > head + tail:
        cut = len(body) - head - tail
        note = [[(f"……（中间还有 {cut} 行，省略）" if tail else f"……（后面还有 {cut} 行，省略）", PALETTE["90"], False)]]
        body = body[:head] + note + (body[-tail:] if tail else [])
    import os
    where = os.environ.get("PROMPT_DIR", "~")          # 提示符里显示的当前目录
    prompt = [("➜ ", "#4ade80", True), (f"{where} ", "#22d3ee", True), (cmd, FG, True)]
    rows = wrap(prompt) + body
    cols = max([sum(width(c) for t, *_ in r for c in t) for r in rows] + [60])
    W = int(PAD_X * 2 + cols * CW)
    H = int(BAR + PAD_TOP + len(rows) * LH + PAD_BOTTOM)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'role="img" aria-label="终端：{html.escape(cmd)}">',
           f'<rect width="{W}" height="{H}" rx="10" fill="{BG}"/>',
           f'<rect width="{W}" height="{BAR}" rx="10" fill="#1e293b"/><rect y="{BAR - 10}" width="{W}" height="10" fill="#1e293b"/>',
           '<circle cx="20" cy="17" r="6" fill="#ff5f57"/><circle cx="40" cy="17" r="6" fill="#febc2e"/>'
           '<circle cx="60" cy="17" r="6" fill="#28c840"/>',
           f'<text x="{W / 2}" y="22" fill="#94a3b8" font-size="12" text-anchor="middle" '
           f'font-family="-apple-system,PingFang SC,Microsoft YaHei,sans-serif">{html.escape(title)}</text>',
           '<g font-family="SF Mono,Menlo,Consolas,PingFang SC,Microsoft YaHei,monospace" '
           f'font-size="{FS}">']
    for i, row in enumerate(rows):
        y = BAR + PAD_TOP + (i + 1) * LH - 6
        col = 0
        for text, color, bold in row:
            # 按「连续非空格」切成词，词里每个字按列给坐标；空格只推进列号（SVG 会吞掉首尾空格）
            for token in re.findall(r"\s+|\S+", text):
                if token.isspace():
                    col += sum(width(c) for c in token)
                    continue
                xs = []
                for ch in token:
                    xs.append(f"{PAD_X + col * CW:.1f}")
                    col += width(ch)
                wt = ' font-weight="700"' if bold else ""
                out.append(f'<text x="{" ".join(xs)}" y="{y}" fill="{color}"{wt}>{html.escape(token)}</text>')
    out.append("</g></svg>")
    return "\n".join(out)


if __name__ == "__main__":
    log, cmd, dst = sys.argv[1:4]
    limit = None
    if len(sys.argv) > 4:
        h, _, t = sys.argv[4].partition(":")
        limit = (int(h), int(t or 0))
    with open(log, encoding="utf-8", errors="replace") as f:
        svg = render(f.read(), cmd, limit)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(svg)
    print(dst)
