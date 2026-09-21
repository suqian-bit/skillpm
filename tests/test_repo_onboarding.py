"""别的团队接自己的仓库：repo add 直接写地址、当场试拉、缺 manifest 就不存；skillpm manifest 生成。
以及报错全是中文、带常用写法。"""
import json
import shutil
import subprocess

import pytest

from skillpm.cli import main
from skillpm.config import load_config


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


@pytest.fixture
def git_repo(fake_repo):
    if not shutil.which("git"):
        pytest.skip("没有 git")
    git(fake_repo, "init", "-q", "-b", "main")
    git(fake_repo, "add", "-A")
    git(fake_repo, "commit", "-q", "-m", "init")
    return fake_repo


def test_repo_add_checks_and_saves(skillpm_home, git_repo, capsys):
    assert main(["repo", "add", "别的团队", "--ssh", str(git_repo)]) == 0
    out = capsys.readouterr().out
    assert "拉得到，里面有 2 个 Skill" in out and "demo-a" in out
    assert "别的团队" in load_config()["repos"]


def test_repo_without_manifest_works(skillpm_home, git_repo, capsys):
    # 1.22.0 起 manifest.json 可选：没有就按 skills/ 当场算
    (git_repo / "manifest.json").unlink()
    git(git_repo, "commit", "-q", "-am", "去掉 manifest")
    assert main(["repo", "add", "别的团队", "--ssh", str(git_repo)]) == 0
    out = capsys.readouterr().out
    assert "拉得到，里面有 2 个 Skill" in out and "按 skills/ 目录算" in out


