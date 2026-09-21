#!/usr/bin/env python3
"""把 docs/ 里的手册生成一个独立的 HTML 页面（替代原来的 Word 版）。

- **内容只有一份**：直接渲染 docs/快速上手.md、命令手册.md、接入自己的Skill仓库.md 和 CHANGELOG.md，改 md 就行，
  不用再像 Word 版那样另写一遍内容。
- 单文件、样式脚本全内联、不引外网资源——内网打不开 CDN 也能看，发给别人直接双击。
- 默认打开「快速上手」（重点和常用命令在前）；顶上切换三份文档；底部更新日志默认折叠，每个版本再各自折叠。
- 左边目录可搜、代码块一键复制、跟随系统深色模式、手机上也能看。

用法：
    uvx --with markdown python tools/manual_html/build.py [输出路径]
不给输出路径就生成到 docs/使用手册.html（随工具一起发，`skillpm docs` 打开的就是它，要提交）。
改了 docs/ 下的 md 或 CHANGELOG 就要重新生成，否则 tools/check_release.py 不让发版。
"""
import html
import re
import sys
from datetime import date
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from skillpm import HOMEPAGE, __version__  # noqa: E402
from skillpm.manual import html_path, source_hash  # noqa: E402

REPO_WEB = HOMEPAGE + "/blob/main/"
DOCS = [
    ("start", "快速上手", ROOT / "docs" / "快速上手.md"),
    ("manual", "完整命令手册", ROOT / "docs" / "命令手册.md"),
    ("onboard", "接入自己的仓库", ROOT / "docs" / "接入自己的Skill仓库.md"),
]


def gfm_fix(text):
    """python-markdown 比 GitHub 严格：列表、表格、代码块前面不空一行就不认。这里补上空行。"""
    out, in_code = [], False
    for line in text.splitlines():
        starts_block = re.match(r"\s*([-*+] |\d+\. |\||```)", line)
        if line.startswith("```"):
            if not in_code and out and out[-1].strip():
                out.append("")
            in_code = not in_code
        elif not in_code and starts_block and out and out[-1].strip() \
                and not re.match(r"\s*([-*+] |\d+\. |\||>)", out[-1]):
            out.append("")
        out.append(line)
    return "\n".join(out)


def render(key, path):
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                           extension_configs={"toc": {"slugify": lambda v, s: f"{key}-" + re.sub(r"\W+", "-", v).strip("-").lower(),
                                                      "toc_depth": "2-3"}})
    body = md.convert(gfm_fix(path.read_text(encoding="utf-8")))
    # 文档之间的链接：另一份手册 → 切到那一页；其余 md → 指到 GitLab 上的文件
    for k, _t, p in DOCS:
        body = body.replace(f'href="{p.name}"', f'href="#{k}" data-doc="{k}"')
    body = re.sub(r'href="(?:\.\./)?([^"#:]+\.md)"',
                  lambda m: f'href="{REPO_WEB}{"docs/" if not m.group(0).count("../") else ""}{m.group(1)}" target="_blank"',
                  body)
    # 截图直接嵌进页面（base64），单个 HTML 拿到哪都能看到图
    def inline(m):
        import base64
        f = path.parent / m.group(1)
        if not f.exists():
            raise SystemExit(f"{path.name} 引用的图片不存在：{m.group(1)}")
        data = base64.b64encode(f.read_bytes()).decode()
        return f'class="shot" src="data:image/svg+xml;base64,{data}"'
    body = re.sub(r'src="([^"]+\.svg)"', inline, body)
    # 外部链接新开标签页（手册是本地单文件，点走了就回不来）
    body = re.sub(r'<a href="(https?://[^"]+)"(?![^>]*target=)', r'<a href="\1" target="_blank" rel="noopener"', body)
    # 表格包一层，窄屏能横向滚
    body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    # 引用块做成提示框
    body = body.replace("<blockquote>", '<blockquote class="note">')
    toc = md.toc_tokens
    return body, toc


