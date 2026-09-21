"""让 `python -m skillpm` 也能用。

必须 sys.exit(main())：光调 main() 的话，返回码被丢掉，
失败也退出 0——CI 里拿退出码卡冲突就全失效了。
"""
import sys

from skillpm.cli import main

if __name__ == "__main__":
    sys.exit(main())