def test_repo_without_skills_is_refused(skillpm_home, git_repo, capsys):
    (git_repo / "manifest.json").unlink()
    shutil.rmtree(git_repo / "skills")
    (git_repo / "README.md").write_text("空仓库\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "清空")
    assert main(["repo", "add", "别的团队", "--ssh", str(git_repo)]) == 1
    out = capsys.readouterr().out
    assert "没找到能装的 Skill" in out and "skills/<名字>/SKILL.md" in out and "没有保存" in out
    assert "别的团队" not in (load_config().get("repos") or {})


def test_bad_skill_is_skipped_others_still_listed(tmp_path, fake_repo, capsys):
    from skillpm.repos import manifest_of
    (fake_repo / "manifest.json").unlink()
    (fake_repo / "skills" / "demo-a" / "SKILL.md").write_text("---\nname: 别的名字\nversion: 1.0.0\n---\n", encoding="utf-8")
    man = manifest_of(fake_repo, "某仓库")
    assert list(man["skills"]) == ["demo-b"] and man.get("computed")
    out = capsys.readouterr().out
    assert "demo-a" in out and "目录名一致" in out and "跳过" in out    # 点名哪个、为什么跳过


def test_manifest_still_wins_when_present(fake_repo):
    from skillpm.repos import manifest_of
    doc = json.loads((fake_repo / "manifest.json").read_text(encoding="utf-8"))
    doc["skills"]["demo-a"]["version"] = "9.9.9"         # 和 SKILL.md 不一样：有 manifest 就以它为准，行为不变
    (fake_repo / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    man = manifest_of(fake_repo)
    assert man["skills"]["demo-a"]["version"] == "9.9.9" and not man.get("computed")


def test_update_sees_new_version_without_manifest(skillpm_home, fake_repo, host_dir, monkeypatch, capsys):
    """没有 manifest 的仓库：改了 SKILL.md 的 version，update 就能看到——不会再有「忘了重新生成」。"""
    from skillpm.config import cache_dir, load_config, save_config
    import skillpm.cli as cli
    from skillpm.repos import manifest_of
    (fake_repo / "manifest.json").unlink()
    cfg = load_config()
    cfg["repos"] = {"团队": {"ssh": "", "http": "", "path": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("团队"))
    monkeypatch.setattr(cli, "fetch_all", lambda cfg, quiet=False: {"团队": (cache_dir("团队"), manifest_of(cache_dir("团队"), "团队"))})
    assert main(["install", "--all", "--hosts", "H"]) == 0
    md = cache_dir("团队") / "skills" / "demo-a" / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.1.0") + "新内容\n", encoding="utf-8")
    assert main(["update", "--yes"]) == 0
    assert "新内容" in (host_dir / "demo-a" / "SKILL.md").read_text(encoding="utf-8")


def test_repo_add_takes_url_directly(skillpm_home):
    assert main(["repo", "add", "a", "http://gitlab.example.com:82/组/仓库.git", "--no-check"]) == 0
    assert main(["repo", "add", "b", "https://gitlab.example.com/g/sub/p", "--no-check"]) == 0
    assert main(["repo", "add", "c", "git@gitlab.example.com:g/p.git", "--no-check"]) == 0
    r = load_config()["repos"]
    assert (r["a"]["http"], r["a"]["path"]) == ("http://gitlab.example.com:82", "组/仓库")
    assert (r["b"]["http"], r["b"]["path"]) == ("https://gitlab.example.com", "g/sub/p")
    assert r["c"]["ssh"] == "git@gitlab.example.com:g/p.git"


def test_repo_add_rejects_bad_url(skillpm_home, capsys):
    assert main(["repo", "add", "x", "http://only-host", "--no-check"]) == 1
    assert "缺项目路径" in capsys.readouterr().out


def test_bare_repo_shows_examples_then_lists(skillpm_home, capsys):
    assert main(["repo"]) == 0
    out = capsys.readouterr().out
    assert "常用写法" in out and "skillpm repo add" in out


def test_errors_are_chinese_with_examples(skillpm_home, capsys):
    with pytest.raises(SystemExit) as e:
        main(["repo", "foo"])
    assert e.value.code == 2
    out = capsys.readouterr()
    text = out.out + out.err
    assert "只能是" in text and "常用写法" in text
    for english in ("usage:", "error:", "invalid choice", "argument action"):
        assert english not in text, english


def test_help_is_chinese(capsys):
    with pytest.raises(SystemExit):
        main(["repo", "-h"])
    out = capsys.readouterr().out
    assert out.startswith("用法：") and "显示这份帮助" in out and "usage" not in out


def test_manifest_command_matches_fixture(fake_repo, capsys):
    want = json.loads((fake_repo / "manifest.json").read_text(encoding="utf-8"))["skills"]
    (fake_repo / "manifest.json").unlink()
    assert main(["manifest", str(fake_repo)]) == 0
    got = json.loads((fake_repo / "manifest.json").read_text(encoding="utf-8"))["skills"]
    assert {n: (v["version"], v["files"]) for n, v in got.items()} == \
           {n: (v["version"], v["files"]) for n, v in want.items()}
    assert main(["manifest", str(fake_repo), "--check"]) == 0


def test_manifest_check_catches_unbumped_change(fake_repo, capsys):
    assert main(["manifest", str(fake_repo)]) == 0
    (fake_repo / "skills" / "demo-a" / "references" / "note.md").write_text("改了\n", encoding="utf-8")
    assert main(["manifest", str(fake_repo), "--check"]) == 1
    assert "版本号没动" in capsys.readouterr().out


def test_skill_without_version_is_accepted(fake_repo, capsys):
    # 1.24.0 起 version 可选：通用 Skill 格式只要 name 和 description
    from skillpm.manifest import UNVERSIONED
    (fake_repo / "skills" / "demo-a" / "SKILL.md").write_text("---\nname: demo-a\ndescription: 演示\n---\n正文\n", encoding="utf-8")
    assert main(["manifest", str(fake_repo)]) == 0
    out = capsys.readouterr().out
    assert "没写 version" in out and "按文件内容判断" in out
    doc = json.loads((fake_repo / "manifest.json").read_text(encoding="utf-8"))
    assert doc["skills"]["demo-a"]["version"].startswith(UNVERSIONED)


def test_missing_description_only_warns(fake_repo, capsys):
    (fake_repo / "skills" / "demo-a" / "SKILL.md").write_text("---\nname: demo-a\nversion: 1.0.0\n---\n", encoding="utf-8")
    (fake_repo / "manifest.json").unlink()
    assert main(["manifest", str(fake_repo), "--check"]) == 0
    assert "没写 description" in capsys.readouterr().out


def test_unversioned_skill_updates_when_content_changes(skillpm_home, fake_repo, host_dir, monkeypatch, capsys):
    """没写 version 的 Skill：内容一变，update 就能看到，并真的更新。"""
    from skillpm.config import cache_dir, load_config, save_config
    import skillpm.cli as cli
    from skillpm.repos import manifest_of
    (fake_repo / "manifest.json").unlink()
    md = fake_repo / "skills" / "demo-a" / "SKILL.md"
    md.write_text("---\nname: demo-a\ndescription: 演示\n---\n第一版\n", encoding="utf-8")
    cfg = load_config()
    cfg["repos"] = {"团队": {"ssh": "", "http": "", "path": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("团队"))
    monkeypatch.setattr(cli, "fetch_all", lambda cfg, quiet=False: {"团队": (cache_dir("团队"), manifest_of(cache_dir("团队"), "团队"))})
    assert main(["install", "--all", "--hosts", "H"]) == 0
    assert main(["update", "--yes"]) == 0
    assert "都是最新的" in capsys.readouterr().out, "内容没变不该提示更新"
    (cache_dir("团队") / "skills" / "demo-a" / "SKILL.md").write_text("---\nname: demo-a\ndescription: 演示\n---\n第二版\n", encoding="utf-8")
    assert main(["update", "--yes"]) == 0
    assert "第二版" in (host_dir / "demo-a" / "SKILL.md").read_text(encoding="utf-8")

def test_top_help_is_grouped(capsys):
    with pytest.raises(SystemExit):
        main(["-h"])
    out = capsys.readouterr().out
    assert out.index("日常") < out.index("配置") < out.index("维护")
    assert "其他" not in out, "有命令没归组——加到 cli.HELP_GROUPS 里"
    from skillpm.cli import build_parser
    subs = build_parser()._sub_names()
    for name in subs:                               # 每个命令都列出来，而且只列一次
        assert sum(1 for ln in out.splitlines() if ln.split() and ln.split()[0] == name) == 1, name
    assert "usage" not in out and "--ssh" not in out

def test_sub_help_unchanged_by_grouping(capsys):
    with pytest.raises(SystemExit):
        main(["install", "-h"])
    out = capsys.readouterr().out
    assert out.startswith("用法：skillpm install") and "--hosts" in out and "日常" not in out

def test_manifest_check_without_manifest_validates_skills(fake_repo, capsys):
    (fake_repo / "manifest.json").unlink()
    assert main(["manifest", str(fake_repo), "--check"]) == 0
    assert "都合格" in capsys.readouterr().out
    assert not (fake_repo / "manifest.json").exists(), "--check 不该生成文件"
    (fake_repo / "skills" / "demo-a" / "SKILL.md").write_text("---\nname: 改错了\nversion: 1.0.0\n---\n", encoding="utf-8")
    assert main(["manifest", str(fake_repo), "--check"]) == 1
    assert "要和目录名一致" in capsys.readouterr().out
