#!/bin/sh
# 重录「快速上手」里的终端截图：在独立的演示 HOME 里真实跑一遍，再渲染成 docs/img/qs-*.svg。
#
# 用法：tools/manual_html/record_demo.sh [演示目录，默认 ~/skillpm-demo]
# 需要：expect（macOS 自带）、git。
#
# 真实环境一个字不碰：HOME 指到演示目录，PATH 只有演示目录的 bin + 系统只读目录，跑完删掉演示目录。
# Skill 仓库是本机起的真 git 服务（git_demo_server.py），演示 HOME 里只让 gitlab.example.com 走它，
# 所以截图里是示例地址。
#
# 环境变量：
#   SHOT_INSTALL=1   录「装工具」那张：真的从项目主页（skillpm.HOMEPAGE）git clone。主页还不能访问时别开。
#   OLD_TOOL=<提交>  录「self-update」那张时先把工具源码退回到这个提交；默认上一个提交，没有就跳过这张。
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
H=${1:-$HOME/skillpm-demo}
W=$(mktemp -d); RAW=$W/raw; mkdir -p "$RAW" "$W/srv/team"
PORT=${PORT:-8123}
HOMEPAGE=$(PYTHONPATH="$ROOT/src" python3 -c "from skillpm import HOMEPAGE; print(HOMEPAGE)")
OLD_TOOL=${OLD_TOOL:-$(git -C "$ROOT" rev-parse -q --verify HEAD~1 2>/dev/null || true)}

skill() {  # skill <工作区> <名字> <版本> <说明> [这一版改了什么]
  d=$1/skills/$2; mkdir -p "$d"
  printf -- "---\nname: %s\ndescription: %s\nversion: %s\n---\n\n# %s\n\n%s\n" "$2" "$4" "$3" "$2" "$4" > "$d/SKILL.md"
  if [ -f "$d/CHANGELOG.md" ]; then old=$(cat "$d/CHANGELOG.md" | tail -n +2); else old=""; fi
  printf "# %s 更新日志\n\n## %s — 2026-09-21\n%s\n%s\n" "$2" "$3" "${5:-- 初版}" "$old" > "$d/CHANGELOG.md"
}
T=$W/work/skills; mkdir -p "$T"
skill "$T" code-review 1.0.0 "代码评审：按团队规范检查改动，列出问题和修改建议"
skill "$T" pdf-tools 2.1.0 "PDF 处理：拆分、合并、提取文字和表格"
skill "$T" weekly-report 1.3.0 "周报：汇总本周提交和工单，生成周报草稿"
skill "$T" doc-writer 0.9.0 "文档：根据代码生成 README 和接口说明"
git -C "$T" init -q -b main && git -C "$T" add -A && git -C "$T" -c user.name=demo -c user.email=demo@example.com commit -qm init
git clone -q --bare "$T" "$W/srv/team/skills.git"
python3 "$ROOT/tools/manual_html/git_demo_server.py" "$W/srv" "$PORT" unused & SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null; rm -rf "$H"' EXIT
sleep 1

run() {   # run <场景> <命令> [expect 交互]
  cat > "$RAW/$1.exp" <<EXP
set timeout 180
log_file -noappend "$RAW/$1.log"
spawn /bin/zsh -f -c {$2}
${3:-}
expect eof
EXP
  env -i HOME="$H" USER=demo SHELL=/bin/zsh TERM=xterm-256color LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8 \
      COLUMNS=100 PATH="$H/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin" /usr/bin/expect -f "$RAW/$1.exp" >/dev/null 2>&1
  echo "  录好 $1"
}
fresh() {
  rm -rf "$H"; mkdir -p "$H/.claude" "$H/.codex"
  git config --file "$H/.gitconfig" http.http://gitlab.example.com.proxy "http://127.0.0.1:$PORT"
}
echo "演示目录：$H"