def changelog_html():
    """CHANGELOG.md → 一个默认折叠的「更新日志」，每个版本再各自折叠，摘要写版本、日期和那一版的标题句。"""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)[1:]
    items = []
    for part in parts:
        head, _, body = part.partition("\n")
        m = re.match(r"(\S+)\s*[—-]\s*(\S+)", head.strip())
        ver, day = (m.group(1), m.group(2)) if m else (head.strip(), "")
        first = re.search(r"\*\*(.+?)\*\*", body)
        gist = html.escape(first.group(1).replace("`", "")) if first else ""
        inner = markdown.markdown(gfm_fix(body), extensions=["tables", "fenced_code", "sane_lists"])
        inner = inner.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
        inner = inner.replace("<blockquote>", '<blockquote class="note">')
        items.append(f'<details class="ver-item"><summary><b>{html.escape(ver)}</b>'
                     f'<span class="d">{html.escape(day)}</span><span class="g">{gist}</span></summary>'
                     f'<div class="ver-body">{inner}</div></details>')
    return (f'<details class="changelog" id="changelog"><summary>更新日志<span class="d">共 {len(items)} 个版本，点开看每一版改了什么</span></summary>'
            f'{"".join(items)}</details>')


def toc_html(tokens):
    items = []
    for t in tokens:
        if t["level"] == 1:
            items.append(toc_html(t["children"]))
            continue
        kids = "".join(f'<li class="l3"><a href="#{c["id"]}">{c["name"]}</a></li>' for c in t["children"])
        items.append(f'<li class="l2"><a href="#{t["id"]}">{t["name"]}</a>'
                     + (f"<ul>{kids}</ul>" if kids else "") + "</li>")
    return "".join(items)


