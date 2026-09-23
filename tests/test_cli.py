"""命令行：参数、退出码、端到端装一遍。"""
from pathlib import Path

import pytest

from skillpm import __version__
from skillpm.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_single_dash_help_is_accepted(capsys):
    with pytest.raises(SystemExit) as e:
        main(["-help"])
    assert e.value.code == 0
    assert "install" in capsys.readouterr().out


def test_no_args_prints_help(capsys):
    assert main([]) == 0
    assert "skillpm" in capsys.readouterr().out


def test_repo_add_and_list(skillpm_home, capsys):
    assert main(["repo", "add", "mine", "--ssh", "git@h:g/p.git", "--no-check"]) == 0
    assert main(["repo", "list"]) == 0
    out = capsys.readouterr().out
    assert "mine" in out and "git@h:g/p.git" in out


def test_repo_add_needs_name(capsys):
    with pytest.raises(SystemExit):
        main(["repo", "add"])


def test_token_never_printed(skillpm_home, capsys):
    assert main(["repo", "add", "mine", "--http", "http://h", "--path", "g/p",
                 "--token", "super-secret-token", "--no-check"]) == 0
    main(["repo", "list"])
    out = capsys.readouterr().out
    assert "super-secret-token" not in out


def test_install_defaults_to_user_level(skillpm_home, fake_repo, host_dir, capsys):
    # 本地目录当 git 仓库用：clone 一个真 repo 太重，这里直接写缓存
    from skillpm.config import cache_dir, load_config, save_config
    import shutil
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "http": "", "path": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))

    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        "local": (cache_dir("local"), __import__("json").loads(
            (cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))}

    code = main(["install", "--all"])        # 不给 -g，默认就该是用户级
    assert code == 0
    assert (host_dir / "demo-a" / "SKILL.md").exists()
    assert (host_dir / "demo-b" / "SKILL.md").exists()

    # 再装一次：本地没动过，不该报冲突
    assert main(["install", "--all"]) == 0
    # 本地改一笔，应该报冲突并返回 1
    (host_dir / "demo-a" / "SKILL.md").write_text("改了\n", encoding="utf-8")
    assert main(["install", "-g", "--all"]) == 1   # -g 显式写也一样
    assert "冲突" in capsys.readouterr().out


def test_check_says_nothing_to_do(skillpm_home, fake_repo, host_dir, capsys):
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))
    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        "local": (cache_dir("local"), _json.loads(
            (cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))}
    main(["install", "--all"])
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "都是最新的" in capsys.readouterr().out


def test_check_reports_local_edits(skillpm_home, fake_repo, host_dir, capsys):
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))
    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        "local": (cache_dir("local"), _json.loads(
            (cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))}
    main(["install", "--all"])
    (host_dir / "demo-a" / "SKILL.md").write_text("我改了\n", encoding="utf-8")
    capsys.readouterr()
    main(["check"])
    out = capsys.readouterr().out
    assert "本地改过" in out and "demo-a" in out


def test_install_to_custom_dir(skillpm_home, fake_repo, tmp_path, capsys):
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(tmp_path / "unused")}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))
    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        "local": (cache_dir("local"), _json.loads(
            (cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))}
    target = tmp_path / "my-skills"
    assert main(["install", "-d", str(target), "--only", "demo-a"]) == 0
    assert (target / "demo-a" / "SKILL.md").exists()
    assert not (tmp_path / "unused").exists(), "指定了 -d 就不该再往宿主目录装"


def _local_repo_setup(skillpm_home, fake_repo, host_dir):
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))
    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        "local": (cache_dir("local"), _json.loads(
            (cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))}


def test_update_warns_about_local_edits_even_when_current(skillpm_home, fake_repo, host_dir, capsys):
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    main(["install", "--all"])
    (host_dir / "demo-a" / "SKILL.md").write_text("我改了\n", encoding="utf-8")
    capsys.readouterr()
    main(["update", "--yes"])
    out = capsys.readouterr().out
    assert "都是最新的" in out
    assert "本地改过" in out and "demo-a" in out, "没新版本≠没问题，改过了要说"


def test_uninstall_refreshes_index(skillpm_home, fake_repo, host_dir):
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    main(["install", "--all"])
    idx = host_dir / "AGENTS.md"
    assert "demo-a" in idx.read_text(encoding="utf-8")
    main(["uninstall", "demo-a", "--yes"])      # 直接写名字，不用 --only
    assert "demo-a" not in idx.read_text(encoding="utf-8"), "删了还留在索引里会误导人"
    assert "demo-b" in idx.read_text(encoding="utf-8")


