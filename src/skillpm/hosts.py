#!/usr/bin/env python3
"""常见 Agent 工具的 Skill / 指令目录候选。

说明一下可信度，免得把猜的当成确认的：
  verified  —— 在真实机器上见过这个目录，确认是放 Skill 的地方
  likely    —— 按该工具的公开约定推断，没有实地验证过
               （主要来源：skills 生态的公开对照表 github.com/vercel-labs/skills）
  auto      —— 不在表里，按「家目录的隐藏文件夹下有 skills 目录」自动发现的
探测只会提供**真实存在**的目录，所以猜错了也不会把东西装到奇怪的地方；
但 likely 的项如果指错了位置又恰好存在，就可能误导，所以装之前会让你确认。

宿主不在这张表里也没关系：`skillpm host add <名字> <路径>` 自己加，加完记在配置里。
"""

# name: (用户级候选路径, 项目级目录或 None, 可信度, 说明)
#
# **默认装用户级**：绝大多数 Agent 就是全局生效的，没有「项目」这个概念。
# 只有编程类 Agent（在仓库里干活的那些）才额外支持项目级目录——
# 这些才填第二项，其余一律 None，`install -p` 对它们直接报错而不是瞎建目录。
CATALOG = {
    # ── 本机实地见过 / 厂商文档写明（verified）──────────────────────────
    "Claude Code": (["~/.claude/skills"], ".claude/skills",
                    "verified", "Anthropic Claude Code"),
    "Codex": (["~/.codex/skills"], ".codex/skills",
              "verified", "OpenAI Codex"),
    "WorkBuddy": (["~/.workbuddy/skills",
                   "~/Library/Application Support/WorkBuddy/skills",
                   "%APPDATA%/WorkBuddy/skills", "%LOCALAPPDATA%/WorkBuddy/skills"],
                  None, "verified", "全局生效，没有项目级概念"),
    "WorkBuddy-AI": (["~/.workbuddy-ai/skills",
                      "~/Library/Application Support/WorkBuddy-AI/skills",
                      "%APPDATA%/WorkBuddy-AI/skills"],
                     None, "verified", "全局生效"),
    "Qoder": (["~/.qoder/skills"], ".qoder/skills",
              "verified", "阿里 Qoder；路径出自 Qoder 自带插件文档"),
    "Cursor": (["~/.cursor/skills"], ".cursor/skills",
               "verified", "本机见过 ~/.cursor/skills"),
    "Windsurf": (["~/.codeium/windsurf/skills"], ".windsurf/skills",
                 "verified", "本机见过；注意不是旁边的 memories（那是记忆，1.17 之前指错了）"),
    "Gemini CLI": (["~/.gemini/skills"], None, "verified", "Google Gemini CLI；本机见过"),
    "Antigravity": (["~/.gemini/antigravity/skills"], None,
                    "verified", "Google Antigravity；本机见过"),
    "Grok": (["~/.grok/skills"], ".grok/skills", "verified", "xAI Grok Build；本机见过"),
    "Agents": (["~/.agents/skills"], ".agents/skills",
               "verified", "多家共用的通用目录：Cline、Kimi Code CLI、Warp、Zed、Dexto 等读这里"),
    "Comate": (["~/.comate/skills"], ".comate/skills",
               "verified", "百度文心快码；百度官方文档写明"),

    # ── 国内（按 skills 生态的公开对照表；没实地验证，likely）───────────
    "Trae": (["~/.trae/skills"], ".trae/skills", "likely", "字节 Trae 国际版"),
    "Trae CN": (["~/.trae-cn/skills"], None, "likely", "字节 Trae 国内版"),
    "Qoder CN": (["~/.qoder-cn/skills"], None, "likely", "阿里 Qoder 国内版"),
    "Lingma": (["~/.lingma/skills"], ".lingma/skills", "likely", "阿里通义灵码"),
    "CodeBuddy": (["~/.codebuddy/skills"], ".codebuddy/skills", "likely", "腾讯 CodeBuddy"),
    "Qwen Code": (["~/.qwen/skills"], ".qwen/skills", "likely", "通义 Qwen Code"),
    "iFlow": (["~/.iflow/skills"], ".iflow/skills", "likely", "心流 iFlow CLI"),
    "CodeArts": (["~/.codeartsdoer/skills"], ".codeartsdoer/skills", "likely", "华为 CodeArts 代码智能体"),
    "MiniMax Code": (["~/.minimax/skills"], ".minimax/skills", "likely", "MiniMax"),
    "ZCode": (["~/.zcode/skills"], ".zcode/skills", "likely", "智谱 ZCode"),
    "JoyCode": (["~/.joycode/skills"], ".joycode/skills", "likely", "京东 JoyCode；只见过项目级 .joycode/，用户级按惯例推断"),
    "Codemaker": (["~/.codemaker/skills"], ".codemaker/skills", "likely", "网易 CodeMaker"),
    "Neovate": (["~/.neovate/skills"], ".neovate/skills", "likely", "Neovate Code"),

    # ── 国外（同上，likely）──────────────────────────────────────────
    "GitHub Copilot": (["~/.copilot/skills"], None, "likely", "GitHub Copilot"),
    "OpenCode": (["~/.config/opencode/skills"], ".opencode/skills", "likely", "OpenCode"),
    "Amp": (["~/.config/agents/skills"], None, "likely", "Amp、Replit 共用"),
    "Droid": (["~/.factory/skills"], None, "likely", "Factory Droid"),
    "Kiro": (["~/.kiro/skills"], ".kiro/skills", "likely", "AWS Kiro"),
    "Kilo Code": (["~/.kilo/skills"], None, "likely", "Kilo Code"),
    "Roo Code": (["~/.roo/skills"], ".roo/skills", "likely", "Roo Code"),
    "Continue": (["~/.continue/skills"], ".continue/skills", "likely", "Continue"),
    "Augment": (["~/.augment/skills"], ".augment/skills", "likely", "Augment"),
    "Junie": (["~/.junie/skills"], ".junie/skills", "likely", "JetBrains Junie"),
    "Goose": (["~/.config/goose/skills"], ".goose/skills", "likely", "Block Goose"),
    "Crush": (["~/.config/crush/skills"], ".crush/skills", "likely", "Charm Crush"),
    "OpenHands": (["~/.openhands/skills"], ".openhands/skills", "likely", "OpenHands"),
    "Mistral Vibe": (["~/.vibe/skills"], ".vibe/skills", "likely", "Mistral Vibe"),
    "Devin": (["~/.config/devin/skills"], ".devin/skills", "likely", "Devin for Terminal"),
    "Rovo Dev": (["~/.rovodev/skills"], ".rovodev/skills", "likely", "Atlassian Rovo Dev"),
    "Tabnine": (["~/.tabnine/agent/skills"], ".tabnine/agent/skills", "likely", "Tabnine CLI"),
    "Cortex Code": (["~/.snowflake/cortex/skills"], ".cortex/skills", "likely", "Snowflake Cortex Code"),
    "IBM Bob": (["~/.bob/skills"], ".bob/skills", "likely", "IBM Bob"),
    "Hermes Agent": (["~/.hermes/skills"], ".hermes/skills", "likely", "Hermes Agent"),
    "OpenClaw": (["~/.openclaw/skills"], None, "likely", "OpenClaw"),
    "Pi": (["~/.pi/agent/skills"], ".pi/skills", "likely", "Pi coding agent"),
    "AiderDesk": (["~/.aider-desk/skills"], ".aider-desk/skills", "likely", "AiderDesk"),
    "ForgeCode": (["~/.forge/skills"], ".forge/skills", "likely", "ForgeCode"),
    "Zencoder": (["~/.zencoder/skills"], ".zencoder/skills", "likely", "Zencoder / Zenflow"),
    "Firebender": (["~/.firebender/skills"], None, "likely", "Firebender"),
    "Deep Agents": (["~/.deepagents/agent/skills"], None, "likely", "LangChain Deep Agents"),
}