CSS = r"""
:root{--bg:#f7f8fa;--paper:#fff;--ink:#1f2933;--muted:#5b6673;--line:#e3e7ec;--accent:#3e6ddf;
--accent-soft:#eaf0fd;--code-bg:#0f172a;--code-ink:#e2e8f0;--inline-bg:#eef1f5;--warn:#b05a00;--warn-soft:#fff6e5;
--shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0d1117;--paper:#151b23;--ink:#e6edf3;
--muted:#9aa5b1;--line:#2a3340;--accent:#7aa2ff;--accent-soft:#1c2740;--code-bg:#0a0f1a;--code-ink:#dbe4ef;
--inline-bg:#222c38;--warn:#f0a44b;--warn-soft:#2b2214;--shadow:none}}
:root[data-theme="dark"]{--bg:#0d1117;--paper:#151b23;--ink:#e6edf3;--muted:#9aa5b1;--line:#2a3340;--accent:#7aa2ff;
--accent-soft:#1c2740;--code-bg:#0a0f1a;--code-ink:#dbe4ef;--inline-bg:#222c38;--warn:#f0a44b;--warn-soft:#2b2214;--shadow:none}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:76px}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC",
"Microsoft YaHei","Hiragino Sans GB","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--paper) 88%,transparent);
backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.bar{max-width:1280px;margin:0 auto;display:flex;align-items:center;gap:16px;padding:0 20px;height:60px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;white-space:nowrap}
.logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,var(--accent),#8b5cf6);
display:grid;place-items:center;color:#fff;font-size:14px}
.ver{font-weight:500;font-size:12px;color:var(--muted);background:var(--inline-bg);padding:2px 8px;border-radius:99px}
/* 顶部三篇的切换：做成一组显眼的按钮，不然容易以为手册只有「快速上手」一页 */
.tabs-wrap{display:flex;align-items:center;gap:8px;margin-left:8px;min-width:0}
.tabs-hint{font-size:12px;color:var(--muted);white-space:nowrap}
.tabs{display:flex;gap:2px;padding:3px;border:1px solid var(--line);border-radius:10px;background:var(--inline-bg)}
.tabs button{border:0;background:none;color:var(--ink);font:inherit;font-size:14.5px;font-weight:500;padding:6px 14px;border-radius:7px;cursor:pointer;white-space:nowrap}
.tabs button:hover{background:var(--paper)}
.tabs button .n{display:inline-grid;place-items:center;width:18px;height:18px;margin-right:6px;border-radius:50%;
font-size:11px;font-weight:700;background:var(--line);color:var(--muted)}
.tabs button.on{background:var(--accent);color:#fff;font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.15)}
.tabs button.on .n{background:rgba(255,255,255,.25);color:#fff}
/* 每篇末尾：下一篇 */
.next{display:flex;justify-content:space-between;align-items:center;gap:12px;width:100%;margin-top:36px;padding:16px 20px;
border:1px solid var(--accent);border-radius:12px;background:var(--accent-soft);color:var(--accent);font:inherit;cursor:pointer;text-align:left}
.next:hover{filter:brightness(.97)}.next small{display:block;font-size:12px;color:var(--muted)}.next b{font-size:16px}.next .arr{font-size:22px}
.sp{flex:1}.icon-btn{border:1px solid var(--line);background:var(--paper);color:var(--muted);border-radius:8px;
height:32px;min-width:32px;cursor:pointer;font-size:14px}
.menu-btn{display:none}
.wrap{max-width:1280px;margin:0 auto;display:grid;grid-template-columns:268px minmax(0,1fr);gap:32px;padding:24px 20px 80px}
nav.toc{position:sticky;top:84px;align-self:start;max-height:calc(100vh - 100px);overflow:auto;padding-right:6px}
.search{width:100%;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:8px;
padding:8px 10px;font:inherit;font-size:13px;margin-bottom:12px}
nav.toc ul{list-style:none;margin:0;padding:0}nav.toc li.l2>a{display:block;padding:5px 10px;border-radius:6px;
color:var(--ink);font-size:13.5px;font-weight:600}nav.toc li.l3>a{display:block;padding:3px 10px 3px 22px;
color:var(--muted);font-size:13px}nav.toc a:hover{background:var(--inline-bg);text-decoration:none}
nav.toc a.cur{color:var(--accent);background:var(--accent-soft)}
nav.toc .t-all{margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}
main{min-width:0}p code,li code{overflow-wrap:anywhere}main article{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:36px 44px;box-shadow:var(--shadow)}
.doc{display:none}.doc.on{display:block}
h1{font-size:28px;line-height:1.3;margin:0 0 8px}h2{font-size:21px;margin:44px 0 14px;padding-top:6px;
border-top:1px solid var(--line)}h2:first-of-type{border-top:0}h3{font-size:17px;margin:30px 0 10px}
h1+p,h1+blockquote{color:var(--muted)}p{margin:10px 0}ul,ol{padding-left:22px}li{margin:3px 0}
code{font-family:"SF Mono",Menlo,Consolas,"Microsoft YaHei",monospace;font-size:.88em;background:var(--inline-bg);
padding:1px 6px;border-radius:5px}
pre{position:relative;background:var(--code-bg);color:var(--code-ink);border-radius:10px;padding:16px 18px;
overflow:auto;font-size:13px;line-height:1.65;margin:14px 0}pre code{background:none;padding:0;color:inherit;font-size:inherit}
pre .c{color:#7d8ba1}
.copy{position:absolute;top:8px;right:8px;opacity:0;transition:.15s;border:1px solid rgba(255,255,255,.18);
background:rgba(255,255,255,.08);color:#dbe4ef;border-radius:6px;font-size:12px;padding:2px 8px;cursor:pointer}
pre:hover .copy,.copy:focus{opacity:1}
.tw{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:9px 14px;
border-bottom:1px solid var(--line);vertical-align:top}th{background:var(--inline-bg);font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:0}td code{white-space:nowrap}
blockquote.note{margin:16px 0;padding:10px 16px;border-left:4px solid var(--warn);background:var(--warn-soft);
border-radius:0 10px 10px 0}blockquote.note p{margin:4px 0}
hr{border:0;border-top:1px solid var(--line);margin:32px 0}
img.shot{display:block;max-width:100%;height:auto;margin:12px 0 18px;border-radius:10px;
box-shadow:0 8px 24px rgba(15,23,42,.18),0 1px 3px rgba(15,23,42,.12)}
.foot{color:var(--muted);font-size:12.5px;text-align:center;margin-top:28px}
.card{margin-top:20px;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:6px 24px;box-shadow:var(--shadow)}
details>summary{cursor:pointer;list-style:none;display:flex;align-items:baseline;gap:12px;padding:14px 0}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"›";display:inline-block;width:12px;color:var(--muted);transition:transform .15s}
details[open]>summary::before{transform:rotate(90deg)}
.changelog>summary{font-size:17px;font-weight:700}.changelog .d,.ver-item .d{color:var(--muted);font-size:13px;font-weight:400}
.ver-item{border-top:1px solid var(--line)}.ver-item>summary{padding:10px 0;font-size:14px}
.ver-item .g{color:var(--ink);flex:1;min-width:0}.ver-item b{min-width:52px}
.ver-body{padding:0 0 14px 24px;font-size:14px}.ver-body h3{font-size:15px;margin:16px 0 6px}
#doc-start h2{border-top:0;margin-top:34px}
#doc-start .tw td:first-child{white-space:nowrap}
#doc-start ol>li{margin:8px 0}
.hit{background:#ffe58f;color:#1f2933;border-radius:3px}
@media (max-width:900px){.wrap{grid-template-columns:minmax(0,1fr);padding:16px 16px 60px}
nav.toc{position:fixed;inset:60px 0 0 0;max-height:none;background:var(--paper);z-index:15;padding:16px;
transform:translateX(-100%);transition:transform .2s}body.menu nav.toc{transform:none}
.menu-btn{display:inline-block}main article{padding:22px 18px;border-radius:10px}.bar{gap:8px;padding:0 12px}.tabs-wrap{margin-left:0}.tabs-hint{display:none}.tabs{min-width:0;overflow-x:auto}.tabs button{padding:5px 8px;font-size:13px}.tabs button .n{display:none}.ver{display:none}
.brand .name{display:none}h1{font-size:23px}}
"""

