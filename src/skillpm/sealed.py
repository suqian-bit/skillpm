"""加密存放的 Skill：仓库里只放加密包，装的时候输口令解开。哪些 Skill 要口令、用哪个口令组，由仓库的 skillpm.repo.json 决定。

为什么要加密而不是只在工具里判断口令：工具装在每个人自己的机器上，判断改一行就绕过了；
仓库人人能拉，明文目录直接拷走就能用。加密后，没有口令拿不到内容，发给谁由发口令的人定。
（拿到口令的人能把解开的文件再拷给别人——这个管不住；最终兜底还是平台账号本身的权限。）

包格式（一个文件）：
    b"TESEAL1\\n" + 头（一行 JSON，明文）+ b"\\n" + 密文
头里有名字、版本、说明、口令组、提示、各文件哈希、更新日志——不解密也能列出来、比版本、显示更新日志。

两层密钥（信封加密）：内容用一把随机的内容密钥加密；内容密钥再用口令派生的密钥加密，放在头的 keys 里，一个口令一份。
现在每个口令组一个共用口令，keys 里就一份；以后要「每人一个口令、单独撤销某个人」，就是 keys 里放多份，格式不用变。
只用标准库：PBKDF2-HMAC-SHA256 派生密钥，HMAC-SHA256 计数器模式生成密钥流异或加密，HMAC-SHA256 校验（口令不对、包被改过都解不开）。
"""
import base64
import getpass
import hashlib
import hmac
import io
import json
import os
import secrets
import sys
import tempfile
import zipfile
from pathlib import Path

from skillpm.config import home

MAGIC = b"TESEAL1\n"
ROUNDS = 200_000
SKIP = {"__pycache__", ".DS_Store"}
_opened = {}          # 本进程里已经解开的：(仓库目录, 名字, 版本) → 临时根目录（里面是 skills/<名字>/）


class WrongPassword(Exception):
    pass


def _b64(b):
    return base64.b64encode(b).decode()


def _stream(key, nonce, data):
    out = bytearray(len(data))
    for i in range(0, len(data), 32):
        block = hmac.new(key, nonce + (i // 32).to_bytes(8, "big"), hashlib.sha256).digest()
        chunk = data[i:i + 32]
        out[i:i + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, block))
    return bytes(out)


def _mac(key, *parts):
    return hmac.new(key, b"".join(parts), hashlib.sha256).hexdigest()


def _canon(head):
    return json.dumps({k: v for k, v in head.items() if k != "mac"}, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _wrap(content_key, label, password):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    k = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS, dklen=64)
    wrapped = _stream(k[:32], nonce, content_key)
    return {"label": label, "salt": _b64(salt), "nonce": _b64(nonce), "wrapped": _b64(wrapped),
            "mac": _mac(k[32:], nonce, wrapped)}


def _unwrap(entry, password):
    k = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(entry["salt"]), ROUNDS, dklen=64)
    nonce, wrapped = base64.b64decode(entry["nonce"]), base64.b64decode(entry["wrapped"])
    if not hmac.compare_digest(_mac(k[32:], nonce, wrapped), entry.get("mac", "")):
        return None
    return _stream(k[:32], nonce, wrapped)


def skill_files(skill_dir):
    """要打进包的文件和哈希（跳过 __pycache__、.DS_Store）。"""
    skill_dir = Path(skill_dir)
    return {f.relative_to(skill_dir).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(skill_dir.rglob("*")) if f.is_file() and not (set(f.parts) & SKIP)}


def pack(skill_dir, passwords, meta):
    """把一个 Skill 目录加密成包的字节。

    passwords：{标签: 口令}，现在就一项 {口令组: 口令}；meta 至少有 name / version / lock，可带 summary / changelog / hint。
    """
    skill_dir = Path(skill_dir)
    files, buf = skill_files(skill_dir), io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.writestr(rel, (skill_dir / rel).read_bytes())
    content_key, nonce = secrets.token_bytes(64), secrets.token_bytes(16)
    cipher = _stream(content_key[:32], nonce, buf.getvalue())
    head = {"format": 1, **meta, "files": files, "nonce": _b64(nonce),
            "keys": [_wrap(content_key, label, pw) for label, pw in passwords.items()]}
    head["mac"] = _mac(content_key[32:], _canon(head), cipher)
    return MAGIC + json.dumps(head, ensure_ascii=False).encode("utf-8") + b"\n" + cipher


