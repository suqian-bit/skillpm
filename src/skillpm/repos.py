"""从 Skill 仓库取代码：有 git 用 git，没有就走 GitLab archive 下 zip。"""
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from skillpm.config import cache_dir, home
from skillpm.console import DIM, RESET, die, mask, ok, remember_secret, say, warn

SSH_RE = re.compile(r"(?:git@|ssh://git@)([^:/]+)[:/](.+?)(?:\.git)?$")


def has_git():
    return shutil.which("git") is not None


# Git for Windows 默认 core.autocrlf=true，检出时把 LF 换成 CRLF——
# 文件内容一变，哈希就和 manifest 对不上，装完立刻被判成「本地已修改」。
# Skill 是数据不是源码，一律按仓库里的原样落盘。
NO_EOL_CONVERT = ["-c", "core.autocrlf=false", "-c", "core.eol=lf"]


def run_git(args, cwd=None, env=None):
    # 必须写死 utf-8：git 的输出是 UTF-8，而 text=True 默认按本机代码页解码，
    # 中文 Windows 是 GBK，遇到中文提交信息会 UnicodeDecodeError 抛在读取线程里。
    # GIT_TERMINAL_PROMPT=0：私有仓库没给令牌时，git 会在终端里问 Username，看起来像卡死了。
    full = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=full,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(mask((r.stderr or r.stdout).strip()))
    return r.stdout


def parse_ssh(url):
    """git@host:group/project.git → (host, group/project)，解析不了返回 (None, None)。"""
    m = SSH_RE.match(url or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def git_url(repo):
    """git clone 用哪个地址。

    优先 ssh；没有 ssh 但 `http` 看着就是个仓库地址（带 .git，或配了 path）时，
    直接拿 HTTP 克隆——公开仓库这样不需要任何密钥和令牌，新人零配置就能装。
    """
    if repo.get("ssh"):
        return repo["ssh"]
    base = (repo.get("git_http") or "").strip()
    if base:
        return base
    http, path = (repo.get("http") or "").rstrip("/"), (repo.get("path") or "").strip("/")
    if http.endswith(".git"):
        return http
    if http and path:
        return f"{http}/{path}.git"
    return None


def origin_of(cache):
    try:
        return run_git(["remote", "get-url", "origin"], cwd=cache).strip()
    except (RuntimeError, OSError):
        return None


def archive_url(repo, ref):
    base, path = repo.get("http"), repo.get("path")
    if not base or not path:
        return None
    proj = urllib.parse.quote(path, safe="")
    return f"{base.rstrip('/')}/api/v4/projects/{proj}/repository/archive.zip?sha={ref}"


def checkout(cache, ref, env=None):
    """把缓存切到指定 commit。要装指定提交时走这一步——
    光把 commit 记下来、安装时还拉分支最新，那锁的是个寂寞。"""
    try:
        run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=cache)
    except RuntimeError:
        # 浅克隆里没有这个 commit，单独去取
        try:
            run_git(["fetch", "--depth", "1", "origin", ref], cwd=cache, env=env)
        except RuntimeError:
            run_git(["fetch", "--unshallow"], cwd=cache, env=env)
    run_git(["checkout", "--detach", ref], cwd=cache)


def git_auth_env(repo):
    """HTTP 私有仓库走 git 时怎么带令牌。

    1.20.2 之前 git 方式压根不用令牌——`repo add … --token` 对私有仓库没用，只有下载压缩包的方式才用。
    GitLab 认「用户名 oauth2、密码是令牌」的 Basic 认证。用 GIT_CONFIG_* 环境变量传 http.extraHeader
    （git 2.31+）：不进命令行（ps 看不到），也不写进缓存目录的 .git/config。
    """
    import base64
    url, token = git_url(repo) or "", repo.get("token") or ""
    if not token or not url.startswith(("http://", "https://")):
        return {}
    basic = base64.b64encode(f"oauth2:{token}".encode()).decode()
    remember_secret(basic)
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}"}