JS = r"""
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
function show(key,hash){$$('.doc').forEach(d=>d.classList.toggle('on',d.id==='doc-'+key));
$$('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.doc===key));
$$('nav.toc .t').forEach(t=>t.hidden=t.dataset.doc!==key);
try{localStorage.setItem('te-doc',key)}catch(e){}
if(hash){const el=document.getElementById(hash);if(el){el.scrollIntoView();return}}window.scrollTo(0,0)}
$$('.tabs button,.next').forEach(b=>b.onclick=()=>{history.replaceState(null,'','#'+b.dataset.doc);show(b.dataset.doc)});
// 目录底部「更新日志」：展开再滚过去
function openLog(){const c=document.getElementById('changelog');if(!c)return;c.open=true;
setTimeout(()=>c.scrollIntoView({behavior:'instant',block:'start'}),0)}
$('#toc-changelog').onclick=e=>{e.preventDefault();history.replaceState(null,'','#changelog');openLog();
document.body.classList.remove('menu')};
document.addEventListener('click',e=>{const a=e.target.closest('a[data-doc]');if(a){e.preventDefault();
history.replaceState(null,'','#'+a.dataset.doc);show(a.dataset.doc)}
if(e.target.closest('nav.toc a'))document.body.classList.remove('menu')});
// 代码块：注释变灰、加复制按钮
$$('pre').forEach(pre=>{const code=pre.querySelector('code');if(!code)return;
code.innerHTML=code.innerHTML.split('\n').map(l=>l.replace(/(^|\s)(#(?!!)[^\n]*)$/,'$1<span class="c">$2</span>')).join('\n');
const b=document.createElement('button');b.className='copy';b.textContent='复制';
b.onclick=()=>{const t=code.innerText.replace(/\s+$/,'');(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject())
.then(()=>{b.textContent='已复制';setTimeout(()=>b.textContent='复制',1400)}).catch(()=>{const r=document.createRange();
r.selectNodeContents(code);const s=getSelection();s.removeAllRanges();s.addRange(r);b.textContent='已选中，按 Ctrl+C'})};pre.appendChild(b)});
// 目录跟随滚动高亮
const io=new IntersectionObserver(es=>es.forEach(en=>{if(en.isIntersecting){$$('nav.toc a').forEach(a=>
a.classList.toggle('cur',a.getAttribute('href')==='#'+en.target.id));
const c=$('nav.toc a.cur');if(c){const n=$('nav.toc'),r=c.getBoundingClientRect(),nr=n.getBoundingClientRect();
if(r.top<nr.top+40||r.bottom>nr.bottom-20)n.scrollTop+=r.top-nr.top-nr.height/3}}}),{rootMargin:'-80px 0px -70% 0px'});
$$('.doc h2[id],.doc h3[id]').forEach(h=>io.observe(h));
// 目录搜索
$('.search').oninput=e=>{const q=e.target.value.trim().toLowerCase();$$('nav.toc li').forEach(li=>{
li.style.display=!q||li.textContent.toLowerCase().includes(q)?'':'none'})};
// 深浅色
const root=document.documentElement;try{const t=localStorage.getItem('te-theme');if(t)root.dataset.theme=t}catch(e){}
$('#theme').onclick=()=>{const dark=root.dataset.theme?root.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
root.dataset.theme=dark?'light':'dark';try{localStorage.setItem('te-theme',root.dataset.theme)}catch(e){}};
$('#menu').onclick=()=>document.body.classList.toggle('menu');
// 打开时：#锚点优先，其次上次看的那份
(()=>{const h=decodeURIComponent(location.hash.slice(1));let key='start';
if(h==='changelog'){try{key=localStorage.getItem('te-doc')||key}catch(e){};show(key);openLog();return}
const hit=h&&document.getElementById(h);if(hit){key=hit.closest('.doc').id.slice(4)}
else if(['start','manual','onboard'].includes(h)){key=h}else{try{key=localStorage.getItem('te-doc')||key}catch(e){}}
show(key,hit?h:null)})();
"""


