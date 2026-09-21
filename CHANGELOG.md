# skillpm 更新日志

版本号语义：主版本＝命令或配置不兼容；次版本＝加功能；修订号＝修 bug，行为不变。
改了 `src/skillpm/__init__.py` 里的版本号就要在这写一条，`tools/check_release.py` 会检查。

## 2.0.1 — 2026-09-21

**修：Windows 上输出被重定向时，一打中文就崩。** 英文 Windows 的系统代码页是 cp1252，编不了中文；
输出接管道、写文件或在 CI 里跑时，Python 就用它编码，直接 `UnicodeEncodeError`。现在启动时把输出流改成 UTF-8。
中文 Windows 的代码页恰好能编中文，所以之前没暴露——是开源后第一次跑 Windows CI 抓到的。

- `~` 统一用同一个家目录来源展开：Windows 上 Agent 目录表和自动发现以前可能看的是两个不同的家目录。
- CI：在 Mac / Linux / Windows 上真的跑一遍安装脚本和卸载脚本。

## 2.0.0 — 2026-09-21

**首个公开版本。** 把放在 git 仓库里的 AI Skill 一键装到本机的各个 Agent，并跟着仓库更新。

**和 1.x 的不兼容之处：不再内置默认的 Skill 仓库。** 第一次运行 `skillpm install` 时必须填你们团队的仓库地址；
已经配好的人不受影响。

### 能做什么

- **一键装到多个 Agent**：认识 52 种常见 Agent 的 Skill 目录（Claude Code、Codex、Cursor、Windsurf、Gemini CLI、
  Qoder、Trae、WorkBuddy……），表里没有的按「家目录的隐藏文件夹下有 skills」自动发现，也能手填目录。
- **跟着仓库更新**：`skillpm update` 列出新版本，确认后更新，并把每个 Skill 的更新日志念给你；旧版自动备份。
- **不碰别人的东西**：本地改过的、不是本工具装的 Skill，安装和更新都跳过并说明；`--force` 覆盖前先完整备份。
- **多个仓库**：可以同时配多个仓库。同名 Skill 换来源只在你自己 `install` 时发生、而且会先问你；
  `update` 永远只跟着装的时候那个仓库。
- **Skill 仓库几乎零要求**：通用 Agent Skill 格式（`skills/<名字>/SKILL.md`，写好 `name`、`description`）就能装；
  `version`、`CHANGELOG.md`、`manifest.json` 都可选。`skillpm manifest --check` 自检，适合放 CI。
- **私有仓库**：`--token` 访问令牌（不进命令行、不落盘到缓存的 git 配置），或者 SSH。
- **锁版本**：`skillpm freeze` 导出锁文件，别人 `install --from` 装到完全一样的一套。
- **项目级安装**：`-p` 只装到当前项目，版本写进锁文件随项目提交。
- **中文友好**：全部提示和报错是中文，写错命令会猜你想写什么并列出常用写法；拉取失败按原因给出下一步。
- **图文手册随工具发**：`skillpm docs` 在浏览器里打开，快速上手每一步都有真实截图。
- **零依赖**：只用 Python 3.8+ 标准库；Mac / Windows / Linux 通用，安装脚本默认不碰 PyPI。