def test_uninstall_all_clears_index(skillpm_home, fake_repo, host_dir):
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    main(["install", "--all"])
    main(["uninstall", "--all", "--yes"])
    idx = host_dir / "AGENTS.md"
    assert not idx.exists() or "demo-" not in idx.read_text(encoding="utf-8")


def test_update_repo_filter(skillpm_home, fake_repo, host_dir, capsys):
    """多仓库时 --repo 只动指定那个。"""
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    cfg = load_config()
    cfg["repos"] = {"a": {"ssh": "", "branch": "main", "mode": "git"},
                    "b": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("a"))
    man = _json.loads((cache_dir("a") / "manifest.json").read_text(encoding="utf-8"))
    import skillpm.cli as cli
    # a 提供 demo-a，b 提供 demo-b
    cli.fetch_all = lambda cfg, quiet=False: {
        "a": (cache_dir("a"), {"skills": {"demo-a": man["skills"]["demo-a"]}}),
        "b": (cache_dir("a"), {"skills": {"demo-b": man["skills"]["demo-b"]}})}
    main(["install", "--all"])

    # 把 a 的 demo-a 提到新版本
    bumped = _json.loads(_json.dumps(man))
    bumped["skills"]["demo-a"]["version"] = "9.9.9"
    cli.fetch_all = lambda cfg, quiet=False: {
        "a": (cache_dir("a"), {"skills": {"demo-a": bumped["skills"]["demo-a"]}}),
        "b": (cache_dir("a"), {"skills": {"demo-b": man["skills"]["demo-b"]}})}
    capsys.readouterr()
    main(["update", "--repo", "b", "--yes"])
    out = capsys.readouterr().out
    assert "只看了 b" in out, "指定了仓库就该说明范围"
    assert "demo-a" not in out, "--repo b 不该动 a 仓库的东西"


def test_uninstall_without_names_does_not_wipe_everything(skillpm_home, fake_repo, host_dir, capsys):
    """不写名字又不给 --all 时必须先问，不能默认删光。"""
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    main(["install", "--all"])
    capsys.readouterr()
    import builtins
    asked = {"n": 0}

    def fake_input(prompt=""):
        asked["n"] += 1
        return "0"          # 「一个都不要」

    old = builtins.input
    builtins.input = fake_input
    try:
        assert main(["uninstall"]) == 0
    finally:
        builtins.input = old
    assert asked["n"] >= 1, "没点名就该问，不能闷头删"
    assert (host_dir / "demo-a" / "SKILL.md").exists(), "选了「一个都不要」就不该动任何东西"


def test_uninstall_host_is_case_insensitive(skillpm_home, fake_repo, host_dir):
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    main(["install", "--all"])
    assert main(["uninstall", "--host", "h", "demo-a", "--yes"]) == 0
    assert not (host_dir / "demo-a").exists()