def build(out):
    docs, tocs, tabs = [], [], []
    for i, (key, title, path) in enumerate(DOCS):
        body, toc = render(key, path)
        if i + 1 < len(DOCS):      # 每篇末尾指向下一篇，读完不至于以为到头了
            nk, nt, _ = DOCS[i + 1]
            body += (f'<button class="next" data-doc="{nk}"><span><small>下一篇（共 {len(DOCS)} 篇）</small>'
                     f'<b>{html.escape(nt)}</b></span><span class="arr">→</span></button>')
        docs.append(f'<section class="doc" id="doc-{key}">{body}</section>')
        tocs.append(f'<ul class="t" data-doc="{key}">{toc_html(toc)}</ul>')
        tabs.append(f'<button data-doc="{key}"><span class="n">{i + 1}</span>{html.escape(title)}</button>')
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skillpm 使用手册</title>
<meta name="description" content="skillpm 命令手册与接入说明，v{__version__}">
<meta name="skillpm-version" content="{__version__}">
<meta name="skillpm-source" content="{source_hash(ROOT)}">
<style>{CSS}</style></head>
<body>
<header><div class="bar">
  <button class="icon-btn menu-btn" id="menu" aria-label="目录">☰</button>
  <div class="brand"><span class="logo">sp</span><span class="name">skillpm 使用手册</span>
  <span class="ver">v{__version__}</span></div>
  <div class="tabs-wrap"><span class="tabs-hint">手册共 {len(DOCS)} 篇 →</span><div class="tabs">{''.join(tabs)}</div></div>
  <div class="sp"></div>
  <button class="icon-btn" id="theme" title="切换深浅色" aria-label="切换深浅色">◐</button>
</div></header>
<div class="wrap">
  <nav class="toc"><input class="search" placeholder="搜目录…" aria-label="搜目录">{''.join(tocs)}
  <ul class="t-all"><li class="l2"><a href="#changelog" id="toc-changelog">更新日志</a></li></ul></nav>
  <main><article>{''.join(docs)}</article>
  <section class="card">{changelog_html()}</section>
  <p class="foot">skillpm v{__version__} · 生成于 {date.today():%Y-%m-%d} · 内容来自工具仓库 docs/ 下的 Markdown，改那里再重新生成</p></main>
</div>
<script>{JS}</script>
</body></html>
"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    # 默认写到 docs/使用手册.html——它随工具一起发，skillpm docs 打开的就是它；要提交
    out = sys.argv[1] if len(sys.argv) > 1 else str(html_path(ROOT))
    print("已生成：", build(out))
