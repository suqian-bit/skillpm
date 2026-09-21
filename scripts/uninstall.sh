#!/bin/sh
# 卸掉 skillpm 本身。
#
#   ./scripts/uninstall.sh            卸工具，保留已装的 Skill 和配置
#   ./scripts/uninstall.sh --all      连 ~/.skillpm 一起删（配置、状态、缓存、备份）
#
# 注意：这个脚本不动已经装到各个宿主目录里的 Skill。
# 要先清 Skill 的话，卸载工具之前跑：skillpm uninstall --yes
set -e
MODE=${1:-}
PY=$(command -v python3 || command -v python) || PY=""

removed=0

# 1) pip 装的
if [ -n "$PY" ] && "$PY" -m pip show skillpm >/dev/null 2>&1; then
  echo "卸载 pip 包 skillpm…"
  "$PY" -m pip uninstall -y skillpm >/dev/null 2>&1 && removed=1
fi
# 历史遗留：老 pip 会把它装成 UNKNOWN
if [ -n "$PY" ] && "$PY" -m pip show UNKNOWN >/dev/null 2>&1; then
  echo "顺手清掉老版本留下的 UNKNOWN 空壳包…"
  "$PY" -m pip uninstall -y UNKNOWN >/dev/null 2>&1 && removed=1
fi

# 2) 启动器
if [ -f "$HOME/.skillpm/.installed-at" ]; then
  LAUNCHER=$(cat "$HOME/.skillpm/.installed-at")
  [ -f "$LAUNCHER" ] && { rm -f "$LAUNCHER"; echo "删掉启动器 $LAUNCHER"; removed=1; }
fi
for d in "$HOME/.local/bin" /usr/local/bin "$HOME/bin"; do
  if [ -f "$d/skillpm" ] && head -3 "$d/skillpm" 2>/dev/null | grep -q 'skillpm/scripts/install'; then
    rm -f "$d/skillpm"; echo "删掉启动器 $d/skillpm"; removed=1
  fi
done

# 3) 配置和状态
if [ "$MODE" = "--all" ]; then
  if [ -d "$HOME/.skillpm" ]; then
    printf "要删掉 %s 吗？里面有配置、安装记录、仓库缓存和备份。[y/N] " "$HOME/.skillpm"
    read -r ans </dev/tty || ans=n
    case "$ans" in
      y|Y|yes|YES) rm -rf "$HOME/.skillpm"; echo "已删除 $HOME/.skillpm"; removed=1 ;;
      *) echo "保留 $HOME/.skillpm" ;;
    esac
  fi
else
  [ -d "$HOME/.skillpm" ] && echo "保留了 $HOME/.skillpm（配置和安装记录）；要一起删加 --all"
fi

[ "$removed" = 1 ] && echo "卸载完成。" || echo "没找到已安装的 skillpm。"
echo "提示：已经装到各宿主目录里的 Skill 不受影响；要清它们请先跑 skillpm uninstall --yes"