# 自动发现时跳过的隐藏目录：skillpm 自己的暂存区，不是宿主
AUTO_SKIP_PREFIX = ("skillpm",)

import os
from pathlib import Path


def expand(candidate):
    """展开 ~ 和 %VAR%；Windows 变量在本机没有就当这条候选作废。"""
    s = os.path.expandvars(str(candidate))
    if "%" in s:
        return None
    return Path(s).expanduser()


def project_dir(name):
    """该宿主的项目级目录（相对项目根）；不支持项目级的返回 None。"""
    return CATALOG.get(name, ([], None, "", ""))[1]


def supports_project(name):
    return bool(project_dir(name))


def project_capable():
    """哪些宿主支持项目级——只有编程类 Agent 才有。同一个项目目录只列一次。"""
    out, seen = [], set()
    for n in CATALOG:
        d = project_dir(n)
        if d and d not in seen:
            out.append(n)
            seen.add(d)
    return out


def detect_project(root="."):
    """扫出项目里已经存在的宿主目录，返回 {名字: 绝对路径}。"""
    from pathlib import Path as _P
    root = _P(root).resolve()
    found = {}
    for name, (_c, proj, _conf, _n) in CATALOG.items():
        if not proj:
            continue
        p = root / proj
        if p.is_dir() and str(p) not in found.values():   # 只认真实存在的；同一目录只算一次
            found[name] = str(p)
    return found


