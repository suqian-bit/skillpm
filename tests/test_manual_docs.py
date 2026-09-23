"""随工具发的图文手册：skillpm docs 能打开；手册过期发版检查会拦；self-update 手册变了会提醒。"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skillpm import manual
from skillpm.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_manual_is_up_to_date():
    # 和 tools/check_release.py 同一个判断：提交的手册必须按当前 md 和版本号生成
    from skillpm import __version__
    ver, src = manual.html_meta(manual.html_path())
    assert ver == __version__, "docs/使用手册.html 版本号不对，重新生成：uvx --with markdown python tools/manual_html/build.py"
    assert src == manual.source_hash(), "docs/ 下的 md 或 CHANGELOG 改过了，手册没重新生成"


def test_release_check_catches_stale_manual(tmp_path):
    work = tmp_path / "repo"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "dist"))
    run = lambda: subprocess.run([sys.executable, "tools/check_release.py"], cwd=work, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
    assert run().returncode == 0
    md = work / "docs" / "快速上手.md"
    md.write_text(md.read_text(encoding="utf-8") + "\n改了一句\n", encoding="utf-8")
    r = run()
    assert r.returncode != 0 and "过期" in (r.stderr + r.stdout)


def test_docs_opens_browser(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(manual.webbrowser, "open", lambda url: seen.append(url) or True)
    assert main(["docs"]) == 0
    assert seen and seen[0].startswith("file://") and seen[0].endswith(".html")
    assert "已在浏览器里打开" in capsys.readouterr().out


def test_docs_without_browser_prints_path(monkeypatch, capsys):
    monkeypatch.setattr(manual.webbrowser, "open", lambda url: False)
    assert main(["docs"]) == 0
    out = capsys.readouterr().out
    assert "没能自动打开" in out and "使用手册.html" in out


def test_docs_path_flag(capsys):
    assert main(["docs", "--path"]) == 0
    from pathlib import Path
    assert Path(capsys.readouterr().out.strip()).as_posix().endswith("docs/使用手册.html")


def test_self_update_notices_manual_change(tmp_path):
    if not shutil.which("git"):
        pytest.skip("没有 git")
    from skillpm.cli import _manual_changed
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, env=env, text=True).stdout
    (tmp_path / "docs").mkdir()
    (tmp_path / manual.HTML).write_text("v1", encoding="utf-8")
    (tmp_path / "x.txt").write_text("1", encoding="utf-8")
    g("init", "-q", "-b", "main"); g("add", "-A"); g("commit", "-q", "-m", "1")
    first = g("rev-parse", "HEAD").strip()
    (tmp_path / "x.txt").write_text("2", encoding="utf-8"); g("commit", "-q", "-am", "别的文件")
    assert not _manual_changed(tmp_path, first), "手册没变不该提醒"
    (tmp_path / manual.HTML).write_text("v2", encoding="utf-8"); g("commit", "-q", "-am", "手册")
    assert _manual_changed(tmp_path, first)


def test_help_has_clickable_manual_link(capsys):
    import pytest
    with pytest.raises(SystemExit):
        main(["-h"])
    out = capsys.readouterr().out
    assert "使用手册.html" in out and ("open " in out or "explorer " in out or "xdg-open " in out), \
        "帮助里要有一条复制就能打开手册的命令（macOS 自带终端点不开 file:// 链接）"


def test_help_has_no_escape_codes(capsys, monkeypatch):
    """Windows 老式 cmd 不认识 OSC 8 超链接转义，会原样打成乱码——终端里也不能带。"""
    import sys, pytest
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    with pytest.raises(SystemExit):
        main(["-h"])
    assert "\033]8" not in capsys.readouterr().out     # 颜色（SGR）可以有，老式 cmd 下 console 本来就不上色


def test_open_command_per_platform(monkeypatch):
    import sys
    from skillpm.manual import open_command
    monkeypatch.setattr(sys, "platform", "win32")
    assert open_command().startswith('explorer "')      # start 在 PowerShell 里会报错
    monkeypatch.setattr(sys, "platform", "darwin")
    assert open_command().startswith("open ")
