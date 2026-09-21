"""生成 / 核对 Skill 仓库根目录的 manifest.json。

本工具靠 manifest 判断「远端有没有新版本」和「本地文件有没有被改过」，
所以它必须和 skills/ 完全一致：每个 Skill 的版本、一句话说明、每个文件的 sha256。

manifest.json 是可选的：仓库里没有，安装时就按 skills/ 当场算（同一套规则）。
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

SKIP = {".DS_Store"}
UNVERSIONED = "未标版本-"          # 没写 version 的 Skill，版本显示成「未标版本-<内容指纹>」


def content_id(files):
    """一个 Skill 所有文件哈希合起来的短指纹，内容一变就变。"""
    h = hashlib.sha256("\n".join(f"{k}:{v}" for k, v in sorted(files.items())).encode())
    return h.hexdigest()[:7]


def _field(text, name):
    """frontmatter 里的 `name: 值`，缩进的也认（metadata: 下面的 version）。"""
    m = re.search(rf"^\s*{name}:\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip().strip("\"'") if m else None


def _frontmatter(text):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[1]
    return ""


def scan(root):
    """扫 <root>/skills/*/SKILL.md，返回 (skills, 必须修的问题, 建议修的问题)。

    必须：SKILL.md 开头有 frontmatter，写了 name 就得和目录名一致。
    建议：description、version、CHANGELOG.md——不写也能装。
    """
    root = Path(root)
    base = root / "skills"
    skills, errors, warnings = {}, [], []
    if not base.is_dir():
        errors.append(f"{root} 下没有 skills/ 目录——Skill 要放在 skills/<名字>/SKILL.md")
        return skills, errors, warnings
    dirs = sorted(p for p in base.iterdir() if p.is_dir())
    for d in dirs:
        md = d / "SKILL.md"
        if not md.is_file():
            warnings.append(f"skills/{d.name}/ 里没有 SKILL.md，跳过")
            continue
        text = md.read_text(encoding="utf-8")
        front = _frontmatter(text)
        if not front:
            errors.append(f"{d.name}：SKILL.md 开头没有 --- 包起来的 frontmatter")
            continue
        name = _field(front, "name")
        if name and name != d.name:
            errors.append(f"{d.name}：SKILL.md 里 name 写的是 {name}，要和目录名一致")
            continue                  # 以前记了错还照样收进清单，装的时候就装上了
        files = {}
        for f in sorted(x for x in d.rglob("*") if x.is_file() and x.name not in SKIP
                        and "__pycache__" not in x.parts):
            files[f.relative_to(d).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
        if not _field(front, "description"):
            warnings.append(f"{d.name}：没写 description——Agent 靠它判断什么时候用这个 Skill，建议写上")
        version = _field(front, "version")
        if not version:
            # 通用的 Skill 格式只要 name 和 description，很多现成的 Skill 不写 version。
            # 那就用内容指纹当版本：文件一变指纹就变，update 照样能发现；只是看不到「1.0 → 1.1」和更新日志。
            version = UNVERSIONED + content_id(files)
            warnings.append(f"{d.name}：没写 version，按文件内容判断有没有更新"
                            "（建议加一行 version: 1.0.0，更新时才能看到版本变化和更新日志）")
        else:
            log = d / "CHANGELOG.md"
            if not log.exists():
                warnings.append(f"{d.name}：没有 CHANGELOG.md，别人更新时看不到改了什么")
            elif not re.search(rf"^##\s+{re.escape(version)}(?:\s|$)",
                               log.read_text(encoding="utf-8"), re.M):
                warnings.append(f"{d.name}：CHANGELOG.md 里没有 `## {version}` 这一节")
        skills[d.name] = {
            "version": version,
            "summary": (_field(front, "description") or "")[:120],
            "files": files,
            "bytes": sum((d / rel).stat().st_size for rel in files),
        }
    if not skills and not errors:
        errors.append(f"{base} 下一个 Skill 都没有（要有 skills/<名字>/SKILL.md）")
    return skills, errors, warnings


def build(root):
    skills, errors, warnings = scan(root)
    doc = {"generated_at": f"{datetime.now().astimezone():%Y-%m-%dT%H:%M:%S%z}",
           "skills": skills}
    return doc, errors, warnings


def stale(root):
    """已有的 manifest.json 和 skills/ 对不上的地方；对得上返回 []。"""
    p = Path(root) / "manifest.json"
    if not p.exists():
        return ["没有 manifest.json"]
    try:
        old = json.loads(p.read_text(encoding="utf-8")).get("skills") or {}
    except ValueError as e:
        return [f"manifest.json 解析不了：{e}"]
    new, _e, _w = scan(root)
    diff = []
    for n in sorted(set(old) | set(new)):
        if n not in new:
            diff.append(f"{n}：manifest 里有，skills/ 里没了")
        elif n not in old:
            diff.append(f"{n}：skills/ 里新加的，manifest 里没有")
        elif old[n].get("version") != new[n]["version"]:
            diff.append(f"{n}：版本 {old[n].get('version')} → {new[n]['version']}")
        elif old[n].get("files") != new[n]["files"]:
            diff.append(f"{n}：文件内容变了，版本号没动（{new[n]['version']}）")
    return diff