_AUTO = set()          # 本次 detect() 自动发现（不在目录表里）的宿主名


def confidence(name):
    if name in CATALOG:
        return CATALOG[name][2]
    return "auto" if name in _AUTO else "unknown"


def describe(name):
    """给人看的可信度说明；verified 返回空串。"""
    return {"verified": "",
            "likely": "路径按公开约定推断，未实地验证",
            "auto": "自动发现：家目录的隐藏文件夹下有 skills 目录"}.get(
        confidence(name), "不在目录表里")


def _looks_like_skills_dir(p):
    """空目录，或者至少有一个 <子目录>/SKILL.md——别把随便叫 skills 的数据目录当宿主。"""
    try:
        kids = list(p.iterdir())
    except OSError:
        return False
    if not kids:
        return True
    return any((k / "SKILL.md").is_file() for k in kids if k.is_dir())


def auto_discover(home=None, taken=()):
    """按「家目录下的隐藏文件夹 → 里面有 skills 目录」自动匹配目录表里没有的宿主。

    只看两处：~/.<名字>/skills 和 ~/.config/<名字>/skills。
    再往深不看——~/.codex/vendor_imports/skills、~/.grok/bundled/skills 这类是宿主自己的内置件，不是装 Skill 的地方。
    """
    home = Path(home) if home else Path.home()
    taken = {str(Path(t)) for t in taken}
    found = {}
    bases = [(home, True), (home / ".config", False)]
    for base, need_dot in bases:
        try:
            dirs = sorted(base.iterdir())
        except OSError:
            continue
        for d in dirs:
            n = d.name
            if need_dot and not n.startswith("."):
                continue
            label = n.lstrip(".")
            if not label or label.lower().startswith(AUTO_SKIP_PREFIX):
                continue
            p = d / "skills"
            if str(p) in taken or not p.is_dir() or not _looks_like_skills_dir(p):
                continue
            if label in CATALOG or label in found:
                continue
            found[label] = str(p)
    return found


def detect():
    """扫出本机的用户级宿主目录，返回 {名字: 路径}。

    先按目录表探，再按「隐藏文件夹下有 skills」自动补漏。
    同一个目录只算一次（~/.agents/skills 好几家共用），免得同一份装两遍。
    """
    found, seen = {}, set()
    for name, (candidates, _proj, _conf, _note) in CATALOG.items():
        hit = None
        for c in candidates:
            p = expand(c)
            if p and p.is_dir():
                hit = p
                break
        if not hit:
            for c in candidates:
                p = expand(c)
                if p and p.parent.is_dir() and p.parent != Path.home():   # 宿主装了但还没有 skills 目录
                    hit = p
                    break
        if hit and str(hit) not in seen:
            found[name] = str(hit)
            seen.add(str(hit))
    auto = auto_discover(taken=seen)
    _AUTO.clear()
    _AUTO.update(auto)
    found.update(auto)
    return found


def name_for_path(path):
    """给手填的目录起个宿主名：表里认识的用表里的名字，否则取文件夹名（~/.foo/skills → foo）。"""
    p = Path(os.path.expandvars(str(path))).expanduser()
    for name, (cands, *_rest) in CATALOG.items():
        for c in cands:
            e = expand(c)
            if e and e == p:
                return name
    base = p.parent.name if p.name.lower() == "skills" else p.name
    return base.lstrip(".") or "自定义"
