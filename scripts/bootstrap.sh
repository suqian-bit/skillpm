#!/bin/sh
# 一条命令搞定：没装过就克隆+安装，装过就更新。
#
# 首次（复制这一行）：
#   git clone https://github.com/suqian-bit/skillpm.git ~/.skillpm-src \
#     && ~/.skillpm-src/scripts/bootstrap.sh
#
# 以后更新：
#   ~/.skillpm-src/scripts/bootstrap.sh
#
set -e
REPO=${SKILLPM_REPO:-https://github.com/suqian-bit/skillpm.git}
SRC=$HOME/.skillpm-src        # 写死。找不到源码在哪是最尴尬的事

if [ -d "$SRC/.git" ]; then
  echo "已有源码：$SRC"
else
  echo "克隆到 $SRC …"
  git clone "$REPO" "$SRC"
fi
exec "$SRC/scripts/install.sh" "$@"