# ── self-update：先装好，再把源码退回上一个提交（不录），再真实升级
if [ -n "$OLD_TOOL" ]; then
  fresh
  run prep-old-tool "git clone -q $ROOT ~/.skillpm-src && ~/.skillpm-src/scripts/install.sh >/dev/null && git -C ~/.skillpm-src reset -q --hard $OLD_TOOL"
  run 07-self-update 'skillpm self-update'
fi

# ── 其余场景：从头来
fresh
if [ "${SHOT_INSTALL:-}" = 1 ]; then
  run 01-install-tool "git clone $HOMEPAGE.git ~/.skillpm-src 2>/dev/null; ~/.skillpm-src/scripts/install.sh"
else
  run prep-tool "git clone -q $ROOT ~/.skillpm-src && ~/.skillpm-src/scripts/install.sh >/dev/null"
fi
run 02-first-install 'skillpm install' '
expect "仓库地址"; after 600; send "http://gitlab.example.com/team/skills.git\r"
expect "仓库名"; after 600; send "\r"
expect "要装到哪几个"; expect "都不要"; after 800; send "\r"
expect "要装哪些"; expect "都不要"; after 800; send "1-3\r"'
run 03-status 'skillpm status'
# 仓库里发一个新版本（不录）：code-review 1.0.0 → 1.1.0
skill "$T" code-review 1.1.0 "代码评审：按团队规范检查改动，列出问题和修改建议" "**新增安全检查**：发现硬编码的密码、密钥时单独列出。
- 评审意见按严重程度排序，先看必须改的。"
git -C "$T" -c user.name=demo -c user.email=demo@example.com commit -qam "code-review 1.1.0"
git -C "$T" push -q "$W/srv/team/skills.git" main
run 04-check 'skillpm check'
run 05-update 'skillpm update' '
expect -re {\[Y/n\]}; after 800; send "\r"'
run 06-uninstall 'skillpm uninstall' '
expect "都不要"; after 900; send "3,6\r"
expect -re {\[y/N\]}; after 800; send "y\r"'
[ -f "$RAW/07-self-update.log" ] || run 07-self-update 'skillpm self-update'   # 没有旧版本可退时，就录「已经是最新的」
run 08-help 'skillpm -h'
run 09-uninstall-tool '~/.skillpm-src/scripts/uninstall.sh'

export DEMO_HOME="$H"      # 截图里演示 HOME 显示成 ~
R="$ROOT/tools/manual_html/term2svg.py"; O="$ROOT/docs/img"; mkdir -p "$O"
[ -f "$RAW/01-install-tool.log" ] && python3 "$R" "$RAW/01-install-tool.log" "git clone $HOMEPAGE.git ~/.skillpm-src 2>/dev/null; ~/.skillpm-src/scripts/install.sh" "$O/qs-01-install-tool.svg"
python3 "$R" "$RAW/02-first-install.log" 'skillpm install' "$O/qs-02-first-install.svg"
python3 "$R" "$RAW/03-status.log" 'skillpm status' "$O/qs-03-status.svg"
python3 "$R" "$RAW/04-check.log" 'skillpm check' "$O/qs-04-check.svg"
python3 "$R" "$RAW/05-update.log" 'skillpm update' "$O/qs-05-update.svg"
python3 "$R" "$RAW/06-uninstall.log" 'skillpm uninstall' "$O/qs-06-uninstall.svg"
[ -f "$RAW/07-self-update.log" ] && python3 "$R" "$RAW/07-self-update.log" 'skillpm self-update' "$O/qs-07-self-update.svg"
python3 "$R" "$RAW/08-help.log" 'skillpm -h' "$O/qs-08-help.svg"
python3 "$R" "$RAW/09-uninstall-tool.log" '~/.skillpm-src/scripts/uninstall.sh' "$O/qs-09-uninstall-tool.svg"
echo "原始输出留在 $RAW；截图已更新到 docs/img/qs-*.svg。接着重新生成手册：uvx --with markdown python tools/manual_html/build.py"
