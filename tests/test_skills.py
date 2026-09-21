"""装、算改动、报冲突——这几件事错了会真丢东西，重点测。"""
import json

from skillpm.skills import ConflictLog, backup, install, local_changes, read_version


def meta(repo, name):
    return json.loads((repo / "manifest.json").read_text(encoding="utf-8"))["skills"][name]


def test_install_copies_and_records_hashes(fake_repo, host_dir):
    rec = install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    assert (host_dir / "demo-a" / "SKILL.md").exists()
    assert (host_dir / "demo-a" / "references" / "note.md").exists()
    assert rec["version"] == "1.0.0" and rec["files"]
    assert local_changes(host_dir, "demo-a", rec) == {"changed": [], "missing": []}


def test_local_edit_is_detected(fake_repo, host_dir):
    rec = install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    (host_dir / "demo-a" / "SKILL.md").write_text("我改了\n", encoding="utf-8")
    (host_dir / "demo-a" / "references" / "note.md").unlink()
    diff = local_changes(host_dir, "demo-a", rec)
    assert diff["changed"] == ["SKILL.md"]
    assert diff["missing"] == ["references/note.md"]


def test_missing_dir_reports_none(fake_repo, host_dir):
    rec = install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    import shutil
    shutil.rmtree(host_dir / "demo-a")
    assert local_changes(host_dir, "demo-a", rec) is None


def test_conflict_when_locally_modified(fake_repo, host_dir, skillpm_home):
    rec = install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    (host_dir / "demo-a" / "SKILL.md").write_text("我改了\n", encoding="utf-8")
    log = ConflictLog()
    assert log.check("H", host_dir, "demo-a", rec, repo_dir=fake_repo) is True
    assert log.report() == 1              # 有冲突要返回非零


def test_conflict_when_foreign_copy_present(fake_repo, host_dir):
    (host_dir / "demo-a").mkdir()
    (host_dir / "demo-a" / "SKILL.md").write_text("metadata:\n  version: 9.9.9\n", encoding="utf-8")
    log = ConflictLog()
    assert log.check("H", host_dir, "demo-a", None, repo_dir=fake_repo) is True
    assert "不是本工具装的" in log.items[0]["why"]


def test_force_skips_conflict_check(fake_repo, host_dir):
    (host_dir / "demo-a").mkdir()
    log = ConflictLog()
    assert log.check("H", host_dir, "demo-a", None, force=True) is False
    assert log.report() == 0


def test_clean_install_is_not_a_conflict(fake_repo, host_dir):
    log = ConflictLog()
    assert log.check("H", host_dir, "demo-a", None) is False


def test_backup_keeps_local_extras(fake_repo, host_dir, skillpm_home):
    install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    (host_dir / "demo-a" / "my-note.txt").write_text("我自己加的\n", encoding="utf-8")
    b = backup(host_dir, "demo-a", "1.0.0")
    assert (b / "my-note.txt").read_text(encoding="utf-8") == "我自己加的\n"


def test_backup_twice_in_same_second(fake_repo, host_dir, skillpm_home):
    install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    a = backup(host_dir, "demo-a", "1.0.0")
    b = backup(host_dir, "demo-a", "1.0.0")
    assert a != b and a.exists() and b.exists()


def test_read_version(fake_repo):
    assert read_version(fake_repo / "skills" / "demo-b") == "2.1.0"
    assert read_version(fake_repo / "skills") is None


def test_force_backs_up_foreign_copy(fake_repo, host_dir, skillpm_home):
    """--force 覆盖别人的东西之前必须备份——「覆盖掉找不回来」不该是管理工具的行为。"""
    d = host_dir / "demo-a"
    d.mkdir()
    (d / "SKILL.md").write_text("metadata:\n  version: 9.9.9\n", encoding="utf-8")
    (d / "别人的笔记.txt").write_text("很重要\n", encoding="utf-8")
    install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir, backup_existing=True)
    from skillpm.config import backup_dir
    saved = list((backup_dir() / "demo-a").glob("9.9.9-*"))
    assert saved, "没备份就覆盖了"
    assert (saved[0] / "别人的笔记.txt").read_text(encoding="utf-8") == "很重要\n"


