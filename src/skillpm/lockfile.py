"""skillpm.lock：项目级安装的版本锁，随项目一起提交。

解决的是「在我机器上能用」：谁 clone 这个项目，跑一次 skillpm install，
拿到的 Skill 版本和提交锁文件时**完全一致**——因为锁的是 commit 和文件哈希，
不是「安装那一刻仓库 HEAD 是什么」。

全局安装（-g）不写锁文件：那是个人偏好，不该污染项目配置。
"""
import json
from datetime import datetime
from pathlib import Path

LOCK_NAME = "skillpm.lock"
LOCK_VERSION = 1


def find_root(start="."):
    """从当前目录往上找项目根：有锁文件的优先，其次是 .git。都没有就用当前目录。"""
    cur = Path(start).resolve()
    for d in [cur, *cur.parents]:
        if (d / LOCK_NAME).exists():
            return d
    for d in [cur, *cur.parents]:
        if (d / ".git").exists():
            return d
    return cur


def path_of(root):
    return Path(root) / LOCK_NAME


def load(root):
    p = path_of(root)
    if not p.exists():
        return {"lockfile_version": LOCK_VERSION, "skills": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise ValueError(f"{p} 不是合法 JSON，可能是合并冲突没解干净")
    data.setdefault("skills", {})
    return data


def save(root, lock):
    lock["lockfile_version"] = LOCK_VERSION
    lock["generated_at"] = f"{datetime.now().astimezone():%Y-%m-%dT%H:%M:%S%z}"
    # 按名字排序写，减少多人改动时的无谓冲突
    lock["skills"] = dict(sorted(lock["skills"].items()))
    path_of(root).write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path_of(root)


def record(lock, name, *, repo, source, commit, version, host, rel_path, files):
    lock.setdefault("skills", {})[name] = {
        "repo": repo, "source": source, "commit": commit, "version": version,
        "host": host, "path": rel_path, "files": dict(files),
    }
    return lock


def drop(lock, name):
    lock.get("skills", {}).pop(name, None)
    return lock
