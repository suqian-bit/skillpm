"""更新日志：只取比手上版本新的那几节。"""
from skillpm.changelog import has_entry, sections_since

TEXT = """# 日志

## 1.2.0 — 2026-03-01

- 新功能 C

## 1.1.0 — 2026-02-01

- 新功能 B

## 1.0.0 — 2026-01-01

- 初版
"""


def test_only_newer_sections():
    got = sections_since(TEXT, "1.0.0")
    assert "1.2.0" in got and "1.1.0" in got
    assert "初版" not in got               # 手上已经有 1.0.0，不该再讲一遍


def test_latest_means_nothing_new():
    assert sections_since(TEXT, "1.2.0") == ""


def test_unknown_version_returns_all():
    assert sections_since(TEXT, "0.9.0").count("##") == 3


def test_has_entry_matches_whole_version():
    assert has_entry(TEXT, "1.1.0")
    assert not has_entry(TEXT, "1.1")         # 不能被前缀糊弄
    assert not has_entry("## 1.1.0-rc — x\n", "1.1.0")