def _fetch_git(name, repo, cache, branch):
    url = git_url(repo)
    auth = git_auth_env(repo)
    if (cache / ".git").exists() and origin_of(cache) != url:
        # 仓库地址变了（换服务器、换项目），旧缓存还指着老远端，
        # 再 fetch 只会悄悄拉到旧内容，所以直接重新 clone。
        say(f"  {DIM}{name}：仓库地址变了，重新拉一份{RESET}")
        shutil.rmtree(cache, ignore_errors=True)
    if (cache / ".git").exists():
        run_git([*NO_EOL_CONVERT, "fetch", "--depth", "1", "origin", branch], cwd=cache, env=auth)
        run_git([*NO_EOL_CONVERT, "reset", "--hard", f"origin/{branch}"], cwd=cache)
    else:
        shutil.rmtree(cache, ignore_errors=True)
        run_git([*NO_EOL_CONVERT, "clone", "--depth", "1", "-b", branch, url, str(cache)], env=auth)


def _fetch_zip(name, repo, cache, branch):
    url = archive_url(repo, branch)
    if not url:
        die(f"{name}：没有 git 命令，也没配 HTTP 仓库地址",
            f"用 skillpm repo add {name} --http <网页地址> --path <组/项目> --token <令牌> 补上")
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": repo.get("token", "")})
    tmp = home() / f"{re.sub(r'[^w.-]', '_', name)}.zip"
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as f:
            shutil.copyfileobj(resp, f)
    except urllib.error.HTTPError as e:
        die(f"{name} 下载失败：HTTP {e.code}",
            "401/403 一般是访问令牌不对或过期；404 是仓库路径不对。"
            f"用 skillpm repo add {name} ... 改。")
    except urllib.error.URLError as e:
        die(f"{name} 连不上：{mask(str(e.reason))}", "检查网络；公司内部的仓库可能要先连 VPN。")
    unzip = home() / "unzip"
    shutil.rmtree(unzip, ignore_errors=True)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(unzip)
    roots = [x for x in unzip.iterdir() if x.is_dir()]
    if not roots:
        die(f"{name}：下载的压缩包是空的")
    shutil.rmtree(cache, ignore_errors=True)
    shutil.move(str(roots[0]), str(cache))
    shutil.rmtree(unzip, ignore_errors=True)
    tmp.unlink(missing_ok=True)


# git 的报错是英文，而且真正的原因常埋在一堆输出里。常见的几种翻成人话。
_GIT_ERRORS = [
    (r"could not read Username|Authentication failed|HTTP Basic: Access denied|403",
     "GitLab 要求登录——仓库不存在，或者不是公开的（GitLab 对不存在的仓库也会要求登录）"),
    (r"Repository not found|does not appear to be a git repository|not found",
     "找不到这个仓库——地址里的组名或项目名写错了"),
    (r"Could not resolve host|Name or service not known|nodename nor servname",
     "连不上主机——主机名写错了，或者当前网络到不了（公司内部的地址要在公司网络里或连 VPN）"),
    (r"Empty reply from server|Connection reset|Recv failure",
     "连上了但对方没按 git 回话——端口不对（要和浏览器里打开 GitLab 用的地址一致，端口也要一样），"
     "或者请求被代理截走了（本机开了代理的话，内部地址要设成不走代理）"),
    (r"Connection refused|Failed to connect|Connection timed out|Operation timed out",
     "主机连得上但端口不通——端口号写错了（要和浏览器里打开 GitLab 用的地址一致，端口也要一样），或者被防火墙挡了"),
    (r"Permission denied \(publickey\)|Host key verification failed",
     "SSH 认证没过——你的 SSH key 没加到 GitLab，或者第一次连这台主机还没信任它；改用 http 地址最省事"),
    (r"Remote branch .* not found|couldn't find remote ref",
     "仓库里没有这个分支——用 --branch 指定，默认是 main"),
]


def explain_git_error(raw):
    import re as _re
    text = "\n".join(ln for ln in raw.splitlines() if not ln.startswith("Cloning into"))
    for pat, human in _GIT_ERRORS:
        if _re.search(pat, text, _re.I):
            return f"{human}\n  （git 原话：{text.strip().splitlines()[-1][:160]}）"
    return text.strip()


