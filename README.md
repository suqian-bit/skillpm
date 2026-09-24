# skillpm —— AI Skill 的安装与版本治理

把你们团队的 AI Skill 一键装到各个 Agent（Claude Code、Codex、Cursor、WorkBuddy……），并跟着仓库更新。
Mac / Windows / Linux 通用，**只用 Python 标准库，零第三方依赖**。

Skill 内容放在你们自己的 git 仓库里（通用 Agent Skill 格式），这里只有工具。

> **新人先看 [`docs/快速上手.md`](docs/快速上手.md)**：跟着装一遍，每一步都有截图。装好后 `skillpm docs` 在浏览器里看图文手册。
> **查命令看 [`docs/命令手册.md`](docs/命令手册.md)** —— 穷举每条命令、每个参数、每种写法，
> 包括两个「删除」的区别。想理解设计取舍看 [`docs/详细说明.md`](docs/详细说明.md)。
> 下面只写怎么上手。

---

## 三步上手

```bash
# 1. 装工具（一条命令，重复跑也没事）
git clone https://github.com/suqian-bit/skillpm.git ~/.skillpm-src 2>/dev/null; ~/.skillpm-src/scripts/install.sh

# 2. 装 Skill（第一次会引导你选仓库、选装到哪个 Agent、选装哪几个）
skillpm install

# 3. 确认
skillpm status
```

**Windows**（PowerShell）：

```powershell
if (-not (Test-Path $env:USERPROFILE\.skillpm-src)) { git clone https://github.com/suqian-bit/skillpm.git $env:USERPROFILE\.skillpm-src }; Set-ExecutionPolicy -Scope Process Bypass -Force; & "$env:USERPROFILE\.skillpm-src\scripts\install.ps1"
```

源码固定放在 `~/.skillpm-src`（Windows 是 `%USERPROFILE%\.skillpm-src`），写死的，省得到处找。
装完敲 `skillpm -v`；提示找不到命令的话，脚本会问要不要加 PATH，回车同意，新开一个终端生效。

## 日常就两条

```bash
skillpm check      # 看看有没有新版本，什么都不动
skillpm update     # 跟上最新，并告诉你每个 Skill 改了什么
```

## 命令一览

| 命令 | 干什么 |
|---|---|
| `skillpm install` | 安装。第一次会先问 Skill 仓库地址（当场试拉验证），再问装到哪 |
| `skillpm check` | 只看有没有新版本，什么都不动 |
| `skillpm update` | 检查并更新；成功后告诉你每个改了什么 |
| `skillpm status` | 各宿主装了什么、什么版本、有没有被本地改过 |
| `skillpm uninstall [名字...]` | 移除。不写名字会列出来让你选；`--all` 全删 |
| `skillpm repo add\|list\|remove` | 管理 Skill 仓库，**可以配多个**；怎么准备自己的 Skill 仓库见 [docs/接入自己的Skill仓库.md](docs/接入自己的Skill仓库.md) |
| `skillpm manifest --check` | 检查自己的 Skill 仓库合不合格（manifest.json 可选） |
| `skillpm host add\|list\|remove` | 管理宿主目录（认识 52 种常见 Agent） |
| `skillpm install <名字>` | 点名装要口令的 Skill（口令在终端里手敲） |
| `skillpm sync` | 重新生成各宿主下的 `AGENTS.md` 索引 |
| `skillpm self-update` | 更新工具本身（在哪个目录跑都行） |

`-v` / `--version` 看版本，`-h` / `--help` 看帮助，子命令后面加 `-h` 看它自己的参数。
参数打错了会给猜测，不会只丢一句 unrecognized arguments。

## 卸载

```bash
~/.skillpm-src/scripts/uninstall.sh           # 只卸工具，已装的 Skill 不动
~/.skillpm-src/scripts/uninstall.sh --all     # 连 ~/.skillpm 一起删
```

Windows（cmd、PowerShell 都能直接跑）：`~\.skillpm-src\scripts\uninstall.cmd`，加 `-All` 连配置一起删。别跑 `.sh`，Windows 不认。

想连 Skill 一起清，**先清 Skill 再卸工具**：`skillpm uninstall --all --yes`，然后再卸。
反过来不行——工具没了就没人知道哪些 Skill 是它装的。

## 几条规矩

- **只碰自己装的东西**：卸载和覆盖都以安装记录为准，别人放的一律不动。
- **覆盖前先备份**：`--force` 覆盖别人那份也一样，连它不认识的文件一起备份。
- **令牌不落日志**：屏幕输出和报错里一律打码。
- **不自动装 Python 包**：只检测、只提示，不动你的 Python 环境。
- **没验证过的就标出来**：`likely` 的宿主路径装之前会让你确认。

## 开发

```bash
pip install -e ".[dev]"
pytest -q          # 173 个用例
```

改了版本号（`src/skillpm/__init__.py`）就要在 `CHANGELOG.md` 写一条，
`tools/check_release.py` 和 CI 都会检查，对不上不让发。

命令速查见 [docs/命令手册.md](docs/命令手册.md)，设计考量见 [docs/详细说明.md](docs/详细说明.md)，
更新日志见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)

---

**问题、建议、踩到的坑** →
[GitHub Issues](https://github.com/suqian-bit/skillpm/issues)
