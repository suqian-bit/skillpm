"""安装源解析：四种写法都得认对，子路径不能丢。"""
import pytest

from skillpm.sources import locate, parse


def test_plain_name_means_configured_repo():
    s = parse("code-review")
    assert s.kind == "repo" and s.name == "code-review" and s.repo is None


def test_repo_prefixed_name():
    s = parse("我的库:some-skill", known_repos={"我的库"})
    assert s.kind == "repo" and s.repo == "我的库" and s.name == "some-skill"


def test_unknown_repo_prefix_is_rejected():
    with pytest.raises(ValueError, match="没配过"):
        parse("不存在的库:x", known_repos={"我的库"})


def test_github_with_subpath():
    s = parse("anthropics/skills/pdf")
    assert s.kind == "github" and s.subpath == "pdf" and s.name == "pdf"
    assert s.url == "https://github.com/anthropics/skills.git"


def test_github_without_subpath():
    s = parse("anthropics/skills")
    assert s.kind == "github" and s.subpath is None and s.name == "skills"


def test_git_url_with_subpath():
    s = parse("git@h:g/r.git/a/b")
    assert s.kind == "git" and s.url == "git@h:g/r.git" and s.subpath == "a/b"
    assert s.name == "b", "子路径最后一段才是 Skill 名"


def test_git_url_without_subpath():
    s = parse("git@h:g/my-skill.git")
    assert s.kind == "git" and s.subpath is None and s.name == "my-skill"


def test_local_path(tmp_path):
    d = tmp_path / "my-skill"
    d.mkdir()
    s = parse(str(d))
    assert s.kind == "local" and s.name == "my-skill"


def test_empty_is_rejected():
    with pytest.raises(ValueError):
        parse("   ")


def test_locate_prefers_subpath(tmp_path):
    (tmp_path / "nested" / "deep").mkdir(parents=True)
    (tmp_path / "nested" / "deep" / "SKILL.md").write_text("x", encoding="utf-8")
    s = parse("git@h:g/r.git/nested/deep")
    assert locate(tmp_path, s).name == "deep"


def test_locate_falls_back_to_skills_dir(tmp_path):
    (tmp_path / "skills" / "demo").mkdir(parents=True)
    (tmp_path / "skills" / "demo" / "SKILL.md").write_text("x", encoding="utf-8")
    assert locate(tmp_path, parse("demo")).name == "demo"


def test_locate_accepts_repo_root_as_skill(tmp_path):
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    assert locate(tmp_path, parse("whatever")) == tmp_path


def test_locate_reports_clearly_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="找不到"):
        locate(tmp_path, parse("nope"))


def test_team_scheme_is_accepted():
    s = parse("team://我的库/some-skill", known_repos={"我的库"})
    assert s.kind == "repo" and s.repo == "我的库" and s.name == "some-skill"


def test_team_scheme_with_deeper_subpath():
    s = parse("team://我的库/general/rc-review", known_repos={"我的库"})
    assert s.repo == "我的库" and s.name == "rc-review" and s.subpath == "general/rc-review"


def test_team_scheme_rejects_unknown_repo():
    with pytest.raises(ValueError, match="没配过"):
        parse("team://不存在/x", known_repos={"我的库"})


def test_team_scheme_needs_skill_name():
    with pytest.raises(ValueError, match="还要写 Skill 名"):
        parse("team://我的库", known_repos={"我的库"})
