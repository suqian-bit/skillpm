import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def skillpm_home(tmp_path, monkeypatch):
    """每个用例一套干净的 ~/.skillpm，绝不碰真实环境。"""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("SKILLPM_HOME", str(h))
    return h


@pytest.fixture
def fake_repo(tmp_path):
    """造一个最小可用的 Skill 仓库：两个 Skill + manifest。"""
    import hashlib
    repo = tmp_path / "repo"
    (repo / "skills").mkdir(parents=True)
    skills = {}
    for name, ver in (("demo-a", "1.0.0"), ("demo-b", "2.1.0")):
        d = repo / "skills" / name
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\nmetadata:\n  version: {ver}\n---\n正文\n",
                                    encoding="utf-8")
        (d / "CHANGELOG.md").write_text(f"# {name}\n\n## {ver} — 2026-01-01\n\n- 初版\n",
                                        encoding="utf-8")
        (d / "references" / "note.md").write_text("参考\n", encoding="utf-8")
        # 真 Skill 常带 Codex 展示元数据（agents/openai.yaml）。夹具里没有的话，
        # install 把它弄丢了也没有测试会响——所以夹具要长得像真 Skill。
        (d / "agents").mkdir()
        (d / "agents" / "openai.yaml").write_text(
            "interface:\n"
            f'  display_name: "{name} · 演示用"\n'
            f'  short_description: "夹具用的假 Skill"\n',
            encoding="utf-8")
        files = {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(d.rglob("*")) if p.is_file()}
        skills[name] = {"version": ver, "summary": "", "files": files}
    (repo / "manifest.json").write_text(json.dumps({"generated_at": "now", "skills": skills},
                                                   ensure_ascii=False), encoding="utf-8")
    return repo


@pytest.fixture
def host_dir(tmp_path):
    d = tmp_path / "host" / "skills"
    d.mkdir(parents=True)
    return d
