"""AGENTS.md 索引：只改自己那一段，别人写的不能动。"""
from skillpm.index import BEGIN, END, render, write

ENTRIES = [{"name": "b-skill", "version": "1.0.0", "repo": "team", "summary": "第二个"},
           {"name": "a-skill", "version": "2.0.0", "repo": "team", "summary": "第一个"}]


def test_render_sorted_and_counted():
    out = render(ENTRIES, "global")
    assert out.index("a-skill") < out.index("b-skill"), "按名字排序，减少无谓 diff"
    assert "共 2 个" in out and BEGIN in out and END in out


def test_scope_wording():
    assert "只在本项目" in render(ENTRIES, "project")
    assert "所有项目" in render(ENTRIES, "global")


def test_pipe_in_summary_is_escaped():
    out = render([{"name": "x", "version": "1", "repo": "r", "summary": "a|b"}], "global")
    assert "a\\|b" in out, "竖线不转义会把表格撑坏"


def test_write_preserves_handwritten_text(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# 我手写的\n\n不能冲掉。\n", encoding="utf-8")
    write(tmp_path, ENTRIES, "global")
    text = p.read_text(encoding="utf-8")
    assert "我手写的" in text and "不能冲掉" in text and "a-skill" in text


def test_write_twice_replaces_block_not_appends(tmp_path):
    write(tmp_path, ENTRIES, "global")
    write(tmp_path, ENTRIES[:1], "global")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count(BEGIN) == 1, "重复生成不能叠加两块"
    assert "共 1 个" in text
