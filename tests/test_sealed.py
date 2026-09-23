"""仓库里的某些 Skill 要口令才能装（通用）：哪些要、用哪个口令组、哪些互斥，都写在仓库根目录的 skillpm.repo.json。

起因：同一个工具分了只读 / 读写 / 管理三个版本，可 install 一回车三个全装上，分级起不到管控作用。
做成通用的版本管控：一个仓库里任意 Skill 都可以要口令，同一口令组共用一个口令；
「同一宿主只装一个」是另一件事（互斥组），可以单独用，也可以和口令一起用。
这里故意不用 read/write/admin 这类名字，证明不依赖命名。
"""
import json
import shutil

import pytest

import skillpm.cli as cli
from skillpm import sealed
from skillpm.cli import main
from skillpm.config import cache_dir, load_config, load_state, save_config, save_state

CONFIG = {"locked": {"kit-pro": {"lock": ["pro", "max"], "hint": "找组长要"}, "kit-max": {"lock": "max"},
                     "secret-tool": {"lock": "leads", "hint": "找组长要"}},
          "exclusive": {"kit": ["kit-basic", "kit-pro", "kit-max"]}}
PW = {"pro": "pro-pw", "max": "max-pw", "leads": "leads-pw"}


def _skill(root, name, ver):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name} 说明\nmetadata:\n  version: {ver}\n---\n正文 {name} {ver}\n",
                                encoding="utf-8")
    (d / "CHANGELOG.md").write_text(f"# {name}\n\n## {ver} — 2026-01-01\n\n- {name} 的 {ver}\n", encoding="utf-8")
    (d / "scripts").mkdir()
    (d / "scripts" / "tool.py").write_text(f"# {name} {ver}\n", encoding="utf-8")
    return d


def typing(monkeypatch, *answers, tty=True):
    """模拟在终端里手敲口令；多问一次就报错（说明不该问的地方问了）。"""
    left = list(answers)
    monkeypatch.setattr(sealed, "interactive", lambda: tty)

    def ask(prompt):
        if not left:
            raise AssertionError(f"不该再问口令：{prompt}")
        return left.pop(0)
    monkeypatch.setattr(sealed, "ask", ask)
    return left


def _publish(monkeypatch, src, repo, *extra, pw=PW):
    for lock, p in pw.items():
        monkeypatch.setenv(f"SKILLPM_LOCK_{lock.upper()}", p)
    rc = main(["publish", str(src), "--repo", str(repo), *extra])
    for lock in pw:
        monkeypatch.delenv(f"SKILLPM_LOCK_{lock.upper()}", raising=False)
    return rc