def _split(path):
    raw = Path(path).read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError(f"{path} 不是加密的 Skill 包")
    body = raw[len(MAGIC):]
    nl = body.index(b"\n")
    return json.loads(body[:nl].decode("utf-8")), body[nl + 1:]


def header(path):
    """不解密，只读头：名字、版本、口令组、说明、文件哈希、更新日志。"""
    return _split(path)[0]


def check_password(path, password):
    """这个口令能不能打开这个包（发版时核对口令有没有输错用）。"""
    head, cipher = _split(path)
    return _content_key(head, cipher, password) is not None


def _content_key(head, cipher, password):
    for entry in head.get("keys") or []:
        key = _unwrap(entry, password)
        if key and hmac.compare_digest(_mac(key[32:], _canon(head), cipher), head.get("mac", "")):
            return key
    return None


def unpack(path, password, out_root):
    """用口令解开，写到 out_root/skills/<名字>/。口令不对或包被改过抛 WrongPassword。"""
    head, cipher = _split(path)
    key = _content_key(head, cipher, password)
    if key is None:
        raise WrongPassword()
    plain = _stream(key[:32], base64.b64decode(head["nonce"]), cipher)
    dst = Path(out_root) / "skills" / head["name"]
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        for rel in z.namelist():
            target = (dst / rel).resolve()
            if dst.resolve() not in target.parents:            # 包里的路径不许跳出目标目录
                raise WrongPassword()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(rel))
    return dst


# ── 口令存本机：输对一次，以后 update 不用再输 ──────────────────────────────

def _store():
    return home() / "keys.json"


def _load():
    try:
        return json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def saved(key):
    return _load().get(key)


def remember(key, password):
    data = _load()
    data[key] = password
    p = _store()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def key_of(repo_name, lock):
    return f"{repo_name}/{lock}"


def interactive():
    return sys.stdin is not None and sys.stdin.isatty()


def ask(prompt):
    """口令只在终端里手敲，不显示、不进命令行、不进历史。测试里替换这个函数。"""
    return getpass.getpass(prompt)


def pkg_path(repo_dir, meta):
    return Path(repo_dir) / meta["sealed"]


def lock_text(name, meta):
    hint = meta.get("hint") or ""
    return f"安装 {name} 需要口令（{meta.get('lock', '?')} 组{'，' + hint if hint else ''}），输入时不显示："


def try_open(repo_name, repo_dir, name, meta, password):
    """用给定口令解开并记下口令；成功返回临时根目录，失败返回 None。"""
    root = Path(tempfile.mkdtemp(prefix="skillpm-sealed-"))
    try:
        unpack(pkg_path(repo_dir, meta), password, root)
    except WrongPassword:
        return None
    remember(key_of(repo_name, meta.get("lock", "")), password)
    _opened[(str(repo_dir), name, meta.get("version"))] = root
    return root


def open_skill(repo_name, repo_dir, name, meta, prompt=True, tries=3):
    """返回 (目录, 原因)：目录下有 skills/<名字>/ 可以照常安装；打不开时目录为 None，原因说明为什么。

    普通 Skill 直接返回仓库目录。加密的：先试本机记下的这个口令组的口令；不行、且允许问、且在终端里，就问（最多 tries 次）。
    """
    if not meta.get("sealed"):
        return repo_dir, None
    cache = (str(repo_dir), name, meta.get("version"))
    if cache in _opened:
        return _opened[cache], None
    if not pkg_path(repo_dir, meta).exists():
        return None, f"仓库里找不到加密包 {meta['sealed']}"
    old = saved(key_of(repo_name, meta.get("lock", "")))
    if old:
        root = try_open(repo_name, repo_dir, name, meta, old)
        if root:
            return root, None
    if not (prompt and interactive()):
        return None, ("口令已更换，本机记的旧口令打不开新版本" if old else "要口令才能装")
    for i in range(tries):
        pw = ask(lock_text(name, meta) if i == 0 else "口令不对，再输一次：")
        if not pw:
            break
        root = try_open(repo_name, repo_dir, name, meta, pw)
        if root:
            return root, None
    return None, "口令不对"
