"""update 只更新装过的 Skill；仓库里有、本机没装的，每次都提示（不自动装），直到装上或 ignore。

2026-09-23 真踩过：仓库新加了 case-design，调度已经会调它，
组里人 update 完一切正常，本机却根本没装——到「设计用例」那步才卡住。
"""
import hashlib
import json
import shutil

import pytest

import skillpm.cli as cli
from skillpm.cli import main
from skillpm.config import cache_dir, load_config, load_state, save_config, save_state


def _add_skill(repo_dir, name, ver="1.0.0", tier=None, summary="夹具里新加的 Skill。后面不显示"):
    d = repo_dir / "skills" / name
    d.mkdir(parents=True)
    meta = f"metadata:\n  version: {ver}\n" + (f"  tier: {tier}\n" if tier else "")
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {summary}\n{meta}---\n正文\n", encoding="utf-8")
    (d / "CHANGELOG.md").write_text(f"# {name}\n\n## {ver} — 2026-01-01\n\n- 初版\n", encoding="utf-8")
    man_p = repo_dir / "manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8"))
    files = {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(d.rglob("*")) if p.is_file()}
    man["skills"][name] = {"version": ver, "summary": summary, "files": files}
    man_p.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(skillpm_home, fake_repo, host_dir, monkeypatch):
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))
    monkeypatch.setattr(cli, "fetch_all", lambda cfg, quiet=False: {
        "local": (cache_dir("local"), json.loads((cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))})
    return cache_dir("local")


def test_update_keeps_pointing_out_missing_skill_until_installed(repo, host_dir, capsys):
    assert main(["install", "demo-a", "--hosts", "H"]) == 0
    _add_skill(repo, "demo-c", summary="给缺口设计新增用例。其余不显示")
    capsys.readouterr()

    assert main(["update", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "demo-b" in out and "demo-c" in out and "skillpm install demo-b demo-c" in out
    assert "给缺口设计新增用例" in out and "其余不显示" not in out
    assert "skillpm ignore demo-b demo-c" in out, "要告诉人怎么关掉提示"
    assert not (host_dir / "demo-c").exists(), "只提示，不自动装"

    main(["update", "--yes"])
    assert "demo-c" in capsys.readouterr().out, "没装就一直提示"

    main(["status", "--offline"])
    assert "demo-c" not in capsys.readouterr().out, "离线时没拉仓库，不该乱说"
    main(["status"])
    assert "demo-c" in capsys.readouterr().out

    assert main(["install", "demo-c", "--hosts", "H"]) == 0
    capsys.readouterr()
    main(["update", "--yes"])
    out = capsys.readouterr().out
    assert "demo-c" not in out and "demo-b" in out, "装上了就不再提示"


def test_ignore_stops_the_hint_and_undo_brings_it_back(repo, capsys):
    assert main(["install", "demo-a", "--hosts", "H"]) == 0
    _add_skill(repo, "demo-c")
    assert main(["ignore", "demo-b"]) == 0
    capsys.readouterr()
    main(["update", "--yes"])
    out = capsys.readouterr().out
    assert "demo-b" not in out and "demo-c" in out
    main(["status"])
    assert "demo-b" not in capsys.readouterr().out

    main(["ignore"])
    assert "demo-b" in capsys.readouterr().out, "不写名字列出忽略了哪些"

    assert main(["ignore", "--undo", "demo-b"]) == 0
    capsys.readouterr()
    main(["update", "--yes"])
    assert "demo-b" in capsys.readouterr().out

    main(["ignore", "demo-b", "demo-c"])
    capsys.readouterr()
    main(["update", "--yes"])
    assert "本机还没装" not in capsys.readouterr().out, "全忽略了，整段都不出"


def test_update_also_mentions_new_skill_when_other_skills_were_updated(repo, capsys):
    assert main(["install", "demo-a", "--hosts", "H"]) == 0
    _add_skill(repo, "demo-c")
    man_p = repo / "manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8"))
    man["skills"]["demo-a"]["version"] = "1.1.0"
    man_p.write_text(json.dumps(man), encoding="utf-8")
    capsys.readouterr()
    assert main(["update", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "更新成功" in out and "1.1.0" in out
    assert "本机还没装" in out and "demo-c" in out


def test_tiered_variants_are_not_nagged(repo, capsys):
    """按权限分级、只装一个级别的：装了 write，新加的 admin 不算「没装」，更不能自动补上。"""
    _add_skill(repo, "x-dml-write", tier="write")
    assert main(["install", "demo-a", "x-dml-write", "--hosts", "H"]) == 0
    _add_skill(repo, "x-dml-admin", tier="admin")
    _add_skill(repo, "demo-c")
    capsys.readouterr()
    main(["update", "--yes"])
    out = capsys.readouterr().out
    assert "demo-c" in out and "x-dml-admin" not in out
    main(["status"])
    assert "x-dml-admin" not in capsys.readouterr().out


def test_repo_never_installed_from_is_not_nagged(repo, capsys):
    """配了仓库却一个都没从它装过，多半是有意不用。"""
    assert main(["install", "demo-a", "--hosts", "H"]) == 0
    state = load_state()
    for entry in state["hosts"].values():
        for rec in entry["skills"].values():
            rec["repo"] = "别的仓库"
    save_state(state)
    capsys.readouterr()
    main(["update", "--yes"])
    assert "demo-b" not in capsys.readouterr().out