@pytest.fixture
def env(skillpm_home, tmp_path, host_dir, monkeypatch):
    src, repo = tmp_path / "src", tmp_path / "repo"
    for n in ("demo-a", "kit-basic", "kit-pro", "kit-max", "secret-tool"):
        _skill(src, n, "1.0.0")
    repo.mkdir()
    (repo / "skillpm.repo.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
    assert _publish(monkeypatch, src, repo) == 0
    cfg = load_config()
    cfg["repos"] = {"local": {"ssh": "", "branch": "main", "mode": "git"}}
    cfg["hosts"] = {"H": str(host_dir)}
    save_config(cfg)

    def sync():
        if cache_dir("local").exists():
            shutil.rmtree(cache_dir("local"))
        shutil.copytree(repo, cache_dir("local"))
        monkeypatch.setattr(sealed, "_opened", {})
    sync()
    monkeypatch.setattr(cli, "fetch_all", lambda cfg, quiet=False: {
        "local": (cache_dir("local"), json.loads((cache_dir("local") / "manifest.json").read_text(encoding="utf-8")))})
    return {"src": src, "repo": repo, "host": host_dir, "sync": sync}


def dirs(host):
    return {p.name for p in host.iterdir() if p.is_dir()}


# ── 加密包本身 ────────────────────────────────────────────────

def test_pack_roundtrip_wrong_password_and_tamper(tmp_path):
    d = _skill(tmp_path, "secret-tool", "1.0.0")
    pkg = tmp_path / "p.pkg"
    pkg.write_bytes(sealed.pack(d, {"leads": "leads-pw"}, {"name": "secret-tool", "version": "1.0.0", "lock": "leads"}))
    assert b"secret-tool 1.0.0" not in pkg.read_bytes(), "内容必须是密文"
    assert sealed.header(pkg)["version"] == "1.0.0", "不解密也要能读版本"
    assert sealed.check_password(pkg, "leads-pw") and not sealed.check_password(pkg, "x")
    with pytest.raises(sealed.WrongPassword):
        sealed.unpack(pkg, "x", tmp_path / "o1")
    out = sealed.unpack(pkg, "leads-pw", tmp_path / "o2")
    assert "正文 secret-tool" in (out / "SKILL.md").read_text(encoding="utf-8")
    raw = bytearray(pkg.read_bytes()); raw[-3] ^= 1; pkg.write_bytes(bytes(raw))
    with pytest.raises(sealed.WrongPassword):
        sealed.unpack(pkg, "leads-pw", tmp_path / "o3")


def test_envelope_leaves_room_for_several_passwords(tmp_path):
    """格式预留：同一个包可以有多份口令（以后「每人一个口令」就用这个），任意一份都能打开。"""
    d = _skill(tmp_path, "secret-tool", "1.0.0")
    pkg = tmp_path / "p.pkg"
    pkg.write_bytes(sealed.pack(d, {"张三": "a-pw", "李四": "b-pw"}, {"name": "secret-tool", "version": "1.0.0", "lock": "leads"}))
    assert [k["label"] for k in sealed.header(pkg)["keys"]] == ["张三", "李四"]
    sealed.unpack(pkg, "a-pw", tmp_path / "o1")
    sealed.unpack(pkg, "b-pw", tmp_path / "o2")


# ── 发版：publish ─────────────────────────────────────────────

def test_publish_seals_only_configured_and_keeps_plaintext_out(env):
    repo = env["repo"]
    assert {p.name for p in (repo / "skills").iterdir()} == {"demo-a", "kit-basic"}
    assert {p.name for p in (repo / "sealed").iterdir()} == {"kit-pro.pkg", "kit-max.pkg", "secret-tool.pkg"}
    man = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))["skills"]
    assert man["kit-pro"]["locks"] == ["pro", "max"] and man["kit-pro"]["exclusive"] == "kit" and man["kit-pro"]["rank"] == 1
    assert man["secret-tool"]["lock"] == "leads" and "exclusive" not in man["secret-tool"]
    assert man["kit-basic"]["rank"] == 0 and "sealed" not in man["kit-basic"]


def test_publish_does_not_reseal_unchanged(env, monkeypatch):
    before = (env["repo"] / "sealed" / "kit-pro.pkg").read_bytes()
    assert _publish(monkeypatch, env["src"], env["repo"]) == 0
    assert (env["repo"] / "sealed" / "kit-pro.pkg").read_bytes() == before, "没变就别重做，不然 git 里平白多一条改动"


def test_publish_refuses_wrong_password_for_existing_group(env, monkeypatch, capsys):
    (env["src"] / "kit-pro" / "SKILL.md").write_text("---\nname: kit-pro\nmetadata:\n  version: 1.1.0\n---\n", encoding="utf-8")
    assert _publish(monkeypatch, env["src"], env["repo"], "--only", "kit-pro", pw={"pro": "手滑", "max": "max-pw"}) != 0
    assert "打不开仓库里现有的 pro 组的包" in capsys.readouterr().out
    assert sealed.header(env["repo"] / "sealed" / "kit-pro.pkg")["version"] == "1.0.0", "口令输错不能发出去"


def test_publish_new_password_needs_whole_group(env, monkeypatch, capsys):
    assert _publish(monkeypatch, env["src"], env["repo"], "--only", "secret-tool", "kit-pro",
                    "--new-password", "max", pw={"max": "new"}) != 0
    assert "还缺 kit-max" in capsys.readouterr().out


# ── 装的人 ────────────────────────────────────────────────────

def test_default_install_skips_everything_that_needs_a_password(env, monkeypatch, capsys):
    typing(monkeypatch)                              # 一次都不该问
    assert main(["install", "--all", "--hosts", "H"]) == 0
    assert dirs(env["host"]) == {"demo-a", "kit-basic"}
    assert "kit 组里还有要口令的：kit-pro、kit-max" in capsys.readouterr().out


