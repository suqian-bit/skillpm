"""选择框：回车 / a / 序号 / 范围 / 路径。1.19.0 之前提示写「回车＝带 * 的全要」，
有人读成「装星号」还是「装全部」分不清，所以每种填法都钉一条。"""
import pytest

from skillpm import console
from skillpm.console import choose

OPTS = [(f"s{i}", "") for i in range(1, 6)]          # 5 个选项


def feed(monkeypatch, *answers, prompts=None):
    it = iter(answers)

    def fake(prompt):
        if prompts is not None:
            prompts.append(console.mask(prompt) if hasattr(console, "mask") else prompt)
        return next(it)
    monkeypatch.setattr(console, "_read", fake)


def names(picked):
    return [n for n, _ in picked]


def test_enter_takes_starred_only(monkeypatch):
    feed(monkeypatch, "")
    assert names(choose("", OPTS, preselect=[0, 2])) == ["s1", "s3"]


def test_enter_with_nothing_starred_takes_nothing(monkeypatch):
    feed(monkeypatch, "")
    assert choose("", OPTS, preselect=[]) == []


@pytest.mark.parametrize("word", ["a", "all", "ALL", "*", "全部"])
def test_all_words_take_everything(monkeypatch, word):
    feed(monkeypatch, word)
    assert names(choose("", OPTS, preselect=[0])) == [f"s{i}" for i in range(1, 6)]


@pytest.mark.parametrize("typed,want", [
    ("2,4", ["s2", "s4"]),
    ("2 4", ["s2", "s4"]),
    ("2，4", ["s2", "s4"]),
    ("2-4", ["s2", "s3", "s4"]),
    ("1,3-4", ["s1", "s3", "s4"]),
    ("3,3,1", ["s3", "s1"]),                 # 重复的只算一次
])
def test_pick_some_by_number(monkeypatch, typed, want):
    feed(monkeypatch, typed)
    assert names(choose("", OPTS)) == want


def test_zero_takes_nothing(monkeypatch):
    feed(monkeypatch, "0")
    assert choose("", OPTS) == []


def test_garbage_is_asked_again_not_treated_as_nothing(monkeypatch):
    feed(monkeypatch, "9", "4-2", "x", "2")
    assert names(choose("", OPTS)) == ["s2"]


def test_uninstall_refuses_select_all(monkeypatch):
    # 卸载不给「a＝全部」：一个键删光太危险，得重填序号
    feed(monkeypatch, "a", "1")
    assert names(choose("", OPTS, preselect=[], allow_all=False)) == ["s1"]


def test_paths_only_when_allowed(monkeypatch):
    feed(monkeypatch, "~/.foo/skills", "1")
    assert names(choose("", OPTS)) == ["s1"]          # 没开 paths：路径当成看不懂，重问


def test_paths_mixed_with_numbers(monkeypatch):
    typed = []
    feed(monkeypatch, "1, ~/.foo/skills, C:\\Users\\me\\.bar\\skills, /opt/my agent/skills")
    assert names(choose("", OPTS, paths=typed)) == ["s1"]
    assert typed == ["~/.foo/skills", "C:\\Users\\me\\.bar\\skills", "/opt/my agent/skills"]


@pytest.mark.parametrize("typed,want_names,want_paths", [
    ("1,3 ~/mine/skills", ["s1", "s3"], ["~/mine/skills"]),        # 真用的时候就这么填，1.19.0 发版前试出来的
    ("~/mine/skills 2", ["s2"], ["~/mine/skills"]),
    ("/opt/my agent/skills", [], ["/opt/my agent/skills"]),
])
def test_paths_and_numbers_separated_by_spaces(monkeypatch, typed, want_names, want_paths):
    got = []
    feed(monkeypatch, typed)
    assert names(choose("", OPTS, paths=got)) == want_names
    assert got == want_paths


def test_hint_says_exactly_what_enter_does(monkeypatch):
    seen = []
    feed(monkeypatch, "", prompts=seen)
    choose("", OPTS, preselect=[0, 1])
    assert "只选带 * 号的这 2 个" in seen[0] and "a＝全部 5 个" in seen[0]
    seen.clear()
    feed(monkeypatch, "", prompts=seen)
    choose("", OPTS)                                   # 全部预选
    assert "回车＝全部 5 个" in seen[0] and "a＝" not in seen[0]


def test_name_for_typed_path(tmp_path, monkeypatch):
    from skillpm.hosts import name_for_path
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert name_for_path(tmp_path / ".foobot" / "skills") == "foobot"
    assert name_for_path(tmp_path / "mydir") == "mydir"
    assert name_for_path(tmp_path / ".claude" / "skills") == "Claude Code"   # 表里认识的用表里的名字


def test_typed_hosts(tmp_path, monkeypatch):
    from skillpm import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".foobot" / "skills").mkdir(parents=True)
    other = tmp_path / "x" / ".foobot" / "skills"
    other.mkdir(parents=True)
    answers = iter([True])                               # 「~/.foobot 下面有 skills，装进去吗」→ 是
    monkeypatch.setattr(cli, "confirm", lambda *a, **k: next(answers))
    got = cli._typed_hosts([str(tmp_path / ".foobot"), str(other)], {})
    assert got == {"foobot": str((tmp_path / ".foobot" / "skills").resolve()),
                   "foobot-2": str(other.resolve())}      # 重名但不同目录：不覆盖
    # 不存在的目录：默认不建
    monkeypatch.setattr(cli, "confirm", lambda *a, **k: False)
    assert cli._typed_hosts([str(tmp_path / "typo" / "skills")], {}) == {}
