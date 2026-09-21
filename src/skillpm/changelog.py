"""读 CHANGELOG：取出「比手上这个版本新」的那几节。"""
import re
from pathlib import Path


def sections_since(text, old_version):
    """返回 old_version 之后的所有小节原文；找不到 old_version 就全给。"""
    parts = re.split(r"^(##\s+\S+.*)$", text, flags=re.M)
    out = []
    for i in range(1, len(parts) - 1, 2):
        head, body = parts[i], parts[i + 1]
        fields = head.split()
        if len(fields) > 1 and fields[1] == old_version:
            break
        out.append(head.strip() + "\n" + body.strip("\n").rstrip())
    return "\n\n".join(out)


def for_skill(repo_dir, name, old_version):
    p = Path(repo_dir) / "skills" / name / "CHANGELOG.md"
    return sections_since(p.read_text(encoding="utf-8"), old_version) if p.exists() else ""


def has_entry(text, version):
    """发版检查用：CHANGELOG 里有没有这个版本的小节（整行匹配，`1.0.0-rc` 不算 `1.0.0`）。"""
    return bool(re.search(rf"^##\s+{re.escape(version)}(?:\s|$)", text, re.M))