def test_standalone_locked_skill_asks_its_group_password(env, monkeypatch, capsys):
    typing(monkeypatch, "leads-pw")
    assert main(["install", "secret-tool", "--hosts", "H"]) == 0
    assert "secret-tool" in dirs(env["host"])
    main(["status", "--offline"])
    assert "口令组：leads" in capsys.readouterr().out


def test_exclusive_group_replaces_lower_one(env, monkeypatch):
    typing(monkeypatch)
    main(["install", "kit-basic", "--hosts", "H"])
    typing(monkeypatch, "猜一个", "pro-pw")
    assert main(["install", "kit-pro", "--hosts", "H"]) == 0
    assert dirs(env["host"]) == {"kit-pro"}, "同组只留一个"
    typing(monkeypatch)
    main(["install", "kit-basic", "--hosts", "H"])
    assert dirs(env["host"]) == {"kit-basic"}, "降回去不要口令"


def test_same_group_password_reused_across_skills(env, monkeypatch):
    """同一口令组的口令输对一次，同组别的 Skill 也不再问。"""
    shutil.rmtree(env["src"] / "secret-tool")
    CONFIG2 = json.loads(json.dumps(CONFIG)); CONFIG2["locked"]["demo-b"] = {"lock": "leads"}
    _skill(env["src"], "demo-b", "1.0.0"); _skill(env["src"], "secret-tool", "1.0.0")
    (env["repo"] / "skillpm.repo.json").write_text(json.dumps(CONFIG2), encoding="utf-8")
    assert _publish(monkeypatch, env["src"], env["repo"]) == 0
    env["sync"]()
    typing(monkeypatch, "leads-pw")
    main(["install", "secret-tool", "--hosts", "H"])
    typing(monkeypatch)
    main(["install", "demo-b", "--hosts", "H"])
    assert {"secret-tool", "demo-b"} <= dirs(env["host"])


def test_wrong_password_three_times_installs_nothing(env, monkeypatch, capsys):
    typing(monkeypatch)
    main(["install", "kit-basic", "--hosts", "H"])
    typing(monkeypatch, "a", "b", "c")
    main(["install", "kit-max", "--hosts", "H"])
    assert dirs(env["host"]) == {"kit-basic"}, "输错了原来的不能动"
    assert "口令不对" in capsys.readouterr().out


def test_no_terminal_refuses_and_says_run_it_yourself(env, monkeypatch, capsys):
    typing(monkeypatch, tty=False)
    main(["install", "kit-pro", "--hosts", "H"])
    out = capsys.readouterr().out
    assert "kit-pro" not in dirs(env["host"])
    assert "终端" in out and "不要发给 AI" in out, "AI 替人跑时要让人自己去终端输"


def test_update_uses_saved_password_then_skips_after_password_change(env, monkeypatch, capsys):
    typing(monkeypatch, "pro-pw")
    main(["install", "kit-pro", "--hosts", "H"])
    shutil.rmtree(env["src"] / "kit-pro"); _skill(env["src"], "kit-pro", "1.1.0")
    assert _publish(monkeypatch, env["src"], env["repo"], "--only", "kit-pro") == 0
    env["sync"]()
    typing(monkeypatch)
    capsys.readouterr()
    assert main(["update", "--yes"]) == 0
    assert "kit-pro 1.1.0" in (env["host"] / "kit-pro" / "SKILL.md").read_text(encoding="utf-8")
    assert "kit-pro 的 1.1.0" in capsys.readouterr().out, "更新日志照常显示"
    shutil.rmtree(env["src"] / "kit-pro"); _skill(env["src"], "kit-pro", "1.2.0")
    assert _publish(monkeypatch, env["src"], env["repo"], "--only", "kit-pro", "--new-password", "pro",
                    pw={"pro": "pro-2026", "max": "max-2026-不同"}) != 0, "max 组口令没换，输错了也要拦住"
    assert _publish(monkeypatch, env["src"], env["repo"], "--only", "kit-pro", "--new-password", "pro",
                    pw={"pro": "pro-2026", "max": "max-pw"}) == 0
    env["sync"]()
    typing(monkeypatch, tty=False)
    main(["update", "--yes"])
    out = capsys.readouterr().out
    assert "口令已更换" in out and "skillpm install kit-pro" in out
    assert "1.1.0" in (env["host"] / "kit-pro" / "SKILL.md").read_text(encoding="utf-8"), "旧版要留着能用"


