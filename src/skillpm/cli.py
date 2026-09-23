"""命令行入口：install / update / status / uninstall / repo / host / self-update。"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from skillpm import HOMEPAGE, __version__
from skillpm.changelog import for_skill, sections_since
from skillpm.config import (backup_dir, cache_dir, config_path, home, load_config, load_state,
                             save_config, save_state, state_path)
from skillpm.console import (BLUE, BOLD, CODE, DIM, GREEN, PATH_C, RED, RESET, YELLOW, Abort,
                              ask, confirm, choose, die, ensure_utf8_stdio, info, md_line, ok, remember_secret, say, warn)
from skillpm import index, lockfile, sealed
from skillpm.sources import locate, parse as parse_source
from skillpm.hosts import (CATALOG, confidence, describe, detect, name_for_path, detect_project, project_capable,
                            project_dir, supports_project)
from skillpm.repos import fetch, fetch_all, git_url, has_git, manifest_of, parse_ssh, run_git
from skillpm.skills import ConflictLog, backup, install, local_changes



# ── 公共 ──────────────────────────────────────────────────────────────────

def all_skills(fetched, prefer=None):
    """把各仓库的 Skill 汇总成 {skill名: (仓库名, 目录, info)}，给「装哪些」列表用。

    同名的默认先来后到；prefer={名字: 仓库名} 点了名的就用点的那个仓库
    （`install 乙:demo-a`）。已经装上的 Skill 该跟哪个仓库比，别用这个，用 source_of()。
    """
    prefer = prefer or {}
    out, seen = {}, {}
    for rname, (rdir, man) in fetched.items():
        for sname, entry in man.get("skills", {}).items():
            if sname in out:
                if prefer.get(sname) == rname:
                    out[sname], seen[sname] = (rname, rdir, entry), rname
                elif prefer.get(sname) != seen[sname]:
                    warn(f"{sname} 在 {seen[sname]} 和 {rname} 里都有，用先配的那个（{seen[sname]}）；"
                         f"要 {rname} 的写 {rname}:{sname}")
                continue
            out[sname], seen[sname] = (rname, rdir, entry), rname
    return out


def source_of(fetched, name, rec):
    """已经装上的 Skill 该跟哪个仓库比：**按安装记录里的来源仓库**，不按名字先来后到。

    返回 ((仓库名, 目录, info), None)，或者 (None, 为什么找不到)。
    1.20.0 之前按名字找：从乙装的，update 会拿先配的甲的同名 Skill 去比、去覆盖。
    """
    repo = rec.get("repo")
    if repo:
        if repo not in fetched:
            return None, f"来源仓库 {repo} 已经不在配置里了（skillpm repo list 看看）"
        entry = (fetched[repo][1].get("skills") or {}).get(name)
        if not entry:
            return None, f"来源仓库 {repo} 里已经没有 {name} 了"
        return (repo, fetched[repo][0], entry), None
    # 很老的安装记录没写来源：只有一个仓库有它才敢认
    holders = [r for r, (_d, m) in fetched.items() if name in (m.get("skills") or {})]
    if not holders:
        return None, "仓库里已经没有了"
    if len(holders) > 1:
        return None, (f"安装记录里没写来源，{'、'.join(holders)} 里都有同名的，不敢猜；"
                      f"用 skillpm install 仓库名:{name} --force 重装一次就记上了")
    r = holders[0]
    return (r, fetched[r][0], fetched[r][1]["skills"][name]), None



def repo_commit(repo_dir):
    """锁文件要锁到 commit，不能只锁版本号——同一个版本号的内容也可能被改过。"""
    try:
        return run_git(["rev-parse", "HEAD"], cwd=repo_dir).strip()
    except (RuntimeError, OSError):
        return None


def project_hosts(root, cfg):
    """项目级装到哪：优先项目里已有的宿主目录；一个都没有就问用户建哪个。

    只有编程类 Agent 支持项目级；别的 Agent 全局生效，这里一个都不会列。
    """
    found = detect_project(root)
    if found:
        return found
    capable = project_capable()
    if not capable:
        return {}
    say()
    warn(f"{root} 下还没有任何项目级目录")
    info("项目级只有编程类 Agent 支持，目录跟随它们自己的约定（.claude/skills、.cursor/rules …）")
    opts = [(n, f"会建 {project_dir(n)}　{confidence(n)}") for n in capable]
    picked = choose("在这个项目里用哪个？", opts, preselect=[0])
    return {n: str(Path(root) / project_dir(n)) for n, _ in picked}


def install_one(catalog, name, dest, host, scope, lock, root, force=False, src=None):
    """装一个 Skill；项目级的同时写进锁文件。src：加密存放的 Skill 解开后的目录（普通 Skill 不给）。"""
    rname, rdir, meta = catalog[name]
    rec = install(src or rdir, name, meta, dest, backup_existing=force)
    rec["repo"], rec["host"], rec["scope"] = rname, host, scope
    if meta.get("tier"):
        rec["tier"] = meta["tier"]
    if meta.get("lock"):
        rec["lock"] = meta["lock"]
    rec["commit"] = repo_commit(rdir)        # 用户级也记 commit，freeze 时才导得出来
    if scope == "project":
        cfg = load_config()
        src = (cfg.get("repos", {}).get(rname) or {})
        lockfile.record(lock, name, repo=rname,
                        source=src.get("ssh") or src.get("http") or "",
                        commit=repo_commit(rdir), version=meta["version"], host=host,
                        rel_path=str(Path(dest).resolve().relative_to(Path(root).resolve()) / name),
                        files=meta["files"])
    return rec


TIER_RANK = {"read": 0, "write": 1, "admin": 2}


def excl_group(name, meta):
    """互斥组（同一宿主只装一个）：以仓库 skillpm.repo.json 的 exclusive 为准；
    老 manifest 没有这个字段时，退回按「SKILL.md 写了 tier、名字以 -<tier> 结尾」认。不属于任何组返回 None。"""
    meta = meta or {}
    if meta.get("exclusive"):
        return meta["exclusive"]
    t = meta.get("tier")
    return name[:-len(t) - 1] if t and name.endswith("-" + t) else None


def excl_rank(meta):
    """组内从低到高的位置：默认装最低、不要口令的那个。"""
    meta = meta or {}
    if "rank" in meta:
        return meta["rank"]
    return TIER_RANK.get(meta.get("tier"), 50 if meta.get("sealed") else 0)


def label_of(name, meta):
    return (meta or {}).get("tier") or name


def _refresh_index(state, key):
    entry = state["hosts"].get(key, {})
    path = entry.get("path")
    if not path:
        return
    entries = [{"name": n, "version": r.get("version", "?"), "repo": r.get("repo"), "summary": ""}
               for n, r in entry.get("skills", {}).items()]
    if entries:
        index.write(path, entries, entry.get("scope", "global"))
    else:
        f = Path(path) / "AGENTS.md"
        if f.exists():
            text = re.sub(index.BLOCK_RE, "", f.read_text(encoding="utf-8")).strip()
            f.write_text(text + "\n", encoding="utf-8") if text else f.unlink()


def _drop(state, key, name):
    entry = state["hosts"][key]
    shutil.rmtree(Path(entry["path"]) / name, ignore_errors=True)
    entry["skills"].pop(name, None)


def replace_siblings(state, key, name, members):
    """同一个宿主上同一组只留一级：装上 name 之后，把同组别的级别卸掉。返回卸掉的名字。"""
    entry = state["hosts"][key]
    gone = [n for n in list(entry.get("skills", {})) if n != name and n in members]
    for n in gone:
        _drop(state, key, n)
    return gone


def group_members(catalog_or_man, group):
    """同一组的所有级别：{名字: meta}。catalog 的值是 (仓库, 目录, meta)，manifest 的值是 meta，两种都收。"""
    out = {}
    for n, v in catalog_or_man.items():
        meta = v[2] if isinstance(v, tuple) else v
        if excl_group(n, meta) == group:
            out[n] = meta
    return out


def locked_hint(name, why):
    warn(f"{name} 没装：{why}")
    if not sealed.interactive():
        info(f"口令只能你自己在终端里输：请手动运行 skillpm install {name}（口令不要发给 AI）")
    else:
        info(f"口令找发放的人要；拿到后重新运行 skillpm install {name}")


def migrate_tiers(fetched, state):
    """互斥组里装了不止一个的（以前会一回车全装上），每个宿主只留一个：
    要留要口令的那个就输它的口令；直接回车只留组里最低、不要口令的那个。"""
    changed = False
    for rname, (rdir, man) in fetched.items():
        skills = man.get("skills") or {}
        for g in sorted({excl_group(n, m) for n, m in skills.items()} - {None}):
            members = group_members(skills, g)
            hosts = [(k, e) for k, e in (state.get("hosts") or {}).items()
                     if e.get("scope") != "project" and sum(1 for n in e.get("skills", {}) if n in members) > 1]
            if not hosts:
                continue
            have = sorted({n for _k, e in hosts for n in e["skills"] if n in members}, key=lambda n: excl_rank(members[n]))
            base = min((n for n in members if not members[n].get("sealed")), key=lambda n: excl_rank(members[n]), default=None)
            locked = sorted((n for n in have if members[n].get("sealed")), key=lambda n: -excl_rank(members[n]))
            say()
            warn(f"{g} 组同时装了 {' / '.join(have)}。同一组每个宿主只保留一个")
            if locked and not sealed.interactive():
                info("请在终端里手动跑一次 skillpm update，选择保留哪一个（口令不要发给 AI）")
                continue
            keep, src = base, rdir
            for i in range(3 if locked else 0):
                pw = sealed.ask(f"要保留 {' 或 '.join(locked)}，输入它的口令；直接回车只保留 {base or '组里最低的那个'}："
                                if i == 0 else "口令不对，再输一次（直接回车放弃）：")
                if not pw:
                    break
                hit = next(((n, r) for n in locked for r in [sealed.try_open(rname, rdir, n, members[n], pw)] if r), None)
                if hit:
                    keep, src = hit
                    break
            if not keep:
                continue
            for key, entry in hosts:
                if keep not in entry["skills"]:
                    rec = install(src, keep, members[keep], entry["path"])
                    rec.update(repo=rname, host=key.split(":")[-1], scope=entry.get("scope", "global"))
                    for f in ("tier", "lock"):
                        if members[keep].get(f):
                            rec[f] = members[keep][f]
                    entry["skills"][keep] = rec
                for f in ("tier", "lock"):             # 以前装的记录里没有这两个，status 要靠它显示权限
                    if members[keep].get(f):
                        entry["skills"][keep][f] = members[keep][f]
                gone = replace_siblings(state, key, keep, members)
                ok(f"{key.split(':')[-1]}：保留 {BOLD}{keep}{RESET}，已卸掉 {'、'.join(gone)}")
                _refresh_index(state, key)
                changed = True
    if changed:
        save_state(state)


def _confirm_switch(host, name, prev, new_repo, meta):
    """同一个宿主下同名 Skill 只能留一个。已经装的来自别的仓库时，换之前要问——默认不换。

    1.20.2 之前不问：装过甲的 demo-a，再装乙的，直接顶掉，屏幕上看不出来源换了。
    """
    say()
    warn(f"{host}：{name} 现在装的是「{prev['repo']}」的 {prev.get('version', '?')}，"
         f"这次要换成「{new_repo}」的 {meta['version']}")
    info("同一个 Agent 下同名的只能留一个；换了以后就跟着新仓库更新")
    if not _interactive():
        info("没有可交互的输入，默认不换。确定要换就加 --force")
        return False
    return confirm("确定换吗？", default=False)


def _interactive():
    """非交互环境（管道、CI、测试）下不该弹选择，直接用已配的。"""
    import sys as _s
    return _s.stdin is not None and _s.stdin.isatty()


def known_hosts(cfg, state=None):
    """宿主注册表：配置里记的 + 装过东西但配置里没有的。

    1.9.0 之前 `install` 会拿本次选中的宿主**整个覆盖** cfg["hosts"]，
    于是「上次装 WorkBuddy、这次装 WorkBuddy-AI」会把 WorkBuddy 从表里抹掉——
    可它目录里的 Skill 还在，state 也还记着。这里按并集给回去，
    下一次 install 保存时就把它并回配置，老配置能自己长好。
    """
    out = dict(cfg.get("hosts") or {})
    st = load_state() if state is None else state
    for key, entry in (st.get("hosts") or {}).items():
        if entry.get("scope") != "global" or not entry.get("path"):
            continue
        out.setdefault(key.split(":")[-1], entry["path"])
    return out


def pick_hosts(cfg, a=None, ask=False):
    """决定装到哪些宿主。

    ask=True 时每次都让你确认一遍（默认勾上次选的，回车即可）——
    装到哪儿是每次都可能变的决定，不该在第一次引导里定死。
    """
    saved = known_hosts(cfg)
    if a is not None and getattr(a, "hosts", None):
        want = {h.lower().replace(" ", "-") for h in a.hosts}
        pool = {**detect(), **saved}
        picked = {n: p for n, p in pool.items() if n.lower().replace(" ", "-") in want}
        missing = want - {n.lower().replace(" ", "-") for n in picked}
        if missing:
            hint = f"可选：{'、'.join(sorted(pool))}；或者 skillpm host add <名字> <路径>"
            # --hosts 是 nargs="*"，会把后面的词一路吃进来——包括本来想当 Skill 名的那个
            if len(a.hosts) > 1:
                hint += ("\n  注意 --hosts 后面会一直吃到下一个选项为止；"
                         "Skill 名要写在它前面："
                         "skillpm install <Skill名> --hosts <宿主>")
            die(f"不认识这些宿主：{'、'.join(sorted(missing))}", hint)
        return picked

    if saved and ask and _interactive():
        pool = {**detect(), **saved}          # 已配的 + 本机新探到的
        if len(pool) > 1:
            say()
            say(f"{BOLD}装到哪些宿主？{RESET}")
            names = sorted(pool)
            opts = []
            for n in names:
                mark = "" if n in saved else f"　{DIM}（本机探到，还没配过）{RESET}"
                conf = f"　{YELLOW}{describe(n)}{RESET}" if describe(n) else ""
                opts.append((n, f"{pool[n]}{mark}{conf}"))
            # 预选＝上次实际装的那几个；没这个记录就退回「配置里有的」
            last = cfg.get("last_hosts") or list(cfg.get("hosts") or saved)
            pre = [i for i, n in enumerate(names) if n in last]
            typed = []
            picked = dict(choose("", opts, preselect=pre, paths=typed))
            return {**{n: pool[n] for n in picked}, **_typed_hosts(typed, pool)}
    if saved:
        return saved
    found = detect()
    if found:
        say()
        say(f"{BOLD}探测到这些宿主{RESET}")
        opts = []
        for n, p in found.items():
            note = f"{p}　（{describe(n)}）" if describe(n) else p
            opts.append((n, note))
        typed = []
        hosts = dict(choose("要装到哪几个？", opts, paths=typed))
        hosts = {**{n: found[n] for n in hosts}, **_typed_hosts(typed, found)}
    if not hosts:
        warn("没探测到宿主，或者你一个都没选")
        info("那就手动填：宿主叫什么、它的 skills 目录在哪")
        while True:
            name = ask("宿主名字（比如 WorkBuddy）")
            path = ask(f"{name} 的 skills 目录完整路径")
            hosts[name] = str(Path(path).expanduser())
            if not confirm("还要再加一个吗？", default=False):
                break
    return hosts


def _typed_hosts(typed, pool):
    """选宿主时手填的路径 → {宿主名: 路径}。

    填的是 Agent 文件夹本身（~/.foo）而它下面有 skills，就问一句是不是想装进 skills；
    目录不存在的也问一句，防手滑打错字。
    """
    out = {}
    for raw in typed:
        p = Path(os.path.expandvars(raw)).expanduser().resolve()
        if p.name.lower() != "skills" and (p / "skills").is_dir():
            if confirm(f"{p} 下面有 skills 目录，装到 {p / 'skills'} 吗？", default=True):
                p = p / "skills"
        if not p.is_dir() and not confirm(f"{p} 还不存在，装的时候新建它？", default=False):
            info(f"跳过 {raw}")
            continue
        name = name_for_path(p)
        taken = {**pool, **out}
        if name in taken and Path(taken[name]).expanduser().resolve() != p:
            k = 2
            while f"{name}-{k}" in taken:
                k += 1
            name = f"{name}-{k}"                  # 重名但不是同一个目录：别覆盖已有的
        out[name] = str(p)
        ok(f"手填的目录记为宿主「{name}」：{p}")
    return out


def check_python_deps(catalog, names):
    need = set()
    for n in names:
        entry = catalog.get(n)
        for mod in ((entry[2].get("requires_python") if entry else None) or []):
            need.add(mod)
    missing = []
    for mod in sorted(need):
        try:
            __import__(mod)
        except ImportError:
            missing.append({"PIL": "Pillow"}.get(mod, mod))
    if missing:
        say()
        warn(f"这些 Python 包没装，相关 Skill 的脚本会用到：{'、'.join(missing)}")
        info("自己挑个时间装上（本工具不动你的 Python 环境）：")
        say(f"  pip install {' '.join(missing)}")


# ── 命令 ──────────────────────────────────────────────────────────────────

def cmd_install(a):
    from_lock = getattr(a, "from_lock", None)
    lock_data = None
    if from_lock:
        # 先验锁文件再走引导——文件都不对就别让人白答四个问题
        lock_data = read_lock_file(Path(from_lock).expanduser())

    cfg = load_config()
    if not config_path().exists() or a.reconfigure:
        cfg = onboarding(cfg)
    if from_lock:
        return install_from_lock(a, cfg, Path(from_lock).expanduser(), lock_data)
    only_repo = pick_repo(cfg, a)
    if only_repo:
        a.repo = only_repo
        sub_cfg = {**cfg, "repos": {only_repo: cfg["repos"][only_repo]}}
        catalog = all_skills(fetch_all(sub_cfg))
    else:
        prefer = dict(reversed(x.split(":", 1)) for x in (a.only or []) if ":" in x)
        catalog = all_skills(fetch_all(cfg), prefer)

    root = lockfile.find_root()
    lock = lockfile.load(root)
    # 默认用户级：绝大多数 Agent 全局生效，没有项目概念。只有编程类 Agent 才分项目级。
    scope = "project" if getattr(a, "project", False) else "global"
    if scope == "project" and not is_project_root(root):
        die(f"{root} 是你的家目录，不是一个项目",
            "这里的 .claude/skills、.codex/skills 本来就是用户级目录，"
            "-p 装到的是同一个地方，还会在家目录里留一个 skillpm.lock。"
            "要装项目级就先 cd 到那个代码仓库里；就想全局装的话去掉 -p。")
    if scope == "global":
        hint_project_scope(root, lock)
    return _do_install(a, cfg, catalog, root, lock, scope)


def is_project_root(root):
    """这个目录算不算一个「项目」。

    家目录不算：`~/.codex/skills`、`~/.claude/skills` 本来就是**用户级**目录，
    在家目录下跑的时候它们会被当成「项目里的目录」，于是提示你用 -p——
    可 -p 装到的是同一个地方，还会在家目录里丢一个 skillpm.lock。
    文件系统根目录同理，不该被当成项目。
    """
    root = Path(root).resolve()
    return root != Path.home().resolve() and root != Path(root.anchor)


def hint_project_scope(root, lock):
    """在编程类 Agent 的项目里装全局时提一句，但不擅自改行为。"""
    if not is_project_root(root):
        return
    if lock.get("skills"):
        say()
        warn(f"{root} 下有 {lockfile.LOCK_NAME}，说明这个项目有自己的 Skill 基线")
        info(f"要按它复现请加 -p：skillpm install -p")
        return
    here = detect_project(root)
    if here:
        say()
        info(f"顺带一提：这个项目里有 {'、'.join(here)} 的目录，"
             f"想让 Skill 只在本项目生效可以用 skillpm install -p")


def read_lock_file(lock_path):
    """读并校验锁文件。有问题立刻说清楚，不要等走完引导才报。"""
    import json as _json
    if not lock_path.exists():
        die(f"找不到 {lock_path}", "确认路径对不对；生成锁文件用 skillpm freeze")
    try:
        lock = _json.loads(lock_path.read_text(encoding="utf-8"))
    except ValueError as e:
        die(f"{lock_path} 不是合法 JSON：{e}", "多半是 git 合并冲突没解干净，看看有没有 <<<<<<< 标记")
    if not isinstance(lock, dict) or not (lock.get("skills") or {}):
        die(f"{lock_path} 里没有记录任何 Skill")
    return lock


def install_from_lock(a, cfg, lock_path, lock=None):
    """按别人给的锁文件装回同一套：每个 Skill 都切到它记的那个 commit。"""
    lock = lock or read_lock_file(lock_path)
    skills = lock["skills"]

    say()
    info(f"按 {lock_path.name} 复现 {len(skills)} 个 Skill")
    hosts = pick_hosts(cfg, a, ask=True)
    if getattr(a, "agent", None):
        hosts = {n: p for n, p in hosts.items()
                 if n.lower().replace(" ", "-") == a.agent.lower()} or die(
                     f"没有叫「{a.agent}」的宿主")

    # 同一个仓库的多个 Skill 可能锁在不同 commit，按 commit 分批拉
    by_commit = {}
    for name, rec in skills.items():
        by_commit.setdefault((rec.get("repo"), rec.get("commit")), []).append((name, rec))

    conflicts, state = ConflictLog(), load_state()
    for (rname, commit), items in by_commit.items():
        repo = (cfg.get("repos") or {}).get(rname)
        if not repo:
            warn(f"锁里写的仓库「{rname}」本机没配，跳过 {len(items)} 个 Skill")
            info(f"配上它：skillpm repo add {rname} --ssh <地址>")
            continue
        rdir = fetch(rname, repo, ref=commit)
        man = manifest_of(rdir, rname)
        for name, rec in items:
            meta = man.get("skills", {}).get(name)
            if not meta:
                warn(f"{name} 在 {rname}@{str(commit)[:8]} 里不存在，跳过")
                continue
            if meta["version"] != rec.get("version"):
                warn(f"{name}：锁里写的是 {rec.get('version')}，"
                     f"这个 commit 上是 {meta['version']}——按 commit 为准")
            for host, path in hosts.items():
                key = host
                entry = state["hosts"].setdefault(key, {"path": path, "skills": {}, "scope": "global"})
                entry["path"] = path
                src, why = sealed.open_skill(rname, rdir, name, meta)
                if src is None:
                    locked_hint(name, why)
                    break
                if conflicts.check(host, path, name, entry["skills"].get(name), a.force, src):
                    continue
                new = install(src, name, meta, path, backup_existing=a.force)
                new["repo"], new["host"], new["scope"], new["commit"] = rname, host, "global", commit
                entry["skills"][name] = new
                ok(f"{name}  {meta['version']}  {DIM}{rname}@{str(commit)[:8]}  {host}{RESET}")
    save_state(state)
    say()
    if len(conflicts):
        warn(f"部分完成：{len(conflicts)} 项因为冲突没动")
    else:
        ok("复现完成，和锁文件里记的一致。")
    return conflicts.report()


def _do_install(a, cfg, catalog, root, lock, scope):
    custom = getattr(a, "dir", None)
    if custom:
        # -d 指定了目录，下面会把 hosts 整个换掉——那就别再问「装到哪些宿主」，
        # 问了答案也是丢掉，白让人选一遍。
        d = Path(custom).expanduser().resolve()
        hosts = {f"自定义:{d.name}": str(d)}
        say()
        info(f"装到自定义目录 {d}（不归任何宿主管，你自己保证它被读到）")
    elif scope == "global":
        # 装到哪儿每次都可能不一样，所以每次都确认（回车＝沿用上次）
        hosts = pick_hosts(cfg, a, ask=True)
        # 宿主表是**累积**的注册表，只有 host remove 才该删；
        # 本次装到哪另记 last_hosts，只用来决定下次的默认勾选。
        cfg["hosts"] = {**known_hosts(cfg), **hosts}
        cfg["last_hosts"] = sorted(hosts)
        save_config(cfg)
        say()
        info("全局安装：装到用户级目录，对你所有项目生效，不写锁文件")
    else:
        hosts = project_hosts(root, cfg)
        if not hosts:
            die("没有可用的项目级宿主",
                f"支持项目级的只有编程类 Agent：{'、'.join(project_capable())}。"
                "别的 Agent 是全局生效的，直接 skillpm install 就行")
        say()
        info(f"项目级安装：装到 {root}，版本写进 {lockfile.LOCK_NAME} 随项目提交")


    want_host = getattr(a, "agent", None)
    if want_host:
        matched = {n: p for n, p in hosts.items() if n.lower().replace(" ", "-") == want_host.lower()}
        if not matched:
            die(f"没有叫「{want_host}」的宿主",
                f"本次可选：{'、'.join(hosts)}；全部认识的用 skillpm host list 看")
        hosts = matched

    names = _pick_names(a, catalog, lock, scope)
    if not names:
        die("一个都没选")
    # 加密存放的级别：先解开（本机记过口令就不问；没记过、在终端里就当场问）
    opened = {}
    for n in list(names):
        rname, rdir, meta = catalog[n]
        src, why = sealed.open_skill(rname, rdir, n, meta)
        if src is None:
            locked_hint(n, why)
            names.remove(n)
        elif meta.get("sealed"):
            opened[n] = src
            ok(f"口令正确：{n}")
    if not names:
        return 1

    conflicts, state = ConflictLog(), load_state()
    switch_skipped = []
    for host, path in hosts.items():
        Path(path).mkdir(parents=True, exist_ok=True)
        say()
        say(f"{BOLD}→ {host}{RESET}  {PATH_C}{path}{RESET}")
        key = f"{scope}:{root}:{host}" if scope == "project" else host
        entry = state["hosts"].setdefault(key, {"path": path, "skills": {}, "scope": scope})
        entry["path"], entry["scope"] = path, scope
        for n in names:
            rname, rdir, meta = catalog[n]
            prev = entry["skills"].get(n)
            if prev and prev.get("repo") and prev["repo"] != rname and not a.force \
                    and not _confirm_switch(host, n, prev, rname, meta):
                switch_skipped.append((host, n, prev["repo"], rname))
                continue
            if conflicts.check(host, path, n, prev, a.force, rdir):
                continue
            entry["skills"][n] = install_one(catalog, n, path, host, scope, lock, root, a.force, src=opened.get(n))
            g = excl_group(n, meta)
            gone = replace_siblings(state, key, n, group_members(catalog, g)) if g else []
            if gone:
                info(f"{host}：{g} 组只保留一个，{'、'.join(gone)} 已换成 {n}")
            ok(f"{n}  {meta['version']}   {DIM}{rname}{RESET}"
               + (f"　{YELLOW}（来源从 {prev['repo']} 换成了 {rname}）{RESET}"
                  if prev and prev.get("repo") and prev["repo"] != rname else ""))
    if not getattr(a, "no_index", False):
        for host, path in hosts.items():
            recs = state["hosts"].get(f"{scope}:{root}:{host}" if scope == "project" else host,
                                      {}).get("skills", {})
            # 按安装记录写版本和来源——汇总表是按名字先来后到的，同名 Skill 会写错来源
            entries = [{"name": n, "version": r.get("version", "?"), "repo": r.get("repo"),
                        "summary": (catalog[n][2].get("summary", "")
                                    if n in catalog and catalog[n][0] == r.get("repo") else "")}
                       for n, r in recs.items()]
            if entries:
                index.write(path, entries, scope)
    save_state(state)
    if scope == "project" and lock.get("skills"):
        p = lockfile.save(root, lock)
        say()
        ok(f"版本已锁定：{p}")
        info(f"把它和宿主目录一起提交，别人 git pull 后跑 skillpm install 就能拿到同样的版本")
    check_python_deps(catalog, names)
    say()
    skipped = len(conflicts) + len(switch_skipped)
    if skipped:
        picked = len(names) * len(hosts)
        why = "、".join(x for x in (f"{len(conflicts)} 项冲突" if len(conflicts) else "",
                                   f"{len(switch_skipped)} 项没换来源" if switch_skipped else "") if x)
        warn(f"装好 {picked - skipped} 项，跳过 {skipped} 项（{why}）")
        for host, n, old, new in switch_skipped:
            info(f"  {host}：{n} 还是 {old} 的。确定要换成 {new} 的：skillpm install {new}:{n} --force")
    else:
        ok("装完了。")
        info("看装了什么：skillpm status；跟上更新：skillpm update")
    # 装的是分了权限级别的 Skill 的低级别：告诉人更高级别怎么装（要口令，点名装）
    for n in names:
        g = excl_group(n, catalog[n][2])
        higher = sorted((m for m, meta in group_members(catalog, g).items()
                         if meta.get("sealed") and excl_rank(meta) > excl_rank(catalog[n][2])),
                        key=lambda m: excl_rank(catalog[m][2])) if g else []
        if higher:
            info(f"{g} 组里还有要口令的：" + "、".join(higher) + f"；要换成它们：skillpm install {higher[0]}")
    code = conflicts.report()
    # 非交互环境下默认没换，要让脚本知道没照要求装上
    return code or (1 if switch_skipped and not _interactive() else 0)


def pick_repo(cfg, a):
    """配了多个仓库时先问从哪个装——混在一张表里选很容易搞混。

    只有一个仓库就别问了，多余。
    """
    if getattr(a, "repo", None):
        return a.repo
    if getattr(a, "all", False) or getattr(a, "only", None):
        return None                     # 已经说了要全部 / 点了名，再问从哪个仓库就是多余
    repos = list((cfg.get("repos") or {}))
    if len(repos) <= 1:
        return None                     # 只有一个（或没有），不用挑
    say()
    say(f"{BOLD}配了 {len(repos)} 个 Skill 仓库{RESET}")
    opts = [(r, (cfg["repos"][r].get("ssh") or cfg["repos"][r].get("http") or "")) for r in repos]
    opts.append(("全部", "把所有仓库的 Skill 放一起挑"))
    picked = choose("从哪个装？", opts, preselect=[len(opts) - 1])
    names = [n for n, _ in picked]
    if "全部" in names or len(names) != 1:
        return None
    return names[0]


def _pick_names(a, catalog, lock, scope):
    """决定装哪几个。项目级且没点名时，优先照锁文件复现。"""
    _pick_names.full = catalog
    if a.only:
        # --only 既收光名字，也收「仓库名:Skill名」——后者只在那个仓库里找
        plain = {x for x in a.only if ":" not in x}
        scoped = {tuple(x.split(":", 1)) for x in a.only if ":" in x}
        names = [n for n in catalog
                 if n in plain or (catalog[n][0], n) in scoped]
        missing = sorted(
            [x for x in plain if x not in catalog]
            + [f"{r}:{n}" for r, n in scoped
               if n not in catalog or catalog[n][0] != r])
        if missing:
            die(f"这些仓库里都没有：{'、'.join(missing)}",
                "看看有哪些：skillpm status 或 skillpm check")
        return names
    # 加密存放的高权限级别不进列表、不跟 --all / --repo 一起装：要装就点名，当场输口令
    catalog = {n: v for n, v in catalog.items() if not v[2].get("sealed")}
    if a.repo:
        names = [n for n in catalog if catalog[n][0] == a.repo]
        if not names:
            die(f"仓库 {a.repo} 里没有 Skill，或者这个仓库名不对", "看看有哪些：skillpm repo list")
        return names
    if scope == "project" and lock.get("skills") and not a.all:
        locked = [n for n in lock["skills"] if n in _pick_names.full]
        missing = [n for n in lock["skills"] if n not in _pick_names.full]
        if missing:
            warn(f"锁文件里这几个在仓库里找不到了：{'、'.join(missing)}")
        if locked:
            say()
            info(f"按 {lockfile.LOCK_NAME} 复现 {len(locked)} 个 Skill（要改动用 --only 或 --all）")
            return locked
    if a.all:
        return list(catalog)
    say()
    say(f"{BOLD}要装哪些 Skill？{RESET}")
    sealed_names = sorted(n for n, v in _pick_names.full.items() if v[2].get("sealed"))
    if sealed_names:
        info(f"要口令的 Skill 不在这个列表里（{'、'.join(sealed_names)}），要装就点名：skillpm install <名字>")
    # 多仓库时按仓库分组排，同一个来源的挨在一起，不容易挑串
    ordered = sorted(catalog, key=lambda n: (catalog[n][0], n))
    multi = len({catalog[n][0] for n in catalog}) > 1
    opts = [(n, f"{catalog[n][2]['version']}" + (f"　来自 {catalog[n][0]}" if multi else ""))
            for n in ordered]
    return [n for n, _ in choose("", opts)]


def cmd_freeze(a):
    """把当前装的版本导成一份锁文件，发给别人就能复现同一套。

    joySkills 的锁只服务项目级，但我们主力宿主（WorkBuddy）根本没有项目级概念，
    所以这里让锁脱离项目也能用：freeze 出来一份，别人 install --from 装回去。
    """
    state = load_state()
    if not state.get("hosts"):
        die("本地没有安装记录", "先跑 skillpm install")
    root = lockfile.find_root()
    lock = {"lockfile_version": lockfile.LOCK_VERSION, "skills": {}}
    for key, entry in state["hosts"].items():
        if a.host and key.split(":")[-1] != a.host:
            continue
        for name, rec in entry.get("skills", {}).items():
            if name in lock["skills"]:
                continue
            lock["skills"][name] = {
                "repo": rec.get("repo"), "source": "", "commit": rec.get("commit"),
                "version": rec.get("version"), "host": key.split(":")[-1],
                "path": "", "files": rec.get("files", {}),
            }
    if not lock["skills"]:
        die("没有可导出的安装记录")
    out = Path(a.out).expanduser() if a.out else lockfile.path_of(root)
    missing = [n for n, v in lock["skills"].items() if not v.get("commit")]
    lockfile.save(out.parent if out.name == lockfile.LOCK_NAME else out.parent, lock) \
        if out.name == lockfile.LOCK_NAME else out.write_text(
            __import__("json").dumps(lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ok(f"已导出 {len(lock['skills'])} 个 Skill 的版本 → {PATH_C}{out}{RESET}")
    if missing:
        warn(f"这几个没记到 commit（装的时候还没有这个字段）：{'、'.join(missing)}")
        info("重新装一次就会补上；没有 commit 时复现只能按版本号，不保证内容完全一致")
    info(f"别人拿这个文件装回同一套：skillpm install --from {out.name}")
    return 0


def cmd_check(a):
    """只检查有没有新版本，什么都不动。想更新再跑 skillpm update。"""
    cfg = load_config()
    if not cfg.get("repos"):
        die("还没配过", "先跑 skillpm install")
    fetched = fetch_all(cfg, quiet=True)
    state = load_state()
    root = lockfile.find_root()

    rows, dirty = [], []
    for key, entry in (state.get("hosts") or {}).items():
        scope = entry.get("scope", "global")
        if scope == "project" and str(root) not in key:
            continue
        for name, rec in entry.get("skills", {}).items():
            meta, why = source_of(fetched, name, rec)
            if not meta:
                rows.append((name, rec["version"], "—", key.split(":")[-1], why))
                continue
            if getattr(a, "repo", None) and meta[0] != a.repo:
                continue
            newv = meta[2]["version"]
            diff = local_changes(entry["path"], name, rec)
            if diff and (diff["changed"] or diff["missing"]):
                dirty.append((name, key.split(":")[-1], len(diff["changed"]) + len(diff["missing"])))
            if newv != rec["version"]:
                rows.append((name, rec["version"], newv, key.split(":")[-1], ""))

    if a.updatable_only and not rows:
        ok("都是最新的")
        return 0
    if rows:
        say(f"{BOLD}可以更新的（{len(rows)} 项）{RESET}")
        for name, old, new, host, note in rows:
            tail = f"   {DIM}{note}{RESET}" if note else ""
            say(f"  {BLUE}{name:<30}{RESET}{old:>9} → {BOLD}{new}{RESET}   {DIM}{host}{RESET}{tail}")
        if len(cfg.get("repos") or {}) > 1 and not getattr(a, "repo", None):
            info("多个仓库都在看；只想管一个用：skillpm check --repo <仓库名>")
    else:
        ok("都是最新的，没什么要更新")
    if dirty and not a.updatable_only:
        say()
        warn(f"这些本地改过，更新时会报冲突跳过（{len(dirty)} 项）")
        for name, host, n in dirty:
            say(f"  {name:<30}{DIM}{host}　{n} 个文件{RESET}")
    if rows:
        say()
        info("要更新：skillpm update")
    return 0


def cmd_update(a):
    cfg = load_config()
    if not cfg.get("repos"):
        die("还没配过", "先跑 skillpm install")
    fetched = fetch_all(cfg)
    state = load_state()
    if not state.get("hosts"):
        die("本地没有安装记录", "先跑 skillpm install")
    migrate_tiers(fetched, state)

    plans = []
    for host, entry in state["hosts"].items():
        for name, rec in entry.get("skills", {}).items():
            found, why = source_of(fetched, name, rec)
            if not found:
                warn(f"{host.split(':')[-1]}：{name} 没法更新——{why}，先留着不动")
                continue
            rname, rdir, meta = found
            if getattr(a, "repo", None) and rname != a.repo:
                continue                      # 只更新指定仓库来的
            if meta["version"] != rec["version"]:
                plans.append((host, entry["path"], name, rec, meta, rname, rdir))
    if getattr(a, "repo", None):
        fetched = {r: v for r, v in fetched.items() if r == a.repo}
    if not plans:
        scope_note = f"（只看了 {a.repo}）" if getattr(a, "repo", None) else ""
        ok(f"都是最新的，没什么要更新{scope_note}")
        show_not_installed(fetched, state)
        dirty = []
        for key, entry in state["hosts"].items():
            for name, rec in entry.get("skills", {}).items():
                diff = local_changes(entry["path"], name, rec)
                if diff and (diff["changed"] or diff["missing"]):
                    dirty.append((name, key.split(":")[-1],
                                  len(diff["changed"]) + len(diff["missing"])))
        if dirty:
            # 没新版本不代表没问题：本地改过的迟早会在下次更新时冲突，现在就说清楚
            say()
            warn(f"不过有 {len(dirty)} 项本地改过，和仓库不一致了")
            for name, host, n in dirty:
                say(f"  {name:<30}{DIM}{host}　{n} 个文件{RESET}")
            info("看具体差哪儿：skillpm check；想还原：skillpm uninstall 再 install")
        return 0

    say()
    say(f"{BOLD}有 {len(plans)} 项可以更新{RESET}")
    multi_repo = len({p[5] for p in plans}) > 1 or len(cfg.get("repos") or {}) > 1
    for host, path, name, rec, meta, _rn, _rd in plans:      # 先只预告谁要变
        src = f"　{DIM}来自 {_rn}{RESET}" if multi_repo else ""
        line = (f"  {BLUE}{name}{RESET}  {rec['version']} → {BOLD}{meta['version']}{RESET}"
                f"   {DIM}（{host}）{RESET}{src}")
        diff = local_changes(path, name, rec)
        if diff and (diff["changed"] or diff["missing"]):
            line += f"   {YELLOW}本地改过，会跳过{RESET}"
        say(line)

    say()
    if not (a.yes or confirm("确认更新？", default=True)):
        say("那就先不动。")
        return 0

    conflicts, done = ConflictLog(), []
    for host, path, name, rec, meta, rname, rdir in plans:
        src, why = sealed.open_skill(rname, rdir, name, meta)
        if src is None:
            warn(f"{name} {rec['version']} → {meta['version']} 没更新（{host}）：{why}；旧版先留着，不影响使用")
            info(f"重新输口令：skillpm install {name}")
            continue
        if conflicts.check(host, path, name, rec, a.force, src):
            continue
        b = backup(path, name, rec["version"])          # 干净更新也留一份，方便回退
        new = install(src, name, meta, path, backup_existing=a.force)
        new["repo"] = rname
        for f in ("tier", "lock"):
            if meta.get(f):
                new[f] = meta[f]
        state["hosts"][host]["skills"][name] = new
        done.append({"host": host, "name": name, "from": rec["version"],
                     "to": meta["version"], "backup": b, "dir": src})
    show_update_summary(done)
    save_state(state)
    show_not_installed(fetched, state)
    # 依赖按「这次实际从哪个仓库更新的」查，不按名字去汇总表里找
    check_python_deps({p[2]: (p[5], p[6], p[4]) for p in plans}, [d["name"] for d in done])
    return conflicts.report()


def show_update_summary(done):
    """更新成功之后：更新了几个、每个改了什么，一次说清楚。"""
    if not done:
        return
    grouped = {}
    for d in done:
        grouped.setdefault((d["name"], d["from"], d["to"]), []).append(d)
    say()
    extra = f"（涉及 {len(done)} 处安装）" if len(done) != len(grouped) else ""
    say(f"{GREEN}{BOLD}更新成功：{len(grouped)} 个 Skill{extra}{RESET}")
    for (name, old_v, new_v), items in grouped.items():
        say()
        hosts = "、".join(sorted({i["host"] for i in items}))
        say(f"{BLUE}{BOLD}{name}{RESET}  {old_v} → {BOLD}{new_v}{RESET}   {DIM}{hosts}{RESET}")
        log = for_skill(items[0]["dir"], name, old_v)
        if log:
            for line in log.splitlines():
                say(f"  {md_line(line)}" if line.strip() else "")
        else:
            info("（这个版本没写更新日志）")
        for i in items:
            if i["backup"]:
                info(f"旧版备份：{i['backup']}")


def _excl_group(rdir, name, _cache={}):
    """同一个 Skill 分了权限级别的（SKILL.md 里写 `tier: write`，名字以 -write 结尾），返回去掉级别的组名。

    这类按权限挑一个装就够：装了其中一个，其余级别不算「没装」。没写 tier 的返回 None。
    """
    key = (str(rdir), name)
    if key not in _cache:
        from skillpm.manifest import _field, _frontmatter
        try:
            front = _frontmatter((Path(rdir) / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
        except OSError:
            front = ""
        tier = _field(front, "tier") if front else None
        _cache[key] = name[:-len(tier) - 1] if tier and name.endswith("-" + tier) else None
    return _cache[key]


def not_installed(fetched, state):
    """仓库里有、本机用户级宿主没装的 Skill：[(仓库名, Skill名, info, [宿主…])]。

    只看装过这个仓库东西的宿主——配了仓库却一个都没从它装过，多半是有意不用，别去烦人。
    项目级安装跟着锁文件走，不在这儿管。
    """
    miss = {}
    for key, entry in (state.get("hosts") or {}).items():
        if entry.get("scope") == "project":
            continue
        have = entry.get("skills") or {}
        for rname in sorted({r.get("repo") for r in have.values()} & set(fetched)):
            rdir, man = fetched[rname]
            mskills = man.get("skills") or {}
            groups = {excl_group(n, mskills.get(n)) or _excl_group(rdir, n) for n in have} - {None}
            for name, meta in sorted(mskills.items()):
                if meta.get("sealed"):
                    continue                      # 要口令的级别不提示安装
                if name in have or (excl_group(name, meta) or _excl_group(rdir, name)) in groups:
                    continue
                miss.setdefault((rname, name), (meta, []))[1].append(key.split(":")[-1])
    return [(r, n, m, h) for (r, n), (m, h) in miss.items()]


def show_not_installed(fetched, state):
    """仓库里有、本机没装的 Skill，每次 update / status 都列出来，直到装上或者被 ignore。

    不自动装——按权限分级、只装一个级别的（xx-read / -write / -admin），自动补上就越权了。
    """
    ignored = set(state.get("ignored_skills") or [])
    items = [x for x in not_installed(fetched, state) if x[1] not in ignored]
    if not items:
        return
    say()
    say(f"{BOLD}仓库里有 {len(items)} 个 Skill 本机还没装{RESET}"
        f"　{DIM}update 只更新装过的，新加的要自己装{RESET}")
    width = max(len(n) for _r, n, _m, _h in items)
    for _rname, name, meta, hosts in items:
        say(f"  {BLUE}{name:<{width}}{RESET}  {meta.get('version', '?'):<9}{DIM}{'、'.join(hosts)} 没装{RESET}")
        brief = (meta.get("summary") or "").split("。")[0].split("：")[0]
        if brief:
            say(f"  {' ' * width}  {brief[:40]}{'…' if len(brief) > 40 else ''}")
    names = " ".join(n for _r, n, _m, _h in items)
    # 这一行是要人照着敲的，用加粗正红，别被淹在说明文字里
    say(f"  {BOLD}{RED}要装：skillpm install {names}{RESET}")
    say(f"  不想装、也不想再看到这个提示：{BOLD}skillpm ignore {names}{RESET}")


def cmd_ignore(a):
    """不再提示安装某些 Skill；不写名字就列出忽略了哪些。"""
    state = load_state()
    ignored = set(state.get("ignored_skills") or [])
    if not a.names:
        if not ignored:
            ok("没有忽略任何 Skill，没装的都会提示")
        else:
            say(f"{BOLD}这些不提示安装{RESET}")
            for n in sorted(ignored):
                say(f"  {BLUE}{n}{RESET}")
            info("想恢复提示：skillpm ignore --undo <名字>")
        return 0
    if a.undo:
        gone = [n for n in a.names if n in ignored]
        miss = [n for n in a.names if n not in ignored]
        ignored -= set(gone)
        if gone:
            ok(f"恢复提示：{'、'.join(gone)}（没装的话 update / status 会再提醒）")
        if miss:
            warn(f"本来就没忽略：{'、'.join(miss)}")
    else:
        ignored |= set(a.names)
        ok(f"以后不再提示安装：{'、'.join(a.names)}")
        info(f"想恢复提示：skillpm ignore --undo {' '.join(a.names)}；看忽略了哪些：skillpm ignore")
    state["ignored_skills"] = sorted(ignored)
    save_state(state)
    return 0


def _lock_password(lock, repo, existing, new_password):
    """拿这个口令组的口令：环境变量 SKILLPM_LOCK_<组名> 或终端里输。仓库里已经有这个组的包时，先核对口令对不对，
    免得手滑输错、发出去一批谁都打不开的包；第一次（或 --new-password）要输两遍。"""
    env = "SKILLPM_LOCK_" + re.sub(r"[^A-Za-z0-9]", "_", lock).upper()
    pw = os.environ.get(env)
    if not pw:
        if not sealed.interactive():
            die(f"没有 {lock} 组的口令", f"在终端里手动运行（会让你输），或者设环境变量 {env}")
        pw = sealed.ask(f"{lock} 组的口令：")
    if not pw:
        die("口令为空")
    if existing and not new_password:
        if not sealed.check_password(existing, pw):
            die(f"这个口令打不开仓库里现有的 {lock} 组的包（{existing.name}）",
                "输错了就重来；确实要换口令，加 --new-password（这个组的每个 Skill 都会用新口令重新加密）")
    elif not os.environ.get(env) and sealed.ask("再输一遍：") != pw:
        die("两遍不一致，什么都没动")
    return pw


def cmd_publish(a):
    """发版：把明文 Skill 目录发布进仓库。skillpm.repo.json 里要口令的，加密成 sealed/<名字>.pkg（明文不进仓库）；其余复制到 skills/。
    最后重建 manifest.json。只动文件，不 git commit。"""
    from skillpm import manifest as mf
    src, repo = Path(a.source).expanduser().resolve(), Path(a.repo).expanduser().resolve()
    cfg, errs = mf.repo_config(repo)
    if errs:
        die("；".join(errs))
    locked = cfg.get("locked") or {}
    dirs = [src] if (src / "SKILL.md").is_file() else sorted(d for d in src.iterdir() if (d / "SKILL.md").is_file())
    if a.only:
        dirs = [d for d in dirs if d.name in a.only]
        missing = sorted(set(a.only) - {d.name for d in dirs})
        if missing:
            die(f"{src} 下没有：{'、'.join(missing)}")
    if a.new_password:
        # 换口令：这个组在仓库里的每个 Skill 都得用新口令重新加密，不然一部分新口令、一部分旧口令
        want = {n for n, s in locked.items() if s.get("lock") in a.new_password}
        lacking = sorted(want - {d.name for d in dirs})
        if lacking:
            die(f"换 {'、'.join(a.new_password)} 组的口令，要把这个组的 Skill 一起发：还缺 {'、'.join(lacking)}")
    if not dirs:
        die(f"{src} 下没有 Skill（要有 <名字>/SKILL.md）")
    (repo / "skills").mkdir(parents=True, exist_ok=True)
    passwords = {}
    for d in dirs:
        name = d.name
        front = mf._frontmatter((d / "SKILL.md").read_text(encoding="utf-8"))
        version = mf._field(front, "version") or mf.UNVERSIONED + mf.content_id(sealed.skill_files(d))
        spec = locked.get(name)
        if not spec:
            dst = repo / "skills" / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(d, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
            ok(f"{name}  {version}   {DIM}明文 → skills/{RESET}")
            continue
        lock = spec["lock"]
        out = repo / "sealed" / f"{name}.pkg"
        if lock not in passwords:
            existing = next((p for p in sorted((repo / "sealed").glob("*.pkg"))
                             if sealed.header(p).get("lock") == lock), None) if (repo / "sealed").is_dir() else None
            passwords[lock] = _lock_password(lock, repo, existing, lock in (a.new_password or []))
        if out.exists() and lock not in (a.new_password or []):
            head = sealed.header(out)
            if head.get("version") == version and head.get("files") == sealed.skill_files(d):
                info(f"{name}  {version}   没变，加密包不重做（重做每次都会变，git 里平白多一条改动）")
                continue
        log = d / "CHANGELOG.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(sealed.pack(d, {lock: passwords[lock]}, {
            "name": name, "version": version, "lock": lock, "hint": spec.get("hint", ""),
            "summary": (mf._field(front, "description") or "")[:120],
            "changelog": log.read_text(encoding="utf-8") if log.exists() else ""}))
        plain = repo / "skills" / name
        if plain.exists():
            shutil.rmtree(plain)
            warn(f"{name}：仓库里原来的明文 skills/{name} 已删掉（要口令的 Skill 不放明文）")
        ok(f"{name}  {version}   {DIM}加密 → sealed/{name}.pkg（{lock} 组）{RESET}")
    doc, errors, warnings = mf.build(repo)
    for w in warnings:
        warn(w)
    if errors:
        die("manifest 生成不了：" + "；".join(errors))
    (repo / "manifest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ok(f"manifest.json 已更新（{len(doc['skills'])} 个 Skill）")
    info("检查无误后自己 git add / commit / push；明文目录别放进仓库")
    return 0


def cmd_status(a):
    cfg, state = load_config(), load_state()
    say(f"{BOLD}工具{RESET}  skillpm {__version__}   {DIM}{home()}{RESET}")
    if not cfg.get("repos"):
        warn("还没配 Skill 仓库，先跑 skillpm install")
    for name, repo in (cfg.get("repos") or {}).items():
        say(f"{BOLD}仓库{RESET}  {name}　{repo.get('ssh') or git_url(repo) or repo.get('http')}"
            f"   {DIM}{repo.get('mode', 'git')}{RESET}")
    fetched = {}
    if not a.offline and cfg.get("repos"):
        try:
            fetched = fetch_all(cfg, quiet=True)
        except Abort:
            warn("没连上仓库，只显示本地情况")
    root = lockfile.find_root()
    lock = lockfile.load(root)
    if lock.get("skills"):
        say(f"{BOLD}锁文件{RESET}  {lockfile.path_of(root)}　{DIM}{len(lock['skills'])} 个 Skill{RESET}")
    want = None
    if getattr(a, "project", False):
        want = "project"
    elif getattr(a, "global_", False):
        want = "global"
    for key, entry in (state.get("hosts") or {}).items():
        scope = entry.get("scope", "global")
        if want and scope != want:
            continue
        if scope == "project" and str(root) not in key:
            continue                      # 别的项目的项目级安装，不在这儿列
        host = key.split(":")[-1]
        tag = f"{BLUE}项目级{RESET}" if scope == "project" else f"{DIM}用户级{RESET}"
        say()
        say(f"{BOLD}{host}{RESET}  {tag}  {PATH_C}{entry['path']}{RESET}")
        if not entry.get("skills"):
            info("（空）")
        for name, rec in sorted(entry["skills"].items()):
            diff = local_changes(entry["path"], name, rec)
            if diff is None:
                note = f"{RED}目录不在了{RESET}"
            elif diff["changed"] or diff["missing"]:
                n = len(diff["changed"]) + len(diff["missing"])
                note = f"{YELLOW}本地已修改（{n} 个文件）{RESET}"
            elif (src_meta := source_of(fetched, name, rec)[0]) and src_meta[2]["version"] != rec["version"]:
                note = f"{BLUE}可更新 → {src_meta[2]['version']}{RESET}"
            else:
                note = f"{GREEN}最新{RESET}"
            src = f"   {DIM}{rec['repo']}{RESET}" if rec.get("repo") else ""
            tier = (f"   {BOLD}权限：{rec['tier']}{RESET}" if rec.get("tier") else
                    f"   {BOLD}口令组：{rec['lock']}{RESET}" if rec.get("lock") else "")
            say(f"  {name:<32} {rec['version']:<9} {note}{tier}{src}")
    if not state.get("hosts"):
        warn("还没装到任何宿主")
    elif fetched and want != "project":
        show_not_installed(fetched, state)
    return 0


def cmd_uninstall(a):
    state = load_state()
    if not state.get("hosts"):
        die("本地没有安装记录")

    want = (a.host or "").lower().replace(" ", "-")
    have_hosts = sorted({k.split(":")[-1] for k in state["hosts"]})
    if want and not any(h.lower().replace(" ", "-") == want for h in have_hosts):
        die(f"没有叫「{a.host}」的宿主", f"本机装过的宿主：{'、'.join(have_hosts)}")

    # 没点名、也没说全部 → 列出来让你选，别让「一条不写就删光」这种事发生
    if not a.only and not getattr(a, "all", False):
        pool = []
        for key, entry in state["hosts"].items():
            host = key.split(":")[-1]
            if want and host.lower().replace(" ", "-") != want:
                continue
            for name, rec in sorted(entry.get("skills", {}).items()):
                pool.append((name, host, rec.get("version", "?")))
        if not pool:
            die("没有匹配到要卸载的东西", f"本机装过的宿主：{'、'.join(have_hosts)}")
        say()
        say(f"{BOLD}要移除哪些？{RESET}")
        multi_host = len({h for _, h, _ in pool}) > 1
        opts = [(n, f"{v}" + (f"　{h}" if multi_host else "")) for n, h, v in pool]
        # 默认一个都不选、也不给「a＝全部」：删是危险动作，一个键删光不行
        picked = {n for n, _ in choose("", opts, preselect=[], allow_all=False)}
        if not picked:
            say("没选，什么都没动。")
            return 0
        a.only = sorted(picked)

    targets = []
    managed = set()
    for key, entry in state["hosts"].items():
        if want and key.split(":")[-1].lower().replace(" ", "-") != want:
            continue
        for name in list(entry.get("skills", {})):
            managed.add(name)
            if a.only and name not in a.only:
                continue
            targets.append((key, entry["path"], name))
    if not targets:
        asked = [n for n in (a.only or [])]
        unknown = [n for n in asked if n not in managed]
        if unknown:
            # 最常见的情况：那个 Skill 本来就不是本工具装的（装的时候冲突跳过了）
            die(f"{'、'.join(unknown)} 不是本工具装的，没法卸",
                (f"本工具在{a.host or '各宿主'}装的是：{'、'.join(sorted(managed))}"
                 if managed else
                 f"本工具在{a.host or '各宿主'}一个都没装成——大概率是装的时候冲突跳过了，"
                 "跑 skillpm status 看看") +
                "。别人放的 Skill 请自己删目录，本工具不碰。")
        die("没有匹配到要卸载的东西", f"本机装过的宿主：{'、'.join(have_hosts)}")

    say(f"{BOLD}要移除这些（只动本工具装的，别人放的不碰）{RESET}")
    wn = max(_cols(n) for _k, _p, n in targets)
    wh = max(_cols(k.split(":")[-1]) for k, _p, _n in targets)
    for key, path, name in targets:
        host = key.split(":")[-1]
        say(f"  {BLUE}{name}{RESET}{' ' * (wn - _cols(name))}  {DIM}{host}{RESET}{' ' * (wh - _cols(host))}"
            f"  {PATH_C}{Path(path) / name}{RESET}")
    if not (a.yes or confirm(f"确认移除这 {len(targets)} 项？", default=False)):
        say("没动。")
        return 0

    touched = set()
    for key, path, name in targets:
        shutil.rmtree(Path(path) / name, ignore_errors=True)
        state["hosts"][key]["skills"].pop(name, None)
        ok(f"{key.split(':')[-1]}  {name} 已移除")
        touched.add((key, path))
    save_state(state)
    # 索引里还留着已经删掉的条目会误导人，顺手刷新
    for key, path in touched:
        entry = state["hosts"].get(key, {})
        entries = [{"name": n, "version": r.get("version", "?"), "repo": r.get("repo"), "summary": ""}
                   for n, r in entry.get("skills", {}).items()]
        scope = entry.get("scope", "global")
        if entries:
            index.write(path, entries, scope)
        else:
            f = Path(path) / "AGENTS.md"     # 一个都不剩了，把生成块清掉
            if f.exists():
                text = re.sub(index.BLOCK_RE, "", f.read_text(encoding="utf-8")).strip()
                f.write_text(text + "\n", encoding="utf-8") if text else f.unlink()
    return 0


def _split_url(r, url):
    """repo add 后面直接写的地址 → 填进 ssh 或 http+path。"""
    from urllib.parse import urlparse
    url = url.strip()
    if url.startswith(("git@", "ssh://")):
        r["ssh"] = url
        return
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        die(f"看不懂这个地址：{url}",
            "要写成 http(s)://主机/组/仓库.git 或 git@主机:组/仓库.git")
    path = u.path.strip("/")
    path = path[:-4] if path.endswith(".git") else path
    if path.count("/") < 1:
        die(f"地址里缺项目路径：{url}", "要写到仓库这一层，比如 http://gitlab.example.com/组/仓库.git")
    r["http"] = f"{u.scheme}://{u.netloc}"
    r["path"] = path


def cmd_manifest(a):
    from skillpm import manifest
    root = Path(a.root).expanduser().resolve()
    if a.check and not (root / "manifest.json").exists():
        # 没有 manifest.json 也行（装的时候按 skills/ 现算），那就只查「别人能不能装」
        doc, errors, warnings = manifest.build(root)
        for w in warnings:
            warn(f"  {w}")
        if errors:
            say(f"{RED}✗{RESET} 这些 Skill 别人装不上：")
            for e in errors:
                say(f"    {e}")
            return 1
        ok(f"{len(doc['skills'])} 个 Skill 都合格（没有 manifest.json，也不需要——装的时候按 skills/ 算）")
        return 0
    if a.check:
        diff = manifest.stale(root)
        if not diff:
            ok(f"{root / 'manifest.json'} 是最新的")
            return 0
        say(f"{RED}✗{RESET} manifest.json 和 skills/ 对不上：")
        for d in diff:
            say(f"    {d}")
        info("在仓库根目录跑 skillpm manifest 重新生成，再提交")
        return 1
    doc, errors, warnings = manifest.build(root)
    for w in warnings:
        warn(f"  {w}")
    if errors:
        say(f"{RED}✗{RESET} 这些要先改，改完再生成：")
        for e in errors:
            say(f"    {e}")
        return 1
    out = root / "manifest.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ok(f"已生成 {out}：{len(doc['skills'])} 个 Skill")
    for name, s in doc["skills"].items():
        say(f"    {name:<32} {s['version']:<10} {len(s['files']):>3} 个文件")
    info("manifest.json 是可选的：不提交它，别人装的时候会直接按 skills/ 算。"
         "提交了的话，以后每次改 Skill 都要重新生成一次，否则别人看到的是旧版本号。")
    return 0


def cmd_repo(a):
    cfg = load_config()
    repos = cfg.setdefault("repos", {})
    if not a.action:
        show_examples("repo")
        say()
        a.action = "list"
    if a.action in ("list", "remove") and a.url:
        die(f"repo {a.action} 后面只要一个仓库名，多写了：{a.url}")
    if a.action == "list":
        if not repos:
            warn("一个仓库都没配")
            return 0
        state = load_state()
        # 本机装了几个来自这个仓库的——只看地址看不出「我到底在用哪个库」
        installed = {}
        for entry in (state.get("hosts") or {}).values():
            for rec in (entry.get("skills") or {}).values():
                if rec.get("repo"):
                    installed.setdefault(rec["repo"], set()).add(rec.get("host", "?"))
        counts = {}
        for entry in (state.get("hosts") or {}).values():
            for name, rec in (entry.get("skills") or {}).items():
                counts.setdefault(rec.get("repo"), set()).add(name)
        for name, r in repos.items():
            say(f"{BOLD}{name}{RESET}")
            say(f"  地址：{r.get('ssh') or git_url(r) or r.get('http') or '（没填）'}")
            say(f"  分支：{r.get('branch', 'main')}　方式：{r.get('mode', 'git')}"
                + ("　已配令牌（输出里一律打码）" if r.get("token") else "　没配令牌"))
            cache = cache_dir(name)
            if cache.is_dir():
                try:
                    man = manifest_of(cache, name) or {}
                except Abort:
                    man = {}          # 缓存里一个能装的都没有：这一行写 0 个，别让整张表报错
                total = len(man.get("skills") or {})
                commit = (repo_commit(cache) or "")[:8]
                say(f"  缓存：{cache}"
                    + (f"　{DIM}commit {commit}{RESET}" if commit else ""))
                say(f"  里面有 {total} 个 Skill"
                    + (f"，本机装了 {len(counts.get(name, ()))} 个"
                       f"（{'、'.join(sorted(installed.get(name, ())))}）"
                       if counts.get(name) else "，本机一个都没装"))
            else:
                say(f"  缓存：{DIM}还没拉过{RESET}")
            say()
        info("看每个宿主装了哪些：skillpm status；只装某个仓库的：skillpm install --repo <名字>")
        return 0
    if a.action == "remove":
        if a.name not in repos:
            die(f"没有叫 {a.name} 的仓库")
        if not (a.yes or confirm(f"移除仓库 {a.name}？（已装的 Skill 不会被删）", default=False)):
            return 0
        repos.pop(a.name)
        shutil.rmtree(cache_dir(a.name), ignore_errors=True)
        save_config(cfg)
        ok(f"{a.name} 已移除")
        return 0
    old = repos.get(a.name)
    r = dict(old or {})
    if a.url:
        _split_url(r, a.url)
    if a.ssh:
        r["ssh"] = a.ssh
        host, path = parse_ssh(a.ssh)
        if host:
            r.setdefault("http", f"http://{host}")
            r["path"] = path
    for key, val in (("http", a.http), ("path", a.path), ("token", a.token), ("branch", a.branch)):
        if val:
            r[key] = val
    r.setdefault("branch", "main")
    # 能 git clone 就 git clone——ssh 地址、或者公开仓库的 http 地址都算
    r["mode"] = "git" if (has_git() and git_url(r) and not a.http_only) else "http"
    if not r.get("ssh") and not r.get("http"):
        say(f"{RED}✗{RESET} 没给仓库地址")
        show_examples("repo")
        return 2
    if r.get("mode") == "http" and not r.get("token"):
        die("不用 git 下载压缩包的方式要令牌", "加上 --token <令牌>；或者装个 git，公开仓库就不用令牌")
    if r.get("token"):
        remember_secret(r["token"])
    shown = r.get("ssh") or git_url(r) or r.get("http")
    if not a.no_check:
        # 加之前先拉一次：地址错、没权限、缺 manifest 当场就知道，别等到 install 才发现
        info(f"先试拉一次 {shown} …")
        try:
            d = fetch(a.name, r, quiet=True)
            man = manifest_of(d, a.name)
        except Abort as e:
            if old is None:
                shutil.rmtree(cache_dir(a.name), ignore_errors=True)
            raise Abort(f"{e}\n  → 仓库 {a.name} 没有保存，改好再加一次", e.hint)
        names = sorted((man.get("skills") or {}))
        ok(f"拉得到，里面有 {len(names)} 个 Skill：{'、'.join(names[:6])}"
           + (f" 等" if len(names) > 6 else ""))
        if man.get("computed"):
            info("仓库里没有 manifest.json，按 skills/ 目录算的（这样就行，不用非得生成）")
    repos[a.name] = r
    save_config(cfg)
    ok(f"仓库 {a.name} 已{'更新' if old else '记下'}：{shown}（{'git' if r['mode'] == 'git' else '下载压缩包'}）")
    info(f"装它的 Skill：skillpm install --repo {a.name}")
    return 0


def cmd_host(a):
    if not a.action:
        show_examples("host")
        say()
        a.action = "list"
    cfg = load_config()
    hosts = cfg.setdefault("hosts", {})
    if a.action == "list":
        state = load_state()
        pool = known_hosts(cfg, state)
        # 每个宿主装了几个——「配了但一个都没装」和「装了 8 个」是两回事
        counted = {}
        for key, entry in (state.get("hosts") or {}).items():
            if entry.get("scope") == "global":
                counted[key.split(":")[-1]] = len(entry.get("skills") or {})
        say(f"{BOLD}已配置{RESET}")
        for n, path in sorted(pool.items()):
            note = ""
            if not Path(path).is_dir():
                note = f"   {RED}目录不存在{RESET}"
            elif n in counted:
                note = f"   {GREEN}装了 {counted[n]} 个{RESET}"
            else:
                note = f"   {DIM}还没装东西{RESET}"
            recovered = f"   {YELLOW}（装过，但配置里丢了）{RESET}" if n not in hosts else ""
            say(f"  {n:<18} {path}{note}{recovered}")
        if not pool:
            info("（空）")
        if any(n not in hosts for n in pool):
            say()
            warn("上面标黄的宿主装过 Skill，但不在配置里——1.9.0 之前的 install 会覆盖宿主表")
            info("下次 skillpm install 保存时会自动并回去，不用手动处理")
        say()
        say(f"{BOLD}本机探测到、还没配的{RESET}")
        rest = {n: p for n, p in detect().items() if n not in pool}
        for n, path in rest.items():
            say(f"  {n:<18} {path}   {DIM}{confidence(n)}{RESET}")
        if not rest:
            info("（没有）")
        say()
        info(f"目录表里认识 {len(CATALOG)} 种宿主；不在表里的，只要是「家目录的隐藏文件夹下有 skills」"
             f"也会自动发现；再不行用 skillpm host add <名字> <路径> 自己加")
        info("想看每个宿主里具体装了哪些 Skill、什么版本：skillpm status")
        return 0
    if a.action == "remove":
        if a.name not in hosts:
            die(f"没有叫 {a.name} 的宿主")
        hosts.pop(a.name)
        save_config(cfg)
        ok(f"{a.name} 已从配置里移除（已装的 Skill 不会被删）")
        return 0
    path = Path(a.path).expanduser()
    if not path.is_dir() and not confirm(f"{path} 现在不存在，还是要加吗？", default=False):
        return 0
    hosts[a.name] = str(path)
    save_config(cfg)
    ok(f"宿主 {a.name} → {path}")
    return 0


def cmd_sync(a):
    """重新生成各宿主目录下的 AGENTS.md 索引，不动 Skill 本身。"""
    cfg, state = load_config(), load_state()
    fetched = {}
    try:
        fetched = fetch_all(cfg, quiet=True)
    except Abort:
        warn("没连上仓库，说明文字可能不全，但索引照样生成")
    root = lockfile.find_root()
    n = 0
    for key, entry in (state.get("hosts") or {}).items():
        scope = entry.get("scope", "global")
        if scope == "project" and str(root) not in key:
            continue
        entries = []
        for name, rec in entry.get("skills", {}).items():
            meta = source_of(fetched, name, rec)[0]
            entries.append({"name": name, "version": rec.get("version", "?"),
                            "repo": rec.get("repo"),
                            "summary": (meta[2].get("summary", "") if meta else "")})
        if not entries:
            continue
        p = index.write(entry["path"], entries, scope)
        ok(f"{key.split(':')[-1]}　{p}　{len(entries)} 个")
        n += 1
    if not n:
        warn("没有可写索引的宿主——先 skillpm install")
    return 0


def _manual_changed(src, old_head):
    """self-update 前后，随工具发的手册有没有变。"""
    from skillpm.manual import HTML
    from skillpm.repos import run_git
    try:
        return bool(run_git(["diff", "--name-only", old_head, "HEAD", "--", HTML], cwd=src).strip())
    except (RuntimeError, OSError):
        return False


def cmd_docs(a):
    """打开随工具一起发的图文手册（docs/使用手册.html）。"""
    from skillpm import manual
    p = manual.html_path()
    if not p.exists():
        die("这份 skillpm 里没带图文手册",
            "pip 装的不带 docs/；用安装脚本装的才有。也可以直接看仓库里的 docs/快速上手.md")
    if getattr(a, "path", False):
        say(str(p))
        return 0
    _p, opened = manual.open_manual()
    if opened:
        ok(f"已在浏览器里打开：{p}")
    else:
        warn("没能自动打开浏览器（可能是远程登录、没有图形界面）")
        info(f"手册在这：{p}　拷到有浏览器的电脑上双击就能看")
    return 0


def cmd_selfupdate(a):
    """更新工具自己。在哪个目录跑都行——它知道自己的源码在哪。"""
    here = Path(__file__).resolve().parents[2]
    if not (here / ".git").exists():
        die("工具不是从 git 工作副本跑的，没法自己更新",
            f"重新装一次：git clone {HOMEPAGE}.git "
            "~/.skillpm-src && ~/.skillpm-src/scripts/install.sh")
    from skillpm.repos import run_git
    say(f"源码：{PATH_C}{here}{RESET}")
    try:
        dirty = run_git(["status", "--porcelain"], cwd=here).strip()
    except (RuntimeError, OSError):
        dirty = ""
    if dirty:
        die("源码目录里有未提交的改动，先处理掉再更新",
            f"看一下改了什么：git -C {here} status")
    before = __version__
    try:
        old_head = run_git(["rev-parse", "HEAD"], cwd=here).strip()
    except (RuntimeError, OSError):
        old_head = ""
    try:
        run_git(["pull", "--ff-only"], cwd=here)
    except RuntimeError as e:
        die(f"更新失败：{e}", "网络或权限问题；手动试一下 git -C %s pull" % here)
    m = re.search(r'__version__ = "([^"]+)"',
                  (here / "src" / "skillpm" / "__init__.py").read_text(encoding="utf-8"))
    after = m.group(1) if m else "?"
    if after == before:
        ok(f"已经是最新的（{before}）")
        return 0
    ok(f"工具已更新：{before} → {BOLD}{after}{RESET}")
    log = here / "CHANGELOG.md"
    if log.exists():
        for line in sections_since(log.read_text(encoding="utf-8"), before).splitlines():
            say(f"  {md_line(line)}" if line.strip() else "")
    if old_head and _manual_changed(here, old_head):
        say()
        from skillpm.manual import browser_url
        ok("使用手册也更新了：复制下面这行到浏览器地址栏就能打开")
        say(f"  {BOLD}{RED}{browser_url(here)}{RESET}")
    # 启动器是直接指向源码的，pull 完就生效；pip 装的才需要重装
    launcher = home() / ".installed-at"
    if not launcher.exists():
        say()
        info(f"如果你是用 pip 装的，重新装一次让入口指向新版本：")
        say(f"  {here}/scripts/install.sh")
    return 0


# ── 首次引导 ──────────────────────────────────────────────────────────────

def onboarding(cfg):
    """第一次用：配一个 Skill 仓库（地址 → 名字 → 试拉），再看本机有哪些 Agent。

    和 repo add 走同一套：地址自动认 http / git@，当场试拉，拉不到就说清楚原因、让你重填。
    以前分四步问（名字、地址、SSH key 配没配、令牌），名字在前、不试拉，地址错了要到 install 才发现。
    """
    say()
    say(f"{BOLD}skillpm {__version__}{RESET}  {DIM}AI Skill 的安装与版本管理{RESET}")
    info("第一次用，配一下 Skill 从哪来。有默认值的直接回车。")

    say()
    say(f"{BOLD}1/2　Skill 仓库{RESET}")
    info("填你们团队放 Skill 的 git 仓库地址：http(s)://…/组/仓库.git 或 git@主机:组/仓库.git")
    info("公开仓库直接能拉；私有仓库待会儿会问你要访问令牌。")
    while True:
        addr = ask("  仓库地址")
        repo = {"branch": "main", "token": ""}
        try:
            _split_url(repo, addr)
        except Abort as e:
            say(f"  {RED}✗{RESET} {e}")
            if e.hint:
                info(f"  {e.hint}")
            continue
        # 默认名取地址里的「组」——组一般就是团队（ops/skills → ops）
        default_name = (repo.get("path") or parse_ssh(addr)[1] or "我的仓库").strip("/").split("/")[0]
        info("给它起个名字，以后 --repo 用它指这个仓库（建议用团队名）")
        name = ask("  仓库名", default_name)
        repo["mode"] = "git" if has_git() else "http"
        if repo["mode"] == "http":
            warn("  本机没有 git，改成下载压缩包，这种方式要访问令牌")
            info("  GitLab → 头像 → Preferences → Access Tokens，勾 read_repository")
            repo["token"] = ask("  访问令牌（输入不回显）", secret=True)
        while True:
            info(f"  先试拉一次 {repo.get('ssh') or git_url(repo) or addr} …")
            try:
                man = manifest_of(fetch(name, repo, quiet=True), name)
                break
            except Abort as e:
                say(f"  {RED}✗{RESET} {e}")
                if "要求登录" in str(e) and not repo.get("ssh") and not repo.get("token"):
                    info("  私有仓库要访问令牌：GitLab → 头像 → Preferences → Access Tokens，勾 read_repository")
                    tok = ask("  访问令牌（输入不回显；直接回车＝重填地址）", default="", secret=True)
                    if tok:
                        repo["token"] = tok
                        continue
                elif e.hint:
                    info(f"  {e.hint}")
                shutil.rmtree(cache_dir(name), ignore_errors=True)
                man = None
                break
        if man is not None:
            break
        say()
        info("换个地址再试（Ctrl+C 退出；以后也可以用 skillpm repo add 再配）")
    skills = sorted(man.get("skills") or {})
    ok(f"拉得到，里面有 {len(skills)} 个 Skill：{'、'.join(skills[:6])}{' 等' if len(skills) > 6 else ''}")
    if repo.get("token"):
        remember_secret(repo["token"])
        info(f"  令牌只存在 {config_path()}，权限 600，不会打印到屏幕或日志里")
    cfg.setdefault("repos", {})[name] = repo

    say()
    say(f"{BOLD}2/2　装到哪{RESET}")
    found = detect()
    if found:
        for n, p in found.items():
            if not describe(n):
                ok(f"找到 {n}：{p}")
            else:
                warn(f"找到 {n}：{p}　（{describe(n)}，装之前确认一下）")
        info("下一步会让你勾选装到哪几个。")
    else:
        warn("  没自动找到宿主，下一步会让你手填路径（填一次就记住）")
    save_config(cfg)
    say()
    ok(f"配置存好了：{config_path()}")
    info("以后加别的 Skill 仓库：skillpm repo add <名字> <地址>")
    return cfg


# ── 参数 ──────────────────────────────────────────────────────────────────

# 顶层帮助按「谁在什么时候用」分组。新加命令记得归进来——漏了会落到「其他」，测试会报。
HELP_GROUPS = [
    ("日常", [("install", "装 Skill（第一次会引导你配好仓库）"),
              ("update", "跟上最新，并告诉你每个 Skill 改了什么"),
              ("status", "看装了什么、什么版本、有没有被改过、能不能更新"),
              ("uninstall", "删 Skill（不写名字会列出来让你挑）"),
              ("check", "只看有没有新版本，什么都不动"),
              ("ignore", "仓库里某个 Skill 不想装，不再提示安装它"),
              ("docs", "在浏览器里打开图文使用手册")]),
    ("配置", [("repo", "Skill 仓库：加 / 看 / 删，可以配多个"),
              ("host", "Agent 目录：加 / 看 / 删，一般自动探到")]),
    ("维护", [("manifest", "检查自己的 Skill 仓库是否合格（可选：生成 manifest.json）"),
              ("freeze", "导出锁文件，让全组装到完全一样的版本"),
              ("sync", "重新生成各 Agent 目录下的 AGENTS.md 索引"),
              ("self-update", "更新 skillpm 工具本身"),
              ("publish", "发版：要口令的 Skill 加密进仓库，其余照常放（维护仓库的人用）")]),
]

EPILOG_ROWS = [
    ("skillpm install", "第一次用：配仓库、选 Agent、选 Skill"),
    ("skillpm update", "跟上最新"),
    ("skillpm repo add 运维组 <仓库地址>", "加一个别的仓库（名字自己起，建议用团队名）"),
    ("skillpm install --repo 运维组", "只装这个仓库里的"),
]
EPILOG = None   # 顶层帮助的尾巴在 Parser.format_help 里按显示宽度排，中文才对得齐


# argparse 自己的提示是英文（usage、the following arguments are required…），
# 它内部统一走模块级的 _() 取文案，把那个函数换掉就能整体中文化。
# 3.9 和 3.12 的原文不完全一样，两套都列上。
_ZH = {
    "usage: ": "用法：",
    "positional arguments": "参数",
    "optional arguments": "选项",
    "options": "选项",
    "show this help message and exit": "显示这份帮助",
    "show program's version number and exit": "显示版本号",
    "the following arguments are required: %s": "少了必填的：%s",
    "unrecognized arguments: %s": "不认识的参数：%s",
    "invalid choice: %(value)r (choose from %(choices)s)": "没有 %(value)r 这个选项，只能是：%(choices)s",
    "invalid choice: %(value)r": "没有 %(value)r 这个选项",
    "argument %(argument_name)s: %(message)s": "%(argument_name)s：%(message)s",
    "expected one argument": "后面要跟一个值",
    "expected at least one argument": "后面至少要跟一个值",
    "ambiguous option: %(option)s could match %(matches)s": "%(option)s 有歧义，可能是：%(matches)s",
    "not allowed with argument %s": "不能和 %s 一起用",
    "%(prog)s: error: %(message)s\n": "%(prog)s：%(message)s\n",
}
_orig_gettext = argparse._


def _zh(text):
    return _ZH.get(text, _orig_gettext(text))


argparse._ = _zh

# 报错时顺手给这个命令最常用的几种写法——光说「少了什么」还是不知道该怎么写
EXAMPLES = {
    "repo": [
        ("看配了哪些仓库", "skillpm repo list"),
        ("加一个仓库（名字自己起，建议用团队名）", "skillpm repo add 我们团队 http://gitlab.example.com/组/仓库.git"),
        ("走 SSH", "skillpm repo add 我们团队 git@gitlab.example.com:组/仓库.git"),
        ("私有仓库带令牌", "skillpm repo add 我们团队 http://gitlab.example.com/组/仓库.git --token <令牌>"),
        ("删掉（已装的 Skill 不动）", "skillpm repo remove 我们团队"),
    ],
    "host": [
        ("看配了哪些宿主", "skillpm host list"),
        ("手动加一个", "skillpm host add 我的工具 ~/.mytool/skills"),
        ("删掉（只删配置）", "skillpm host remove 我的工具"),
    ],
    "install": [
        ("问你装哪些、装到哪", "skillpm install"),
        ("全装", "skillpm install --all"),
        ("只装某几个", "skillpm install code-review pdf-tools"),
        ("只装某个仓库的", "skillpm install --repo 我们团队"),
    ],
    "uninstall": [
        ("列出来让你选", "skillpm uninstall"),
        ("卸某几个", "skillpm uninstall code-review"),
    ],
    "manifest": [
        ("生成 manifest.json（可选）", "skillpm manifest"),
        ("指定仓库目录", "skillpm manifest ~/code/我们的skill仓库"),
        ("只检查仓库合不合格（CI 用）", "skillpm manifest --check"),
    ],
}


def _cols(text):
    """终端里占几列：中文全角占 2 列。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def show_examples(cmd):
    rows = EXAMPLES.get(cmd)
    if not rows:
        return
    say(f"  {BOLD}常用写法{RESET}")
    width = max(_cols(d) for d, _ in rows)
    for desc, line in rows:
        say(f"    {desc}{' ' * (width - _cols(desc))}  {line}")


