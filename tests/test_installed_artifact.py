"""验「装完之后目标目录里是什么」，而不是「install 函数返回了成功」。

踩过的坑：几个 Skill 漏了 `agents/openai.yaml`，Codex 列表里显示成另一套名字，
看着像两套 Skill。当时的用例全绿——因为它们只验「装没装上」「哈希对不对」，
**没有一个去看装完的那份东西长什么样、能不能被宿主正确读出来**。

这一组补的就是这个缺口：产物完整性、元数据可解析、约定是否遵守。
"""
from pathlib import Path

import pytest

from skillpm.skills import install, local_changes

yaml = pytest.importorskip("yaml", reason="需要 pyyaml 才能验 Codex 元数据")


def _install_one(fake_repo, tmp_path, name="demo-a"):
    dest = tmp_path / "host"
    meta = {"version": "1.0.0", "files": {}}
    import json
    man = json.loads((fake_repo / "manifest.json").read_text(encoding="utf-8"))
    meta = man["skills"][name]
    rec = install(fake_repo, name, meta, dest)
    return dest / name, rec


def test_installed_copy_has_every_source_file(fake_repo, tmp_path):
    """源目录里有的文件，装完一个都不能少——包括 agents/openai.yaml。

    以前只验「SKILL.md 在不在」，漏掉整个目录也发现不了。
    """
    dst, _ = _install_one(fake_repo, tmp_path)
    src = fake_repo / "skills" / "demo-a"
    skip = {"__pycache__", ".DS_Store"}
    want = {f.relative_to(src).as_posix() for f in src.rglob("*")
            if f.is_file() and not (skip & set(f.parts)) and f.name not in skip}
    got = {f.relative_to(dst).as_posix() for f in dst.rglob("*") if f.is_file()}
    assert want <= got, f"装完少了这些文件：{sorted(want - got)}"


def test_installed_codex_metadata_parses(fake_repo, tmp_path):
    """装完的 agents/openai.yaml 必须还能解析出 display_name。

    文件在、但内容是坏的（比如 YAML 语法错），宿主一样读不出来——
    「文件存在」不等于「宿主能用」。
    """
    dst, _ = _install_one(fake_repo, tmp_path)
    y = dst / "agents" / "openai.yaml"
    assert y.exists(), "装完没有 agents/openai.yaml，Codex 会回退成 frontmatter name"
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    disp = ((data or {}).get("interface") or {}).get("display_name")
    assert disp, "display_name 解析不出来"
    assert disp.startswith("demo-a"), f"display_name 不以 Skill 名开头：{disp!r}"


def test_installed_skill_md_name_matches_dir(fake_repo, tmp_path):
    """frontmatter 里的 name 要和落地的目录名一致，否则宿主对不上号。"""
    import re
    dst, _ = _install_one(fake_repo, tmp_path)
    text = (dst / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^name:\s*(\S+)", text, re.M)
    assert m and m.group(1) == dst.name, f"name={m and m.group(1)!r} 目录={dst.name!r}"


def test_record_covers_every_installed_file(fake_repo, tmp_path):
    """安装记录要盖住落地的每一个文件。

    漏记的文件＝改了也查不出来，`status` 会把被人动过的 Skill 报成「最新」。
    """
    dst, rec = _install_one(fake_repo, tmp_path)
    on_disk = {f.relative_to(dst).as_posix() for f in dst.rglob("*") if f.is_file()}
    recorded = set(rec.get("files") or {})
    assert not (on_disk - recorded), f"这些文件没进安装记录：{sorted(on_disk - recorded)}"


def test_tampering_with_metadata_is_detected(fake_repo, tmp_path):
    """改了 agents/openai.yaml 也要算「本地改过」，不能只盯 SKILL.md。"""
    dst, rec = _install_one(fake_repo, tmp_path)
    y = dst / "agents" / "openai.yaml"
    y.write_text(y.read_text(encoding="utf-8") + "\n# 有人动过\n", encoding="utf-8")
    diff = local_changes(dst.parent, dst.name, rec)
    assert "agents/openai.yaml" in diff["changed"], "改了展示元数据却没被认出来"


def test_reinstall_over_existing_leaves_no_stale_file(fake_repo, tmp_path):
    """重装要把旧文件清干净，不能留下上一版才有的残骸。

    残骸会让宿主读到早该消失的配置，而哈希比对只看记录里有的文件，看不见多出来的。
    """
    dst, _ = _install_one(fake_repo, tmp_path)
    (dst / "references" / "只有旧版才有.md").write_text("旧的\n", encoding="utf-8")
    _install_one(fake_repo, tmp_path)
    assert not (dst / "references" / "只有旧版才有.md").exists(), "重装后旧文件还在"