def _all_three_installed(env):
    """模拟以前一回车全装上的状态。"""
    state = load_state()
    entry = state.setdefault("hosts", {}).setdefault("H", {"path": str(env["host"]), "skills": {}, "scope": "global"})
    for n in ("kit-basic", "kit-pro", "kit-max"):
        shutil.copytree(env["src"] / n, env["host"] / n)
        entry["skills"][n] = {"version": "1.0.0", "repo": "local", "host": "H", "scope": "global",
                              "files": {r: sealed.hashlib.sha256((env["host"] / n / r).read_bytes()).hexdigest()
                                        for r in ("SKILL.md", "CHANGELOG.md", "scripts/tool.py")}}
    save_state(state)


def test_migration_keeps_the_one_whose_password_is_typed(env, monkeypatch, capsys):
    _all_three_installed(env)
    typing(monkeypatch, "max-pw")
    main(["update", "--yes"])
    assert dirs(env["host"]) == {"kit-max"}
    assert "保留" in capsys.readouterr().out
    main(["status", "--offline"])
    assert "口令组：max" in capsys.readouterr().out, "迁移后保留的那个也要显示口令组"



def test_migration_blank_keeps_lowest(env, monkeypatch):
    _all_three_installed(env)
    typing(monkeypatch, "")
    main(["update", "--yes"])
    assert dirs(env["host"]) == {"kit-basic"}, "不输口令就只留组里最低、不要口令的那个"


def test_missing_skill_hint_never_suggests_locked(env, monkeypatch, capsys):
    typing(monkeypatch)
    main(["install", "demo-a", "--hosts", "H"])
    capsys.readouterr()
    main(["status"])
    out = capsys.readouterr().out
    assert "kit-basic" in out and "kit-pro" not in out and "secret-tool" not in out


# ── 一个 Skill 配多个口令组 ────────────────────────────────────

def test_skill_with_two_locks_opens_with_either(env, monkeypatch, capsys):
    """kit-pro 配了 pro、max 两组：拿到 max 口令的人不用再要 pro 的（像 DML write 让 admin 口令也能装）。"""
    typing(monkeypatch, "max-pw")
    assert main(["install", "kit-pro", "--hosts", "H"]) == 0
    assert dirs(env["host"]) == {"kit-pro"}
    assert sealed.saved("local/max") == "max-pw", "记在它实际打开的那个组名下"
    main(["status", "--offline"])
    assert "口令组：pro/max" in capsys.readouterr().out


def test_password_saved_for_one_skill_opens_the_other(env, monkeypatch):
    typing(monkeypatch, "max-pw")
    main(["install", "kit-max", "--hosts", "H"])
    typing(monkeypatch)                              # 装 kit-pro 不该再问：本机记过 max 的口令
    assert main(["install", "kit-pro", "--hosts", "H"]) == 0
    assert dirs(env["host"]) == {"kit-pro"}


def test_prompt_says_which_groups_work(env, monkeypatch):
    asked = []
    monkeypatch.setattr(sealed, "interactive", lambda: True)
    monkeypatch.setattr(sealed, "ask", lambda p: (asked.append(p), "pro-pw")[1])
    main(["install", "kit-pro", "--hosts", "H"])
    assert "pro 或 max 组的都行" in asked[0] and "找组长要" in asked[0]


def test_publish_checks_each_group_against_its_own_key(env, monkeypatch, capsys):
    """问 pro 组口令时输成 max 的：它也能打开 kit-pro 的包，但不是 pro 组的——要拦住，不然 pro 那份就被悄悄换成了 max 的口令。"""
    (env["src"] / "kit-pro" / "SKILL.md").write_text("---\nname: kit-pro\nmetadata:\n  version: 1.1.0\n---\n", encoding="utf-8")
    assert _publish(monkeypatch, env["src"], env["repo"], "--only", "kit-pro", pw={"pro": "max-pw", "max": "max-pw"}) != 0
    assert "打不开仓库里现有的 pro 组的包" in capsys.readouterr().out
