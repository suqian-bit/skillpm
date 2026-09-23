"""找项目根目录：项目级安装（-p）装到哪、status 只列当前项目的项目级安装，都靠它。"""
from pathlib import Path


def find_root(start="."):
    """从当前目录往上找有 .git 的目录当项目根；都没有就用当前目录。"""
    cur = Path(start).resolve()
    for d in [cur, *cur.parents]:
        if (d / ".git").exists():
            return d
    return cur