def test_uninstall_says_when_skill_was_never_installed_by_us(skillpm_home, fake_repo, host_dir, capsys):
    """最常见的困惑：那个 Skill 装的时候冲突跳过了，根本没进记录。"""
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    main(["install", "--only", "demo-a"])
    capsys.readouterr()
    assert main(["uninstall", "demo-b", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "不是本工具装的" in out
    assert "demo-a" in out, "要告诉用户本工具到底装了哪些"


def test_hosts_flag_selects_subset(skillpm_home, fake_repo, tmp_path):
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    h1, h2 = tmp_path / "h1", tmp_path / "h2"
    h1.mkdir(); h2.mkdir()
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"A": str(h1), "B": str(h2)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir("local"))
    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        "local": (cache_dir("local"), _json.loads(
            (cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))}
    assert main(["install", "--hosts", "b", "--only", "demo-a"]) == 0
    assert (h2 / "demo-a").exists()
    assert not (h1 / "demo-a").exists(), "--hosts b 不该装到 A"


def test_hosts_flag_rejects_unknown(skillpm_home, fake_repo, host_dir, capsys):
    _local_repo_setup(skillpm_home, fake_repo, host_dir)
    assert main(["install", "--hosts", "nope", "--only", "demo-a"]) == 1
    assert "不认识这些宿主" in capsys.readouterr().out


def _wire_local_repo(tmp_path, fake_repo, host_dir, repo_name="local"):
    """公共脚手架：把 fake_repo 当成一个已配好的仓库，缓存就位、不走网络。"""
    from skillpm.config import cache_dir, load_config, save_config
    import shutil, json as _json
    cfg = load_config()
    cfg["repos"] = {repo_name: {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)
    shutil.copytree(fake_repo, cache_dir(repo_name))
    import skillpm.cli as cli
    cli.fetch_all = lambda cfg, quiet=False: {
        repo_name: (cache_dir(repo_name), _json.loads(
            (cache_dir(repo_name) / "manifest.json").read_text(encoding="utf-8")))}


def test_install_accepts_repo_scoped_name(skillpm_home, fake_repo, host_dir, tmp_path):
    """`仓库名:Skill名` 要真能装上——文档里写了，就不能只是解析一下。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    assert main(["install", "local:demo-a"]) == 0
    assert (host_dir / "demo-a" / "SKILL.md").exists()
    assert not (host_dir / "demo-b").exists(), "点名了就只装点名的那个"


def test_install_accepts_team_url(skillpm_home, fake_repo, host_dir, tmp_path):
    """team://仓库名/Skill名 和 仓库名:Skill名 是同一条路。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    assert main(["install", "team://local/demo-b"]) == 0
    assert (host_dir / "demo-b" / "SKILL.md").exists()


def test_install_rejects_unknown_repo_prefix(skillpm_home, fake_repo, host_dir, tmp_path, capsys):
    """仓库名写错要当场说清楚，而不是报「这些仓库里都没有」让人去猜。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    assert main(["install", "写错的库:demo-a"]) == 1
    out = capsys.readouterr().out
    assert "写错的库" in out and "skillpm repo list" in out


def test_install_reports_wrong_repo_for_existing_skill(skillpm_home, fake_repo, host_dir,
                                                       tmp_path, capsys):
    """Skill 存在但不在点名的那个仓库里，报错要带上仓库前缀。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    from skillpm.config import load_config, save_config
    cfg = load_config()
    cfg["repos"]["另一个库"] = {"ssh": "", "branch": "main", "mode": "git"}
    save_config(cfg)
    assert main(["install", "另一个库:demo-a"]) == 1
    assert "另一个库:demo-a" in capsys.readouterr().out


def test_install_still_rejects_external_sources(skillpm_home, fake_repo, host_dir,
                                                tmp_path, capsys):
    """GitHub / git 地址确实还没接，要明说没接，不能装成功的样子。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    assert main(["install", "anthropics/skills/pdf"]) == 1
    assert "暂时还不支持" in capsys.readouterr().out


def test_install_does_not_wipe_other_hosts(skillpm_home, fake_repo, tmp_path, capsys):
    """装到 B 不该把上次配的 A 从宿主表里抹掉——表是累积的注册表。"""
    from skillpm.config import load_config, save_config
    a_dir, b_dir = tmp_path / "A", tmp_path / "B"
    a_dir.mkdir(); b_dir.mkdir()
    _wire_local_repo(tmp_path, fake_repo, a_dir)
    cfg = load_config()
    cfg["hosts"] = {"A": str(a_dir), "B": str(b_dir)}
    save_config(cfg)

    # Skill 名写在 --hosts 前面：--hosts 会一路吃到下一个选项
    assert main(["install", "demo-a", "--hosts", "B"]) == 0
    cfg = load_config()
    assert set(cfg["hosts"]) == {"A", "B"}, "只装 B 不等于把 A 从配置里删掉"
    assert cfg["last_hosts"] == ["B"], "本次装到哪单独记，只用来决定下次默认勾选"


def test_known_hosts_recovers_from_state(skillpm_home, fake_repo, tmp_path):
    """老配置被覆盖过：装过的宿主要能从安装记录里找回来。"""
    from skillpm.cli import known_hosts
    from skillpm.config import load_config, save_config, save_state
    _wire_local_repo(tmp_path, fake_repo, tmp_path / "A")
    cfg = load_config()
    cfg["hosts"] = {"B": str(tmp_path / "B")}
    save_config(cfg)
    save_state({"hosts": {"A": {"path": str(tmp_path / "A"), "scope": "global",
                                "skills": {"demo-a": {"version": "1.0.0"}}}}})
    assert set(known_hosts(load_config())) == {"A", "B"}


def test_host_list_shows_counts_and_recovered(skillpm_home, fake_repo, host_dir,
                                              tmp_path, capsys):
    """host list 要说清楚每个宿主装了几个，并标出配置里丢了的那个。"""
    from skillpm.config import load_config, save_config
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    main(["install", "--all"])
    cfg = load_config()
    cfg["hosts"] = {}                       # 模拟被老版本覆盖掉
    save_config(cfg)
    capsys.readouterr()
    main(["host", "list"])
    out = capsys.readouterr().out
    assert "装了 2 个" in out
    assert "配置里丢了" in out
    assert "skillpm status" in out, "要指一条能看明细的路"


def test_repo_list_shows_what_is_installed(skillpm_home, fake_repo, host_dir,
                                           tmp_path, capsys):
    """repo list 光有地址没用，得说清这个库里有多少、本机装了几个、装到哪。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    main(["install", "--all"])
    capsys.readouterr()
    main(["repo", "list"])
    out = capsys.readouterr().out
    assert "里面有 2 个 Skill" in out
    assert "本机装了 2 个" in out
    assert "H" in out


def test_hosts_flag_swallowing_skill_name_explains_itself(skillpm_home, fake_repo,
                                                          host_dir, tmp_path, capsys):
    """`--hosts B demo-a` 会把 demo-a 当宿主；报错要指出词序问题，别只说不认识。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    assert main(["install", "--hosts", "H", "demo-a"]) == 1
    out = capsys.readouterr().out
    assert "不认识这些宿主" in out and "demo-a" in out
    assert "写在它前面" in out


def test_git_url_prefers_ssh_then_http():
    """公开仓库只给 http 也要能 git clone——新人没配密钥是常态，不该卡在这。"""
    from skillpm.repos import git_url
    assert git_url({"ssh": "git@h:g/p.git", "http": "http://h"}) == "git@h:g/p.git"
    assert git_url({"http": "http://h:82/g/p.git"}) == "http://h:82/g/p.git"
    assert git_url({"http": "http://h:82", "path": "g/p"}) == "http://h:82/g/p.git"
    assert git_url({"http": "http://h:82"}) is None, "只有网页地址、没有项目路径，拼不出仓库地址"
    assert git_url({}) is None


def test_repo_add_http_only_still_uses_git(skillpm_home, monkeypatch, capsys):
    """只给 http 的 .git 地址、不给 ssh 不给令牌，也该走 git 模式。"""
    import skillpm.cli as cli
    monkeypatch.setattr(cli, "has_git", lambda: True)
    assert main(["repo", "add", "公开库", "--http",
                 "http://h:82/g/p.git", "--yes", "--no-check"]) == 0
    from skillpm.config import load_config
    assert load_config()["repos"]["公开库"]["mode"] == "git"


def test_home_dir_is_not_a_project(monkeypatch, tmp_path):
    """家目录不该被当成项目：~/.claude/skills 本来就是用户级目录。"""
    from skillpm.cli import is_project_root
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert not is_project_root(home)
    proj = home / "work" / "repo"; proj.mkdir(parents=True)
    assert is_project_root(proj)


def test_install_p_in_home_refuses(skillpm_home, fake_repo, host_dir, tmp_path,
                                   monkeypatch, capsys):
    """在家目录里 install -p 要拦下来：家目录下的 .claude/skills 本来就是用户级目录。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    home = tmp_path / "home"          # skillpm_home fixture 已经建过了
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(home)
    assert main(["install", "-p", "--all"]) == 1
    out = capsys.readouterr().out
    assert "家目录" in out


def test_conflict_advice_names_the_skills(skillpm_home, fake_repo, host_dir,
                                          tmp_path, capsys):
    """冲突提示要给能直接粘的命令，别写 <Skill名> 让人自己回头对着列表填。"""
    _wire_local_repo(tmp_path, fake_repo, host_dir)
    foreign = host_dir / "demo-a"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text(
        "---\nname: demo-a\nmetadata:\n  version: 0.9.0\n---\n别人放的\n", encoding="utf-8")
    assert main(["install", "--all"]) == 1
    out = capsys.readouterr().out
    assert "--force --only demo-a" in out, "要点名到具体 Skill"
    assert "只动这一个" in out, "得说清楚不是全覆盖"
    assert "<Skill名>" not in out
    assert (host_dir / "demo-b" / "SKILL.md").exists(), "没冲突的照装不误"


def test_non_utf8_stdout_does_not_crash(monkeypatch, skillpm_home):
    """Windows 英文系统上输出被重定向时编码是 cp1252，以前一打中文就 UnicodeEncodeError。"""
    import io, sys
    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", fake)
    main(["host", "list"])
    sys.stdout.flush()
    assert "已配置".encode("utf-8") in raw.getvalue() or "本机探测".encode("utf-8") in raw.getvalue()
