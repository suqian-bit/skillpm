#!/bin/sh
# 重录「接入自己的仓库」里的截图。和 record_demo.sh 一样在独立的演示 HOME 里真实跑，跑完删掉。
#
# 用法：tools/manual_html/record_onboard.sh [演示目录，默认 ~/skillpm-demo]
#
# 「别的团队的仓库」是本机起的真 git 服务（git_demo_server.py，git http-backend，和 GitLab 同一套协议）：
#   ops/skills.git 公开；ops/private.git 私有，要令牌 glpat-demo1234。
# 演示 HOME 的 .gitconfig 里只让 gitlab.example.com 走这个服务，所以截图里是文档用的示例地址；装工具照样走真 GitLab。
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
H=${1:-$HOME/skillpm-demo}
W=$(mktemp -d); RAW=$W/raw; mkdir -p "$RAW" "$W/srv/ops"
PORT=${PORT:-8123}; TOKEN=glpat-demo1234

mk() {  # mk <仓库工作区> <skill> <版本> <说明>
  d=$1/skills/$2; mkdir -p "$d"
  printf -- "---\nname: %s\ndescription: %s\nversion: %s\n---\n\n# %s\n\n%s\n" "$2" "$4" "$3" "$2" "$4" > "$d/SKILL.md"
  printf "# %s 更新日志\n\n## %s — 2026-09-21\n- 初版\n" "$2" "$3" > "$d/CHANGELOG.md"
}
repo() {  # repo <名字> <skill 列表…>：建工作区、提交、导出成 bare 仓库
  n=$1; shift; w=$W/work/$n; mkdir -p "$w"
  while [ $# -gt 0 ]; do mk "$w" "$1" "$2" "$3"; shift 3; done
  git -C "$w" init -q -b main && git -C "$w" add -A && git -C "$w" -c user.name=ops -c user.email=ops@x commit -qm init
  git clone -q --bare "$w" "$W/srv/ops/$n.git"
}
repo skills ops-patrol 1.0.0 "每日巡检：检查服务器温度、风扇、电源告警" ops-backup 1.2.0 "配置备份：导出服务器和交换机配置"
repo private ops-secret-tool 0.9.0 "内部工具：只给运维组用"
python3 "$ROOT/tools/manual_html/git_demo_server.py" "$W/srv" "$PORT" "$TOKEN" & SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null; rm -rf "$H"' EXIT
sleep 1

run() {
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
rm -rf "$H"; mkdir -p "$H/.claude" "$H/.workbuddy"
git config --file "$H/.gitconfig" http.http://gitlab.example.com.proxy "http://127.0.0.1:$PORT"
run prep-tool "git clone -q $ROOT ~/.skillpm-src && ~/.skillpm-src/scripts/install.sh >/dev/null"

# 维护者自检：ops-report 的 name 写错了 → 不通过；改对 → 通过
cp -R "$W/work/skills" "$H/ops-skills"; rm -rf "$H/ops-skills/.git"
mkdir -p "$H/ops-skills/skills/ops-report"
printf -- "---\nname: ops-weekly-report\ndescription: 周报：汇总本周告警和处理情况\nversion: 1.0.0\n---\n\n# ops-report\n" > "$H/ops-skills/skills/ops-report/SKILL.md"
run o1-check-fail 'cd ~/ops-skills && skillpm manifest --check'
mk "$H/ops-skills" ops-report 1.0.0 "周报：汇总本周告警和处理情况"
run o2-check-pass 'cd ~/ops-skills && skillpm manifest --check'

run o3-repo-add 'skillpm repo add 运维组 http://gitlab.example.com/ops/skills.git'
run o4-install 'skillpm install --repo 运维组' '
expect "都不要"; after 800; send "\r"'
run o5-typo 'skillpm repo add 存储组 http://gitlab.example.com/ops/skils.git'
run o6-private 'skillpm repo add 运维私有 http://gitlab.example.com/ops/private.git'
run o7-private-token "skillpm repo add 运维私有 http://gitlab.example.com/ops/private.git --token $TOKEN"
run o8-repo-list 'skillpm repo'

export DEMO_HOME="$H"      # 截图里演示 HOME 显示成 ~
T="$ROOT/tools/manual_html/term2svg.py"; O="$ROOT/docs/img"
PROMPT_DIR='~/ops-skills' python3 "$T" "$RAW/o1-check-fail.log" 'skillpm manifest --check' "$O/ob-01-check-fail.svg"
PROMPT_DIR='~/ops-skills' python3 "$T" "$RAW/o2-check-pass.log" 'skillpm manifest --check' "$O/ob-02-check-pass.svg"
python3 "$T" "$RAW/o3-repo-add.log" 'skillpm repo add 运维组 http://gitlab.example.com/ops/skills.git' "$O/ob-03-repo-add.svg"
python3 "$T" "$RAW/o4-install.log" 'skillpm install --repo 运维组' "$O/ob-04-install.svg"
python3 "$T" "$RAW/o5-typo.log" 'skillpm repo add 存储组 http://gitlab.example.com/ops/skils.git' "$O/ob-05-typo.svg"
python3 "$T" "$RAW/o6-private.log" 'skillpm repo add 运维私有 http://gitlab.example.com/ops/private.git' "$O/ob-06-private.svg"
python3 "$T" "$RAW/o7-private-token.log" "skillpm repo add 运维私有 http://gitlab.example.com/ops/private.git --token $TOKEN" "$O/ob-07-private-token.svg"
python3 "$T" "$RAW/o8-repo-list.log" 'skillpm repo' "$O/ob-08-repo-list.svg"
echo "原始输出留在 $RAW；截图已更新到 docs/img/ob-*.svg。接着重新生成手册：uvx --with markdown python tools/manual_html/build.py"