def examples_text(cmd):
    """-h 末尾的「常用写法」，和报错时列的是同一份、同一种排版。"""
    rows = EXAMPLES.get(cmd) or []
    width = max((_cols(d) for d, _ in rows), default=0)
    return "常用写法：\n" + "\n".join(f"  {d}{' ' * (width - _cols(d))}  {l}" for d, l in rows)


# 位置参数在报错里的叫法（argparse 会说 argument action，看不懂）
_ARG_LABEL = {"action": "要做什么", "add|list|remove": "要做什么",
              "name": "名字", "path": "路径", "url": "地址"}


class ZhFormatter(argparse.RawDescriptionHelpFormatter):
    """帮助的左列按「显示宽度」对齐：中文占两列，argparse 原版按字符数算，中文参数名后面会错位。"""

    def add_argument(self, action):
        if action.help is not argparse.SUPPRESS:
            inv = [self._format_action_invocation(action)]
            inv += [self._format_action_invocation(s) for s in self._iter_indented_subactions(action)]
            self._action_max_length = max(self._action_max_length,
                                          max(_cols(x) for x in inv) + self._current_indent)
            self._add_item(self._format_action, [action])

    def _format_action(self, action):
        help_position = min(self._action_max_length + 2, self._max_help_position)
        help_width = max(self._width - help_position, 11)
        action_width = help_position - self._current_indent - 2
        header = self._format_action_invocation(action)
        indent_first = 0
        if not action.help:
            header = " " * self._current_indent + header + "\n"
        elif _cols(header) <= action_width:
            header = " " * self._current_indent + header + " " * (action_width - _cols(header)) + "  "
        else:
            header = " " * self._current_indent + header + "\n"
            indent_first = help_position
        parts = [header]
        if action.help and action.help.strip():
            lines = self._split_lines(self._expand_help(action), help_width)
            parts.append(" " * indent_first + lines[0] + "\n")
            parts += [" " * help_position + ln + "\n" for ln in lines[1:]]
        elif not header.endswith("\n"):
            parts.append("\n")
        parts += [self._format_action(s) for s in self._iter_indented_subactions(action)]
        return self._join_parts(parts)


