#!/usr/bin/env python3
"""发版前检查。CI 里跑，本地也可以手动跑。

1. 版本号变了就必须有对应的更新日志；
2. 随工具发的 docs/manual.html 必须是按当前 md 和版本号生成的——
   不然用户 skillpm docs 打开的手册和工具对不上。
"""
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):          # Windows 上重定向输出默认是系统代码页，中文会崩
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from skillpm import __version__                       # noqa: E402
from skillpm.changelog import has_entry               # noqa: E402

log = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
if not log.exists():
    sys.exit("缺 CHANGELOG.md")
if not has_entry(log.read_text(encoding="utf-8"), __version__):
    sys.exit(f"CHANGELOG.md 里没有 `## {__version__}` 这一节——改了版本号就得写清楚改了什么")
from skillpm.manual import html_meta, html_path, source_hash   # noqa: E402

ver, src = html_meta(html_path())
if ver is None:
    sys.exit("缺 docs/manual.html——跑 uvx --with markdown python tools/manual_html/build.py 生成并提交")
if ver != __version__ or src != source_hash():
    why = f"它是按 {ver} 生成的，现在是 {__version__}" if ver != __version__ else "docs/ 下的 md 或 CHANGELOG 改过了"
    sys.exit(f"docs/manual.html 过期了（{why}）——跑 uvx --with markdown python tools/manual_html/build.py 重新生成并提交")
print(f"skillpm {__version__} 的更新日志齐了，使用手册是最新的")
