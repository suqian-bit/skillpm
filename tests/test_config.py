"""配置迁移：老的单仓库格式要能无感升级。"""
from skillpm.config import CONFIG_VERSION, migrate


def test_v1_single_repo_becomes_named_repo():
    old = {"repo_ssh": "git@h:g/p.git", "repo_http": "http://h", "repo_path": "g/p",
           "branch": "main", "mode": "git", "token": "abc", "hosts": {"A": "/tmp/a"}}
    new = migrate(dict(old))
    assert new["config_version"] == CONFIG_VERSION
    assert list(new["repos"]) == ["skillpm"]
    r = new["repos"]["skillpm"]
    assert r["ssh"] == "git@h:g/p.git" and r["path"] == "g/p" and r["token"] == "abc"
    assert new["hosts"] == {"A": "/tmp/a"}
    assert "repo_ssh" not in new          # 老字段清掉，免得两份真相


def test_migrate_is_idempotent():
    once = migrate({"repo_ssh": "git@h:g/p.git"})
    assert migrate(dict(once)) == once


def test_empty_config_gets_shape():
    new = migrate({})
    assert new["repos"] == {} and new["hosts"] == {}


def test_run_git_decodes_utf8_not_locale():
    """git 输出是 UTF-8；按本机代码页解码会在中文 Windows 上抛 UnicodeDecodeError。"""
    import inspect
    from skillpm import repos
    src = inspect.getsource(repos.run_git)
    assert 'encoding="utf-8"' in src
    assert 'errors="replace"' in src
