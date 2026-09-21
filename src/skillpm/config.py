"""配置与安装状态：放哪、怎么读写、老格式怎么升级。

config.json  仓库地址、令牌、宿主路径 —— 含密，权限 600
state.json   各宿主装了什么、什么版本、安装时每个文件的哈希
"""
import json
import os
import re
from pathlib import Path

from skillpm.console import remember_secret, warn

CONFIG_VERSION = 2


def home():
    return Path(os.environ.get("SKILLPM_HOME") or (Path.home() / ".skillpm"))


def config_path():
    return home() / "config.json"


def state_path():
    return home() / "state.json"


def cache_dir(repo_name):
    return home() / "repos" / re.sub(r"[^\w.-]", "_", repo_name)


def backup_dir():
    return home() / "backup"


def migrate(cfg):
    """单仓库的老配置升级成多仓库结构，用户无感。"""
    if cfg.get("config_version", 1) >= CONFIG_VERSION:
        return cfg
    if cfg.get("repo_ssh"):
        cfg["repos"] = {cfg.get("repo_name") or "skillpm": {
            "ssh": cfg.pop("repo_ssh", ""), "http": cfg.pop("repo_http", ""),
            "path": cfg.pop("repo_path", ""), "branch": cfg.pop("branch", "main"),
            "mode": cfg.pop("mode", "git"), "token": cfg.pop("token", "")}}
    for k in ("repo_host", "repo_name"):
        cfg.pop(k, None)
    cfg.setdefault("repos", {})
    cfg.setdefault("hosts", {})
    cfg["config_version"] = CONFIG_VERSION
    return cfg


def _read(path, default):
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        warn(f"{path} 读不动（文件坏了？），先按空的算")
        return dict(default)


def load_config():
    cfg = migrate(_read(config_path(), {"config_version": CONFIG_VERSION, "repos": {}, "hosts": {}}))
    for repo in (cfg.get("repos") or {}).values():
        remember_secret(repo.get("token"))
    return cfg


def load_state():
    return _read(state_path(), {"hosts": {}})


def _write(path, data, secret=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if secret and os.name != "nt":
        os.chmod(path, 0o600)


def save_config(cfg):
    _write(config_path(), cfg, secret=True)


def save_state(state):
    _write(state_path(), state)
