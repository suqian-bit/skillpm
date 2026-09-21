"""两个仓库里有同名 Skill：装的是哪个仓库的，更新、检查、看状态就只认那个仓库。

1.20.0 之前按名字「先配的仓库优先」：从乙装的 demo-a，update 会拿甲的版本去比、
去覆盖，悄悄把来源换成甲。`install 乙:demo-a` 也会被说成「仓库里都没有」。
"""
import json
import shutil

import pytest

from skillpm.cli import main


def _make(repo, ver, body):
    import hashlib
    d = repo / "skills" / "demo-a"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: demo-a\nversion: {ver}\n---\n{body}\n", encoding="utf-8")
    files = {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(d.rglob("*")) if p.is_file()}
    (repo / "manifest.json").write_text(json.dumps(
        {"skills": {"demo-a": {"version": ver, "summary": body, "files": files}}},
        ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def two_repos(skillpm_home, tmp_path, host_dir, monkeypatch):
    """甲先配，乙后配，都有 demo-a；甲 1.0.0，乙 5.0.0。"""
    from skillpm.config import cache_dir, load_config, save_config
    import skillpm.cli as cli
    cfg = load_config()
    blank = {"ssh": "", "http": "", "path": "", "branch": "main", "mode": "git"}
    cfg["repos"] = {"甲": dict(blank), "乙": dict(blank)}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    for name, ver, body in (("甲", "1.0.0", "甲的内容"), ("乙", "5.0.0", "乙的内容")):
        _make(cache_dir(name), ver, body)

    def fake_fetch_all(cfg, quiet=False):
        return {n: (cache_dir(n), json.loads((cache_dir(n) / "manifest.json").read_text(encoding="utf-8")))
                for n in (cfg.get("repos") or {})}
    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)
    return host_dir


def body(host_dir):
    return (host_dir / "demo-a" / "SKILL.md").read_text(encoding="utf-8")


def test_install_scoped_name_picks_that_repo(two_repos):
    assert main(["install", "乙:demo-a", "--hosts", "H"]) == 0
    assert "乙的内容" in body(two_repos)


def test_update_sticks_to_the_repo_it_came_from(two_repos, capsys):
    from skillpm.config import cache_dir
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    assert "乙的内容" in body(two_repos)
    # 甲先配、甲的版本号不同——旧逻辑会把它当成「可更新」并用甲的覆盖
    capsys.readouterr()
    assert main(["update", "--yes"]) == 0
    assert "乙的内容" in body(two_repos), "update 把来源从乙换成了甲"
    assert main(["check"]) == 0
    assert "1.0.0" not in capsys.readouterr().out          # 不该提示「可更新到甲的 1.0.0」
    # 乙真出了新版本：照常更新，而且还是乙的
    shutil.rmtree(cache_dir("乙") / "skills")
    _make(cache_dir("乙"), "5.1.0", "乙的新内容")
    assert main(["update", "--yes"]) == 0
    assert "乙的新内容" in body(two_repos)


def test_status_compares_with_its_own_repo(two_repos, capsys):
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "可更新" not in out


def test_removed_source_repo_is_not_silently_swapped(two_repos, capsys):
    from skillpm.config import load_config, save_config
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    cfg = load_config()
    cfg["repos"].pop("乙")
    save_config(cfg)
    capsys.readouterr()
    main(["update", "--yes"])
    out = capsys.readouterr().out
    assert "乙的内容" in body(two_repos), "来源仓库删掉后，不该拿甲的同名 Skill 顶上"
    assert "乙" in out and "不在" in out


# ── 1.20.2：装过甲的，再装乙的同名 Skill，要问一句，默认不换 ─────────────────

def _state_repo(name="demo-a"):
    from skillpm.config import load_state
    return load_state()["hosts"]["H"]["skills"][name]["repo"]


def test_switching_source_is_refused_without_tty(two_repos, capsys):
    assert main(["install", "--repo", "甲", "--all", "--hosts", "H"]) == 0
    capsys.readouterr()
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 1   # 脚本要能看出没装上
    out = capsys.readouterr().out
    assert "甲的内容" in body(two_repos) and _state_repo() == "甲"
    assert "现在装的是「甲」" in out and "--force" in out and "没换来源" in out


def test_force_switches_and_update_follows_new_source(two_repos, capsys):
    assert main(["install", "--repo", "甲", "--all", "--hosts", "H"]) == 0
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H", "--force"]) == 0
    assert "乙的内容" in body(two_repos) and _state_repo() == "乙"
    assert "来源从 甲 换成了 乙" in capsys.readouterr().out
    assert main(["update", "--yes"]) == 0
    assert "乙的内容" in body(two_repos)


@pytest.mark.parametrize("answer,want", [(True, "乙的内容"), (False, "甲的内容")])
def test_interactive_asks_and_respects_answer(two_repos, monkeypatch, answer, want):
    import skillpm.cli as cli
    assert main(["install", "--repo", "甲", "--all", "--hosts", "H"]) == 0
    asked = []
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "confirm", lambda prompt, default=True: asked.append((prompt, default)) or answer)
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    assert asked and asked[0][1] is False, "要问，而且默认是「不换」"
    assert want in body(two_repos)


def test_same_repo_reinstall_does_not_ask(two_repos, monkeypatch, capsys):
    import skillpm.cli as cli
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    monkeypatch.setattr(cli, "confirm", lambda *a, **k: pytest.fail("同一个仓库重装不该问"))
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    assert "现在装的是" not in capsys.readouterr().out


def test_index_names_the_real_source(two_repos):
    assert main(["install", "--repo", "乙", "--all", "--hosts", "H"]) == 0
    # 再用混合汇总表跑一次 install（点名甲的，没终端→不换）：索引会重写，
    # 旧逻辑按汇总表（甲优先）写来源，就把装着的乙的写成了甲的
    main(["install", "甲:demo-a", "--hosts", "H"])
    assert "乙的内容" in body(two_repos)
    idx = (two_repos / "AGENTS.md").read_text(encoding="utf-8")
    assert "乙" in idx and "甲" not in idx and "5.0.0" in idx