def test_conflict_advice_matches_kind(fake_repo, host_dir, skillpm_home, capsys):
    """『不是本工具装的』不能建议去 uninstall——uninstall 根本卸不掉它。"""
    (host_dir / "demo-a").mkdir()
    log = ConflictLog()
    log.check("H", host_dir, "demo-a", None, repo_dir=fake_repo)
    capsys.readouterr()
    log.report()
    out = capsys.readouterr().out
    assert "--force" in out, "对外来副本要给 --force 这条路"
    assert "uninstall <Skill名>" not in out, "别给一条根本走不通的解法"


def test_conflict_advice_for_our_own_modified(fake_repo, host_dir, skillpm_home, capsys):
    rec = install(fake_repo, "demo-a", meta(fake_repo, "demo-a"), host_dir)
    (host_dir / "demo-a" / "SKILL.md").write_text("改了\n", encoding="utf-8")
    log = ConflictLog()
    log.check("H", host_dir, "demo-a", rec, repo_dir=fake_repo)
    capsys.readouterr()
    log.report()
    out = capsys.readouterr().out
    assert "uninstall" in out, "本工具装的、改过的，uninstall 是有效解法"


def test_record_hashes_what_was_written_not_the_manifest(tmp_path):
    """Windows 的 CRLF 转换会让检出内容和 manifest 哈希对不上。

    安装记录的用途是「用户后来改没改过」，就必须以实际落盘的内容为准；
    照抄 manifest 的哈希，装完第一眼就会被误判成「本地已修改」。
    """
    import hashlib
    from skillpm.skills import install, local_changes
    repo, dest = tmp_path / "repo", tmp_path / "host"
    sk = repo / "skills" / "demo"
    sk.mkdir(parents=True)
    lf = "---\nname: demo\nmetadata:\n  version: 1.0.0\n---\n正文\n".encode("utf-8")
    (sk / "SKILL.md").write_bytes(lf.replace(b"\n", b"\r\n"))     # 检出成了 CRLF
    meta = {"version": "1.0.0", "files": {"SKILL.md": hashlib.sha256(lf).hexdigest()}}

    rec = install(repo, "demo", meta, dest)
    assert local_changes(dest, "demo", rec) == {"changed": [], "missing": []}

    (dest / "demo" / "SKILL.md").write_bytes(b"user edit\r\n")
    assert local_changes(dest, "demo", rec)["changed"] == ["SKILL.md"]


def test_git_clone_disables_eol_conversion():
    """克隆和更新都要关掉 autocrlf，否则跨平台哈希对不上，锁文件也就失去意义。"""
    from skillpm.repos import NO_EOL_CONVERT
    assert NO_EOL_CONVERT == ["-c", "core.autocrlf=false", "-c", "core.eol=lf"]


def test_old_records_with_lf_hashes_are_not_false_positives(tmp_path):
    """1.14.1 之前写的记录存的是 manifest 的 LF 哈希，磁盘上却是 CRLF。

    升级后不能满屏「本地改过」——那不是用户改的，是 Git for Windows 的行尾转换。
    """
    import hashlib
    from skillpm.skills import local_changes
    host = tmp_path / "host"
    d = host / "demo"
    d.mkdir(parents=True)
    lf = "---\nname: demo\n---\n正文\n第二行\n".encode("utf-8")
    (d / "SKILL.md").write_bytes(lf.replace(b"\n", b"\r\n"))
    old_record = {"files": {"SKILL.md": hashlib.sha256(lf).hexdigest()}}

    assert local_changes(host, "demo", old_record)["changed"] == []

    # 但真改了一行就得认出来，不能被这条豁免吞掉
    (d / "SKILL.md").write_bytes(lf.replace(b"\n", b"\r\n") + "我加的\r\n".encode("utf-8"))
    assert local_changes(host, "demo", old_record)["changed"] == ["SKILL.md"]


def test_line_ending_exemption_needs_actual_crlf(tmp_path):
    """纯 LF 的文件内容对不上，就是真改过，不许走这条豁免。"""
    import hashlib
    from skillpm.skills import same_but_for_line_endings
    f = tmp_path / "a.md"
    f.write_bytes(b"hello\nworld\n")
    assert not same_but_for_line_endings(f, hashlib.sha256(b"other\n").hexdigest())
