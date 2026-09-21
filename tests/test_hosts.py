"""宿主目录表与探测。"""
import os

from skillpm.hosts import CATALOG, confidence, detect, expand


def test_catalog_entries_well_formed():
    for name, (cands, proj, conf, note) in CATALOG.items():
        assert cands, f"{name} 没有候选路径"
        assert proj is None or not proj.startswith("/"), f"{name} 的项目级目录要是相对路径：{proj}"
        assert conf in ("verified", "likely"), f"{name} 的可信度标错了：{conf}"
        assert isinstance(note, str)


def test_only_coding_agents_have_project_scope():
    # 默认是用户级：大多数 Agent 全局生效。只有编程类 Agent 才填项目级目录。
    from skillpm.hosts import project_capable, project_dir, supports_project
    assert supports_project("Claude Code") and project_dir("Claude Code") == ".claude/skills"
    assert supports_project("Cursor") and project_dir("Cursor") == ".cursor/skills"
    assert not supports_project("WorkBuddy"), "WorkBuddy 全局生效，不该有项目级"
    assert not supports_project("Gemini CLI")
    assert "WorkBuddy" not in project_capable()


def test_project_dirs_are_host_native():
    # 项目级跟随宿主自己的约定，不自建 .skillpm/
    from skillpm.hosts import project_capable, project_dir
    assert not any(project_dir(n).startswith(".skillpm") for n in project_capable())


def test_detect_project_only_returns_existing(tmp_path):
    from skillpm.hosts import detect_project
    assert detect_project(tmp_path) == {}        # 空项目不该报出一堆宿主
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    assert list(detect_project(tmp_path)) == ["Claude Code"]


def test_known_hosts_marked_verified():
    # 这几个在真机上确认过，不许悄悄降级成猜的
    for name in ("Claude Code", "Codex", "WorkBuddy", "WorkBuddy-AI", "Qoder", "Windsurf", "Agents"):
        assert confidence(name) == "verified"


def test_expand_drops_unresolved_windows_vars(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert expand("%APPDATA%/X/skills") is None
    assert expand("~/x").is_absolute()


def test_detect_only_returns_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".codex" / "skills").mkdir(parents=True)
    found = detect()
    assert "Codex" in found
    for name, path in found.items():
        assert os.path.isdir(path) or os.path.isdir(os.path.dirname(path))


def test_qoder_detected_from_home(tmp_path, monkeypatch):
    # 装了 Qoder 却探不到——当时目录表里压根没有它。
    # 只要 ~/.qoder 在（哪怕还没有 skills 子目录），就该被探出来，项目级也要认 .qoder/skills。
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".qoder").mkdir()
    found = detect()
    assert found.get("Qoder") == str(tmp_path / ".qoder" / "skills")
    from skillpm.hosts import project_dir
    assert project_dir("Qoder") == ".qoder/skills"


# ── 1.18.0：自动发现「家目录的隐藏文件夹下有 skills」 ────────────────────

def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def _skill(d, name="demo"):
    (d / name).mkdir(parents=True)
    (d / name / "SKILL.md").write_text("---\nname: demo\n---\n")


def test_auto_discovers_unknown_hidden_agent(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    _skill(home / ".foobot" / "skills")                 # 表里没有的新 Agent
    (home / ".config" / "barcli" / "skills").mkdir(parents=True)   # ~/.config 下、空的也算
    found = detect()
    assert found["foobot"] == str(home / ".foobot" / "skills")
    assert found["barcli"] == str(home / ".config" / "barcli" / "skills")
    assert confidence("foobot") == "auto"
    from skillpm.hosts import describe
    assert "自动发现" in describe("foobot")


def test_auto_discover_ignores_noise(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    _skill(home / ".skillpm" / "skills")                      # 工具自己的暂存区
    _skill(home / ".codex" / "vendor_imports" / "skills")      # 宿主内置件：两层深，不看
    (home / ".datadump" / "skills").mkdir(parents=True)
    (home / ".datadump" / "skills" / "rows.csv").write_text("x")   # 叫 skills 但不是 Skill 目录
    _skill(home / "notes" / "skills")                          # 不是隐藏文件夹
    found = detect()
    assert "skillpm" not in found and "datadump" not in found and "notes" not in found
    assert found.get("Codex") != str(home / ".codex" / "vendor_imports" / "skills")


def test_auto_discover_does_not_duplicate_catalog(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    _skill(home / ".claude" / "skills")
    found = detect()
    assert found["Claude Code"] == str(home / ".claude" / "skills")
    assert "claude" not in found                              # 表里有的不再以自动发现的名字重复出现
    assert list(found.values()).count(str(home / ".claude" / "skills")) == 1


def test_windsurf_points_at_skills_not_memories(tmp_path, monkeypatch):
    # 1.17 之前 Windsurf 的第一候选是 memories（记忆），它存在就会把 Skill 装进记忆目录
    home = _home(tmp_path, monkeypatch)
    (home / ".codeium" / "windsurf" / "memories").mkdir(parents=True)
    (home / ".codeium" / "windsurf" / "skills").mkdir(parents=True)
    assert detect()["Windsurf"] == str(home / ".codeium" / "windsurf" / "skills")


def test_same_directory_listed_once():
    # 多家共用的目录在表里只能出现一次，否则同一份会装两遍
    from collections import Counter
    from skillpm.hosts import project_capable, project_dir
    users = Counter(c for cands, *_ in CATALOG.values() for c in cands)
    assert [c for c, k in users.items() if k > 1] == []
    projs = [project_dir(n) for n in project_capable()]
    assert len(projs) == len(set(projs))
