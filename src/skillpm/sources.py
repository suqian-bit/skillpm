"""安装源解析：一个字符串说清「从哪拿、拿哪一个」。

支持四种写法，对应 joySkills 的四类源：

    code-review                           已配仓库里的某个 Skill（最常用）
    我的库:some-skill                      指定仓库里的某个
    team://我的库/some-skill                同上，joySkills 风格的写法
    owner/repo/skill                      GitHub 公开仓库里的某个子目录
    git@host:group/repo.git[/子路径]       任意 Git 仓库，可带子路径
    ~/Downloads/my-skill                  本地目录（调试用）

子路径是关键：仓库里可能有一堆 Skill，得能只装其中一个，
也可能 Skill 不在 skills/ 下面而在别的目录。
"""
import re
from pathlib import Path

GIT_RE = re.compile(r"^(?:git@|ssh://git@|https?://)")
GITHUB_RE = re.compile(r"^[\w.-]+/[\w.-]+(?:/(?P<sub>.+))?$")


class Source:
    """解析结果。kind 决定后面怎么取：repo / github / git / local。"""

    def __init__(self, kind, *, name=None, repo=None, url=None, subpath=None, path=None):
        self.kind, self.name, self.repo = kind, name, repo
        self.url, self.subpath, self.path = url, subpath, path

    def __repr__(self):
        return f"<Source {self.kind} name={self.name} repo={self.repo} url={self.url} sub={self.subpath}>"


def _split_git(spec):
    """把 git URL 和后面的子路径分开：…/repo.git/a/b → (…/repo.git, a/b)。"""
    if ".git/" in spec:
        url, _, sub = spec.partition(".git/")
        return url + ".git", sub or None
    return spec, None


def parse(spec, known_repos=()):
    spec = spec.strip()
    if not spec:
        raise ValueError("安装源不能为空")

    if spec.startswith("team://"):        # team://仓库名/Skill名[/更深的子路径]
        rest = spec[len("team://"):].strip("/")
        repo, _, sub = rest.partition("/")
        if not repo:
            raise ValueError("team:// 后面要写仓库名，比如 team://我的库/some-skill")
        if repo not in known_repos:
            raise ValueError(f"没配过叫「{repo}」的仓库；skillpm repo list 看看有哪些")
        if not sub:
            raise ValueError(f"team://{repo} 后面还要写 Skill 名")
        name = sub.rstrip("/").split("/")[-1]
        return Source("repo", name=name, repo=repo,
                      subpath=sub if "/" in sub else None)

    if spec.startswith(("~", ".", "/")) or Path(spec).expanduser().is_dir():
        p = Path(spec).expanduser()
        return Source("local", name=p.name, path=str(p))

    if GIT_RE.match(spec):
        url, sub = _split_git(spec)
        name = (sub.rstrip("/").split("/")[-1] if sub
                else re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1]))
        return Source("git", name=name, url=url, subpath=sub)

    if ":" in spec:                       # 仓库名:Skill名
        repo, _, name = spec.partition(":")
        if repo in known_repos:
            return Source("repo", name=name, repo=repo)
        raise ValueError(f"没配过叫「{repo}」的仓库；skillpm repo list 看看有哪些")

    m = GITHUB_RE.match(spec)
    if m and "/" in spec:
        owner_repo = "/".join(spec.split("/")[:2])
        sub = m.group("sub")
        name = (sub.rstrip("/").split("/")[-1] if sub else spec.split("/")[1])
        return Source("github", name=name,
                      url=f"https://github.com/{owner_repo}.git", subpath=sub)

    return Source("repo", name=spec)      # 光一个名字：在已配的仓库里找


def locate(repo_dir, source):
    """在拉下来的仓库里找到这个 Skill 的目录。

    先看子路径，再看 skills/<名字>，最后看仓库根就是这个 Skill 本身（只有一个 SKILL.md）。
    """
    root = Path(repo_dir)
    if source.subpath:
        p = root / source.subpath
        if (p / "SKILL.md").exists():
            return p
        raise FileNotFoundError(f"{source.subpath} 下没有 SKILL.md")
    p = root / "skills" / (source.name or "")
    if (p / "SKILL.md").exists():
        return p
    if (root / "SKILL.md").exists():
        return root
    raise FileNotFoundError(
        f"仓库里找不到 {source.name}：既没有 skills/{source.name}/SKILL.md，仓库根也不是一个 Skill")
