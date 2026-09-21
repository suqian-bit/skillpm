"""第一次用的引导：地址 → 名字 → 试拉；私有仓库要登录时问令牌。以及 git 方式真的带上令牌。"""
import base64
import subprocess

import pytest

import skillpm.cli as cli
from skillpm.console import Abort


def _script(monkeypatch, answers):
    it = iter(answers)
    asked = []

    def fake_ask(prompt, default=None, secret=False):
        asked.append(prompt.strip())
        got = next(it)
        return got if got != "" else default
    monkeypatch.setattr(cli, "ask", fake_ask)
    monkeypatch.setattr(cli, "detect", lambda: {})
    return asked


def _fetcher(monkeypatch, fake_repo, fail_first=None):
    calls = []

    def fake_fetch(name, repo, quiet=False, ref=None):
        calls.append(dict(repo))
        if fail_first and len(calls) == 1:
            raise Abort(fail_first)
        return fake_repo
    monkeypatch.setattr(cli, "fetch", fake_fetch)
    return calls


def test_no_default_repo_address_is_required(skillpm_home, fake_repo, monkeypatch, capsys):
    # 2.0.0 起没有内置的默认仓库：地址直接回车会要求必须填（用真的 ask，只假冒键盘输入）
    from skillpm import console
    answers = iter(["", "http://gitlab.example.com/ops/skills.git", ""])
    monkeypatch.setattr(console, "_read", lambda prompt: next(answers))
    monkeypatch.setattr(cli, "detect", lambda: {})
    _fetcher(monkeypatch, fake_repo)
    cfg = cli.onboarding({})
    assert list(cfg["repos"]) == ["ops"]
    out = capsys.readouterr().out
    assert "这项必须填" in out and "里面有 2 个 Skill" in out


def test_other_department_address_and_group_as_default_name(skillpm_home, fake_repo, monkeypatch):
    asked = _script(monkeypatch, ["http://gitlab.example.com/ops/skills.git", ""])
    _fetcher(monkeypatch, fake_repo)
    cfg = cli.onboarding({})
    assert "ops" in cfg["repos"], "默认名应取地址里的组名"
    assert asked[0].startswith("仓库地址"), "先问地址，再问名字"


def test_wrong_address_asks_again(skillpm_home, fake_repo, monkeypatch, capsys):
    _script(monkeypatch, ["http://gitlab.example.com/ops/typo.git", "", "http://gitlab.example.com/ops/skills.git", ""])
    calls = _fetcher(monkeypatch, fake_repo, fail_first="ops 拉取失败：找不到这个仓库——地址里的组名或项目名写错了")
    cfg = cli.onboarding({})
    assert len(calls) == 2 and cfg["repos"]["ops"]["path"] == "ops/skills"
    assert "找不到这个仓库" in capsys.readouterr().out


def test_private_repo_asks_for_token_and_retries(skillpm_home, fake_repo, monkeypatch):
    _script(monkeypatch, ["http://gitlab.example.com/ops/skills.git", "", "tok-123456789"])
    calls = _fetcher(monkeypatch, fake_repo, fail_first="ops 拉取失败：GitLab 要求登录——仓库不存在，或者不是公开的")
    cfg = cli.onboarding({})
    assert calls[1]["token"] == "tok-123456789"
    assert cfg["repos"]["ops"]["token"] == "tok-123456789"


def test_bad_url_format_is_asked_again(skillpm_home, fake_repo, monkeypatch, capsys):
    _script(monkeypatch, ["gitlab 上那个", "http://gitlab.example.com/ops/skills.git", ""])
    _fetcher(monkeypatch, fake_repo)
    assert "ops" in cli.onboarding({})["repos"]
    assert "看不懂这个地址" in capsys.readouterr().out


# ── git 方式带令牌 ─────────────────────────────────────────────────────────

def test_git_gets_token_via_env_not_argv(tmp_path, monkeypatch):
    from skillpm import repos
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw.get("env") or {}
        (tmp_path / "c" / ".git").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(repos.subprocess, "run", fake_run)
    repo = {"http": "http://gitlab.example.com", "path": "ops/skills", "token": "tok-abcdef123", "mode": "git"}
    repos._fetch_git("ops", repo, tmp_path / "c", "main")
    assert "tok-abcdef123" not in " ".join(seen["argv"]), "令牌不能出现在命令行里"
    env = seen["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0", "私有仓库没令牌时不该让 git 在终端里问用户名"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    basic = env["GIT_CONFIG_VALUE_0"].split("Basic ", 1)[1]
    assert base64.b64decode(basic).decode() == "oauth2:tok-abcdef123"


def test_no_token_no_auth_header(tmp_path, monkeypatch):
    from skillpm import repos
    assert repos.git_auth_env({"http": "http://h", "path": "g/p"}) == {}
    assert repos.git_auth_env({"ssh": "git@h:g/p.git", "token": "tok-abcdef123"}) == {}, "SSH 不用令牌"


@pytest.mark.parametrize("raw,want", [
    ("fatal: could not read Username for 'http://h': terminal prompts disabled", "要登录才能看就是私有仓库"),
    ("fatal: repository 'http://h/g/p.git/' not found", "核对一下组名和项目名"),
    ("fatal: unable to access 'http://h/g/p.git/': Could not resolve host: h", None),
    ("fatal: unable to access 'http://h/g/p.git/': Empty reply from server", None),
])
def test_fetch_failure_hint_matches_reason(skillpm_home, monkeypatch, raw, want):
    # 提示跟着原因走，不再每种都追一句「地址写错了，或者仓库不是公开的」
    from skillpm import repos
    def boom(*a, **k):
        raise RuntimeError(raw)
    monkeypatch.setattr(repos, "_fetch_git", boom)
    monkeypatch.setattr(repos, "has_git", lambda: True)
    with pytest.raises(Abort) as e:
        repos.fetch("x", {"http": "http://h", "path": "g/p", "mode": "git"})
    hint = e.value.hint
    assert (want in hint) if want else hint is None, hint
    assert "常见原因" not in (hint or "")