def fetch(name, repo, quiet=False, ref=None):
    """把某个仓库拉到本地缓存，返回目录。给了 ref 就切到那个 commit。"""
    cache = cache_dir(name)
    cache.parent.mkdir(parents=True, exist_ok=True)
    branch = repo.get("branch", "main")
    use_git = repo.get("mode", "git") == "git" and git_url(repo) and has_git()
    if use_git:
        try:
            _fetch_git(name, repo, cache, branch)
            if ref:
                checkout(cache, ref, git_auth_env(repo))
                if not quiet:
                    ok(f"{name}：已切到锁定的 {ref[:8]}")
            elif not quiet:
                ok(f"{name}：已拉到最新（git）")
            return cache
        except RuntimeError as e:
            url = git_url(repo) or ""
            e = explain_git_error(str(e))
            web = url.removesuffix(".git")
            token_how = ("加令牌：skillpm repo add <名字> <地址> --token <令牌>"
                         "（GitLab → 头像 → Preferences → Access Tokens，勾 read_repository）")
            # 提示跟着原因走——以前不管什么原因都再追一句「地址写错了，或者仓库不是公开的」，和上一行重复
            if "要求登录" in e:
                hint = f"用浏览器打开 {web}：打不开就是地址写错了；要登录才能看就是私有仓库，{token_how}"
            elif "找不到这个仓库" in e:
                hint = f"用浏览器打开 {web} 核对一下组名和项目名"
            elif any(k in e for k in ("连不上", "端口", "代理", "SSH 认证", "分支")):
                hint = None                    # 上一行已经说清楚怎么办了
            elif url.startswith(("git@", "ssh://")):
                hint = ("先手动试 ssh -T git@<GitLab 主机> 看通不通；没配过 SSH key 就改用 http 地址")
            else:
                hint = f"用浏览器打开 {web} 看能不能访问；私有仓库要{token_how}"
            die(f"{name} 拉取失败：{e}", hint)
    _fetch_zip(name, repo, cache, ref or branch)
    if not quiet:
        ok(f"{name}：已拉到{'锁定版本' if ref else '最新'}（下载压缩包）")
    return cache


def manifest_of(repo_dir, name="仓库"):
    """仓库里有哪些 Skill、什么版本、每个文件的哈希。

    有 manifest.json 就用它；**没有就当场按 skills/ 算**（和 skillpm manifest 同一套规则）。
    1.22.0 之前 manifest.json 是必需的——别的团队接入要多学一个命令，还常常改了 Skill 忘了重新生成，
    别人 update 看不到新版本。拉下来的本来就是整个仓库，现算和预先算出来的是同一份东西。
    """
    p = Path(repo_dir) / "manifest.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            die(f"{name} 的 manifest.json 解析不了：{e}",
                "删掉它也行——没有 manifest.json 时会直接按 skills/ 目录算")
    from skillpm import manifest
    doc, errors, warnings = manifest.build(repo_dir)
    if not doc["skills"]:
        die(f"{name} 里没找到能装的 Skill",
            "仓库要这样放：skills/<名字>/SKILL.md，SKILL.md 开头的 frontmatter 里写 name（和目录名一样）和 version。"
            + ("\n  具体问题：" + "；".join(errors) if errors else ""))
    for e in errors:           # 个别 Skill 不合格：跳过它，别的照常能装
        warn(f"{name}：{e}，这个先跳过")
    doc["computed"] = True     # 标一下是现算的，repo list 之类的地方可以说明
    return doc



def fetch_all(cfg, quiet=False):
    """拉所有配置过的仓库，返回 {仓库名: (目录, manifest)}。"""
    repos = cfg.get("repos") or {}
    if not repos:
        die("还没配任何 Skill 仓库",
            "跑 skillpm install 走一遍引导，或者 skillpm repo add <名字> --ssh <地址>")
    return {name: (d, manifest_of(d, name))
            for name, repo in repos.items()
            for d in [fetch(name, repo, quiet)]}
