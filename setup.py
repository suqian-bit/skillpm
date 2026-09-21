"""老版 setuptools 的兼容垫片。

新版 setuptools（>=61）直接读 pyproject.toml 里的 [project]，用不到这个文件。
但 macOS 自带的 Python 3.9 配的是 setuptools 58 + pip 21，它们**看不懂** [project]，
结果会打出一个 name=UNKNOWN、version=0.0.0 的空壳包——装完没有 skillpm 命令，
而且 pip 还会说 "Successfully installed"，很容易被骗过去。

所以这里把同一份元数据用老格式再写一遍。改版本号只改 src/skillpm/__init__.py，
这里是读出来的，不会有两个真相。
"""
import re
from pathlib import Path

from setuptools import find_packages, setup

SRC = Path(__file__).parent / "src"
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (SRC / "skillpm" / "__init__.py").read_text(encoding="utf-8")).group(1)

setup(
    name="skillpm",
    version=VERSION,
    description="AI Skill 的安装与版本管理：一键装到各个 Agent 宿主并跟随更新",
    long_description=(Path(__file__).parent / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[],                       # 零第三方依赖，装起来不用连 PyPI
    entry_points={"console_scripts": ["skillpm = skillpm.cli:main"]},
)
