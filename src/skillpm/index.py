"""生成 AGENTS.md：给宿主一份「这儿有哪些 Skill」的索引。

宿主本来就会扫目录找 SKILL.md，索引不是必需的——它的作用是让扫描更快、
也让人打开目录就知道装了什么、每个从哪来、什么版本。

只写自己管的那一段，用标记包起来；标记外面的内容一个字不动，
免得把别人手写的说明冲掉。
"""
import re
from datetime import datetime
from pathlib import Path

BEGIN = "<!-- skillpm:begin 以下内容由 skillpm 生成，手改会被覆盖 -->"
END = "<!-- skillpm:end -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def render(entries, scope):
    """entries: [{name, version, repo, summary, path}]"""
    where = "项目级（只在本项目生效）" if scope == "project" else "用户级（对所有项目生效）"
    lines = [BEGIN, "",
             f"## 已安装的 Skill（{where}）", "",
             f"共 {len(entries)} 个，由 skillpm 管理。更新：`skillpm update`；查看：`skillpm status`。", "",
             "| Skill | 版本 | 来源 | 说明 |", "|---|---|---|---|"]
    for e in sorted(entries, key=lambda x: x["name"]):
        summary = (e.get("summary") or "").replace("|", "\\|").replace("\n", " ")[:60]
        lines.append(f"| `{e['name']}` | {e['version']} | {e.get('repo') or '-'} | {summary} |")
    lines += ["", f"<sub>生成于 {datetime.now().astimezone():%Y-%m-%d %H:%M}</sub>", "", END]
    return "\n".join(lines)


def write(dest_dir, entries, scope):
    """把索引写进 <宿主目录>/AGENTS.md，保留标记外的既有内容。"""
    path = Path(dest_dir) / "AGENTS.md"
    block = render(entries, scope)
    if path.exists():
        old = path.read_text(encoding="utf-8")
        new = BLOCK_RE.sub(block, old) if BLOCK_RE.search(old) else old.rstrip() + "\n\n" + block + "\n"
    else:
        new = block + "\n"
    path.write_text(new, encoding="utf-8")
    return path