class Parser(argparse.ArgumentParser):
    """argparse 默认的报错是英文、只说一句「少了什么」。
    这里统一成中文，并且：
      · 拼错了参数 → 猜你想写的是哪个
      · 少了必填的 / 选项写错 → 列出这个命令的常用写法
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", ZhFormatter)
        super().__init__(*args, **kwargs)

    def format_help(self):
        # 只接管顶层（skillpm -h）；子命令的 -h 还是 argparse 自己排
        if " " in self.prog or not self._subparsers:
            return super().format_help()
        names = self._sub_names()
        grouped = [n for _g, rows in HELP_GROUPS for n, _d in rows]
        rest = sorted(n for n in names if n not in grouped)
        groups = HELP_GROUPS + ([("其他", [(n, "") for n in rest])] if rest else [])
        width = max(_cols(n) for n in names) + 2
        out = [f"用法：{self.prog} <命令> [参数]　　　{self.prog} <命令> -h 看这条命令的全部参数", "",
               f"{self.description}", ""]
        for title, rows in groups:
            out.append(title)
            out += [f"  {n}{' ' * (width - _cols(n))}{d}" for n, d in rows if n in names]
            out.append("")
        w2 = max(_cols(c) for c, _d in EPILOG_ROWS) + 2
        out += ["选项", "  -h, --help     显示这份帮助", "  -v, --version  显示版本号", "", "常用写法"]
        out += [f"  {c}{' ' * (w2 - _cols(c))}{d}" for c, d in EPILOG_ROWS]
        from skillpm.manual import browser_url, open_command
        where = str(home()) + "\\" if sys.platform.startswith("win") else "~/.skillpm/"   # Windows 上 ~ 没意义
        # 手册入口是新人最该看到的一行，命令用加粗正红（和「要装：…」一样，照着敲的都这么标）
        # 给绝对地址：复制到浏览器地址栏就能开，不用先弄明白 ~ 是哪、也不用会敲命令
        out += ["", f"{BOLD}图文使用手册（HTML）{RESET}：复制下面这行到浏览器地址栏就能打开，快速上手在第一页",
                f"  {BOLD}{RED}{browser_url()}{RESET}",
                f"  也可以直接敲 {BOLD}skillpm docs{RESET}，或者在终端里跑：{open_command()}",
                f"配置和状态放在 {where}（改位置用环境变量 SKILLPM_HOME）。"]
        return "\n".join(out).rstrip() + "\n"

    def error(self, message):
        import difflib
        cmd = self.prog.split()[-1] if " " in self.prog else getattr(self, "sub_cmd", None)
        if cmd not in EXAMPLES and " " not in self.prog and cmd not in self._sub_names():
            cmd = None                                   # 连命令都写错了，别拼出 skillpm frob -h
        # 3.9 的 ArgumentError 把「argument xxx: 」写死了，不走翻译，这里再换一次
        message = re.sub(r"^argument (\S+?)[:：] ?",
                         lambda mm: f"{_ARG_LABEL.get(mm.group(1), mm.group(1))}：", message)
        m = re.search(r"(?:unrecognized arguments|不认识的参数)[:：] ?(\S+)", message)
        if m and m.group(1).startswith("-"):
            bad = m.group(1)
            known = [o for act in self._actions for o in act.option_strings]
            for sub_act in self._subparsers._group_actions if self._subparsers else []:
                for name, sp in getattr(sub_act, "choices", {}).items():
                    known += [o for act in sp._actions for o in act.option_strings]
            near = difflib.get_close_matches(bad, sorted(set(known)), n=2, cutoff=0.5)
            say(f"{RED}✗{RESET} 没有 {BOLD}{bad}{RESET} 这个参数")
            if near:
                say(f"  是不是想写 {BOLD}{'  或  '.join(near)}{RESET}？")
        else:
            say(f"{RED}✗{RESET} {message}")
            # 命令、动作写错了：从「只能是」里挑最像的
            m2 = re.search(r"没有 '([^']+)' 这个选项，只能是：(.+)$", message)
            if m2:
                near = difflib.get_close_matches(m2.group(1), re.findall(r"'([^']+)'", m2.group(2)),
                                                 n=2, cutoff=0.4)
                if near:
                    say(f"  是不是想写 {BOLD}{'  或  '.join(near)}{RESET}？")
        if cmd in EXAMPLES:
            show_examples(cmd)
        prog = self.prog if " " in self.prog or not cmd else f"{self.prog} {cmd}"
        if " " not in self.prog and cmd not in self._sub_names():
            prog = self.prog
        say(f"  看全部用法：{BOLD}{prog} -h{RESET}")
        self.exit(2)

    def _sub_names(self):
        names = set()
        for act in (self._subparsers._group_actions if self._subparsers else []):
            names |= set(getattr(act, "choices", {}) or {})
        return names


def build_parser():
    ap = Parser(
        prog="skillpm", description="AI Skill 的安装与版本管理",
        epilog=EPILOG, formatter_class=ZhFormatter)
    ap.add_argument("-v", "-V", "--version", action="version", version=f"skillpm {__version__}",
                    help="显示版本号")
    sub = ap.add_subparsers(dest="cmd", metavar="命令")

    p = sub.add_parser("install", help="安装 Skill（默认装到用户级，对所有项目生效）")
    p.add_argument("specs", nargs="*", metavar="SKILL",
                   help="要装的 Skill 名，或安装源（owner/repo/skill、git 地址、team://库/名、本地路径）")
    p.add_argument("-p", "--project", action="store_true",
                   help="只装到当前项目（仅编程类 Agent 支持），版本写进锁文件随项目提交")
    p.add_argument("-g", "--global", dest="global_", action="store_true",
                   help="装到用户级目录（默认行为，写不写都一样）")
    p.add_argument("--only", nargs="*", metavar="SKILL", help="只装这几个")
    p.add_argument("--repo", metavar="名字", help="只装这个仓库里的")
    p.add_argument("--all", action="store_true", help="全装，不问")
    p.add_argument("--force", action="store_true", help="有冲突也覆盖")
    p.add_argument("-a", "--agent", metavar="宿主", help="只装到这个宿主（如 claude-code、cursor）")
    p.add_argument("--hosts", nargs="*", metavar="宿主", help="装到这几个宿主，跳过询问")
    p.add_argument("-d", "--dir", metavar="目录", help="装到指定目录，不走宿主探测")
    p.add_argument("--from", dest="from_lock", metavar="锁文件",
                   help="按锁文件复现：每个 Skill 都切到它记的那个 commit")
    p.add_argument("--no-index", action="store_true", help="不生成 AGENTS.md 索引")
    p.add_argument("--reconfigure", action="store_true", help="重新走一遍引导")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("freeze", help="把当前装的版本导成锁文件，发给别人复现")
    p.add_argument("-o", "--out", metavar="文件", help="输出到哪，默认当前项目的 skillpm.lock")
    p.add_argument("--host", metavar="宿主", help="只导这个宿主装的")
    p.set_defaults(fn=cmd_freeze)

    p = sub.add_parser("check", help="只看有没有新版本，什么都不动")
    p.add_argument("--repo", metavar="名字", help="只看这个仓库来的")
    p.add_argument("-u", "--updatable-only", action="store_true", help="只列可更新的，没有就一句话")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("update", help="检查并更新")
    p.add_argument("--repo", metavar="名字", help="只更新来自这个仓库的 Skill")
    p.add_argument("--yes", action="store_true", help="不问直接更新")
    p.add_argument("--force", action="store_true", help="有冲突也覆盖")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("publish", help="发版：要口令的加密进 sealed/，其余复制到 skills/，重建 manifest")
    p.add_argument("source", help="明文 Skill 所在目录（下面是 <名字>/SKILL.md），或单个 Skill 目录")
    p.add_argument("--repo", required=True, help="Skill 仓库的本地目录（根目录有 skillpm.repo.json）")
    p.add_argument("--only", nargs="*", metavar="SKILL", help="只发这几个")
    p.add_argument("--new-password", nargs="*", metavar="口令组", help="换这些口令组的口令（组里的 Skill 要一起发）")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("status", help="看装了什么")
    p.add_argument("-p", "--project", action="store_true", help="只看当前项目级")
    p.add_argument("-g", "--global", dest="global_", action="store_true", help="只看用户级")
    p.add_argument("--offline", action="store_true", help="不连仓库，只看本地")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("ignore", help="不再提示安装某些 Skill（不写名字就列出忽略了哪些）")
    p.add_argument("names", nargs="*", metavar="SKILL", help="不想装、也不想被提示的 Skill 名，可以写多个")
    p.add_argument("--undo", action="store_true", help="恢复提示")
    p.set_defaults(fn=cmd_ignore)

    p = sub.add_parser("uninstall", help="移除 Skill（不写名字会列出来让你选）")
    p.add_argument("names", nargs="*", metavar="SKILL", help="要移除的 Skill 名，可以写多个")
    p.add_argument("--only", nargs="*", metavar="SKILL", help="同上，写不写都行")
    p.add_argument("--all", action="store_true", help="移除本工具装的全部")
    p.add_argument("--host", metavar="宿主", help="只动这个宿主（大小写随便写）")
    p.add_argument("--yes", action="store_true", help="不再确认")
    p.set_defaults(fn=cmd_uninstall)

    p = sub.add_parser("repo", help="管理 Skill 仓库（可以配多个，别的团队配自己的）",
                       epilog=examples_text("repo"),
                       formatter_class=ZhFormatter)
    p.add_argument("action", nargs="?", choices=["add", "list", "remove"], metavar="add|list|remove",
                   help="加 / 看 / 删；不写就是 list")
    p.add_argument("name", nargs="?", metavar="仓库名", help="自己起，以后 --repo 用它")
    p.add_argument("url", nargs="?", metavar="地址", help="http(s)://… 或 git@…，自动认")
    p.add_argument("--ssh", metavar="地址", help="SSH 地址（也可以直接写在仓库名后面）")
    p.add_argument("--http", metavar="地址", help="HTTP 地址（也可以直接写在仓库名后面）")
    p.add_argument("--path", metavar="组/项目", help="项目路径（地址里已经带了就不用写）")
    p.add_argument("--branch", metavar="分支", help="默认 main")
    p.add_argument("--token", metavar="令牌", help="访问令牌，私有仓库才要")
    p.add_argument("--http-only", action="store_true", help="不用 git，下载压缩包（要令牌）")
    p.add_argument("--no-check", action="store_true", help="加的时候不试拉（默认会试拉一次，确认能装）")
    p.add_argument("--yes", action="store_true", help="删的时候不再确认")
    p.set_defaults(fn=cmd_repo)

    p = sub.add_parser("manifest", help="给自己的 Skill 仓库生成 / 检查 manifest.json（可选，CI 把关用）",
                       epilog=examples_text("manifest"),
                       formatter_class=ZhFormatter)
    p.add_argument("root", nargs="?", default=".", metavar="仓库目录", help="默认当前目录")
    p.add_argument("--check", action="store_true",
                   help="只检查不写：每个 Skill 合不合格；有 manifest.json 的话再查它是不是最新（CI 用）")
    p.set_defaults(fn=cmd_manifest)

    p = sub.add_parser("host", help="管理宿主目录（各个 AI 工具放 Skill 的地方）",
                       epilog=examples_text("host"),
                       formatter_class=ZhFormatter)
    p.add_argument("action", nargs="?", choices=["add", "list", "remove"], metavar="add|list|remove",
                   help="加 / 看 / 删；不写就是 list")
    p.add_argument("name", nargs="?", metavar="宿主名")
    p.add_argument("path", nargs="?", metavar="目录", help="它的 skills 目录")
    p.set_defaults(fn=cmd_host)

    p = sub.add_parser("docs", help="在浏览器里打开图文使用手册")
    p.add_argument("--path", action="store_true", help="不打开，只打出文件路径")
    p.set_defaults(fn=cmd_docs)

    p = sub.add_parser("sync", help="重新生成各宿主目录下的 AGENTS.md 索引")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("self-update", help="更新工具本身")
    p.set_defaults(fn=cmd_selfupdate)
    return ap


def _resolve_install_specs(a):
    """位置参数写的安装源，折算成 --only 能认的名字。

    光名字、`仓库名:Skill名`、`team://仓库名/Skill名` 说的都是「已配仓库里的某个 Skill」，
    统一折成 `仓库名:名字`；GitHub / git 地址 / 本地路径还没接，当场说清楚。
    """
    known = tuple(load_config().get("repos") or {})
    wanted, external = [], []
    for spec in a.specs:
        try:
            src = parse_source(spec, known)
        except ValueError as e:
            die(str(e))
        if src.kind == "repo":
            wanted.append(f"{src.repo}:{src.name}" if src.repo else src.name)
        else:
            external.append(spec)
    if external:
        die(f"暂时还不支持直接从这种源安装：{'、'.join(external)}",
            "先把仓库加进来再装：skillpm repo add <名字> --ssh <地址>，"
            "然后 skillpm install <名字>:<Skill名>")
    a.only = (a.only or []) + wanted


def main(argv=None):
    ensure_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    # 单横线的 -help / -version 也认，省得有人打错了摸不着头脑
    argv = [{"-help": "--help", "-version": "--version"}.get(x, x) for x in argv]
    ap = build_parser()
    # 拼错的参数由顶层解析器报，它不知道你在用哪个子命令——告诉它，好给对应的例子
    ap.sub_cmd = next((x for x in argv if not x.startswith("-")), None)
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 0
    if a.cmd == "repo" and a.action in ("add", "remove") and not a.name:
        ap.error(f"repo {a.action} 后面要写仓库名")
    if a.cmd == "host" and a.action == "add" and not (a.name and a.path):
        ap.error("host add 要给宿主名和路径")
    if a.cmd == "host" and a.action == "remove" and not a.name:
        ap.error("host remove 要给宿主名")
    # 直接写名字和 --only 是一回事，别让人纠结该用哪个
    if a.cmd == "uninstall" and getattr(a, "names", None):
        a.only = (a.only or []) + a.names
    try:
        if a.cmd == "install" and getattr(a, "specs", None):
            _resolve_install_specs(a)
        return a.fn(a) or 0
    except Abort as e:
        say(f"{RED}✗{RESET} {e}")
        if e.hint:
            info(e.hint)
        return 1
    except KeyboardInterrupt:
        say()
        say("中断了，没做完的改动不会留下。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
