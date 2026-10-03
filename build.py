#!/usr/bin/env python3
"""Static builder for the literature site.

Scans LIT_DIR for poets and books and renders a small bilingual static site
into _site/. Folder layout (all optional metadata files fall back to sensible
defaults, so dropping a new folder in is enough):

    literature/
      literature.yml                 site title/tagline (fa/en)
      creators/{creator}/            URL slug = folder name
        creator.yml                  name_fa, name_en, wiki, lang (poet.yml also read)
        {work}/                      URL slug = folder name
          work.yml                   title_fa/en, subtitle, reader, description,
                                     cover, audio, tracks (book.yml also read)
          text.md                    the work text (markdown)
          assets/                    cover, audio, source PDF, other files
          media/                     generated per-work output (gitignored)
      site/                          templates/ + static/ for the generator
      scripts/                       tooling, each self-contained

Usage:
    python build.py
    python build.py --serve [--port 8000]
"""

import argparse
import functools
import html
import http.server
import os
import re
import shutil
import socket
import sys
from pathlib import Path

import yaml
import markdown

LIT_DIR = Path(__file__).resolve().parent
SITE_DIR = LIT_DIR / "_site"
CREATORS_DIR = LIT_DIR / "creators"
TEMPLATE_DIR = LIT_DIR / "site" / "templates"
STATIC_DIR = LIT_DIR / "site" / "static"

EXCLUDE_DIRS = {
    "_site", "site", "templates", "static", "scripts", "creators", "secrets",
    "media", "assets", "__pycache__", ".git",
}
MD_EXTENSIONS = ["extra", "toc", "sane_lists", "md_in_html"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
AUDIO_EXTS = {".m4a", ".mp3", ".ogg", ".oga", ".wav", ".flac", ".opus", ".aac", ".m4b"}

# UI strings as (fa, en) pairs. Both languages are embedded in each page and
# the language button swaps them client-side.
STRINGS = {
    "authors": ("پدیدآورندگان", "Authors"),
    "works": ("آثار", "Works"),
    "work_count": ("{n} اثر", "{n} work(s)"),
    "all_authors": ("همهٔ پدیدآورندگان", "All authors"),
    "back_works": ("بازگشت به آثار این پدیدآورنده", "Back to this author's works"),
    "listen": ("شنیدن", "Listen"),
    "wiki": ("بیشتر در ویکی‌پدیا", "Read more on Wikipedia"),
    "footer": ("مجموعه ادبیات", "Literature collection"),
}


def bi(fa, en):
    """Return both language variants; CSS/JS show the active one."""
    fa = "" if fa is None else str(fa)
    en = "" if en is None else str(en)
    return (
        f'<span data-lang="fa">{html.escape(fa)}</span>'
        f'<span data-lang="en">{html.escape(en)}</span>'
    )


def work_count(n, lang):
    fa, en = STRINGS["work_count"]
    return (fa if lang == "fa" else en).format(n=n)


def unicode_slugify(value, separator="-"):
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s]+", separator, value)


def load_yaml(path):
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}
    except Exception as exc:  # pragma: no cover
        print(f"  ! could not parse {path.name}: {exc}", file=sys.stderr)
        return {}


def content_dir(text):
    """Pick a text direction for a work from its dominant script."""
    persian = len(re.findall(r"[\u0600-\u06FF]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "rtl" if persian >= latin else "ltr"


def first_heading(md_text, skip=("فهرست",)):
    for m in re.finditer(r"^#{1,2}\s+(.+?)\s*#*\s*$", md_text, flags=re.MULTILINE):
        title = re.sub(r"\{#[^}]*\}$", "", m.group(1)).strip()
        if title and title not in skip:
            return title
    return None


def _first_meta(directory, names):
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return directory / names[0]


def find_books(poet_dir):
    """A work is a subfolder containing markdown (with an optional assets/
    folder), or a markdown file directly in the creator folder."""
    books = []
    for b in sorted(poet_dir.iterdir()):
        if not b.is_dir() or b.name.startswith(".") or b.name in EXCLUDE_DIRS:
            continue
        mds = sorted(b.glob("*.md"))
        if not mds:
            continue
        md_path = b / "text.md" if (b / "text.md").is_file() else mds[0]
        books.append({
            "slug": b.name,
            "dir": b,
            "md": md_path,
            "meta_path": _first_meta(b, ["work.yml", "book.yml"]),
        })
    for f in sorted(poet_dir.glob("*.md")):
        if f.name.startswith("."):
            continue
        books.append({
            "slug": f.stem,
            "dir": poet_dir,
            "md": f,
            "meta_path": _first_meta(poet_dir, [f.stem + ".yml", "work.yml", "book.yml"]),
        })
    return books


def find_asset(book_dir, exts, preferred_name=None, keyword=None):
    if preferred_name:
        preferred = book_dir / preferred_name
        if preferred.is_file():
            return preferred
    files = []
    for d in (book_dir, book_dir / "assets"):
        if d.is_dir():
            files += [f for f in sorted(d.iterdir()) if f.is_file() and f.suffix.lower() in exts]
    if keyword:
        for f in files:
            if keyword in f.name.lower():
                return f
    return files[0] if files else None


def copy_asset(src, dest_dir, dest_name):
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    if dest.is_file():
        s, d = src.stat(), dest.stat()
        if s.st_size == d.st_size and int(s.st_mtime) <= int(d.st_mtime):
            return dest
    shutil.copy2(src, dest)
    return dest


FN_PARA_RE = re.compile(r'<p>\s*<a id="(fn-[\w-]+)"></a>(.*?)</p>', re.DOTALL)
FN_REF_RE = re.compile(r'<a href="#(fn-[\w-]+)">')


def extract_footnotes(html):
    """Pull the glossary lines out of the flow and turn them into hidden
    definitions that the in-text links reveal as a popup."""
    defs = []

    def repl(match):
        fid, inner = match.group(1), match.group(2)
        headword = ""
        link = re.match(r'\s*<a href="#w-[\w-]+">(.*?)</a>', inner, re.DOTALL)
        if link:
            headword = link.group(1).strip()
            inner = inner[link.end():]
        idx = inner.find(" = ")
        sep = 3
        if idx == -1:
            idx = inner.find(": ")
            sep = 2
        if idx == -1:
            before, body = "", inner.strip()
        else:
            before, body = inner[:idx].strip(), inner[idx + sep:].strip()
        title = before or headword
        content = f'<b class="fn-term">{title}</b> {body}' if title else body
        defs.append(f'<span class="fn-def" id="{fid}">{content}</span>')
        return ""

    out = FN_PARA_RE.sub(repl, html)
    out = FN_REF_RE.sub(
        lambda m: f'<a class="fnref" data-fn="{m.group(1)}" href="#{m.group(1)}">', out
    )
    if defs:
        out += '\n<div class="footnotes" hidden>' + "".join(defs) + "</div>"
    return out


def parse_time(value):
    """Accept seconds (int/str) or 'M:SS' / 'H:MM:SS' and return seconds."""
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    parts = s.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


_SVG_PLAY = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
    '<path d="M8 5v14l11-7z"/></svg>'
)

_DEF_BTN = (
    '<button class="track-play" data-src="{src}" data-start="{start}"'
    ' data-title="{title}" data-poet="{poet}" data-subtitle="{subtitle}"'
    ' data-cover="{cover}" data-href="{href}" aria-label="Play">{icon}</button>'
)


def inject_tracks(html_text, tracks, *, src, poet, subtitle, cover, href,
                  icon='<span class="ico">' + _SVG_PLAY + "</span>"):
    """Add a play button next to each poem title (and its TOC entry) that seeks
    the shared player to that poem's timestamp. `tracks` items are either a
    time string (matched to poems in order) or a dict with start/title/anchor."""
    heads = re.findall(
        r'<p>\s*<a id="(poem-\d+)"></a>\s*</p>\s*<h2[^>]*>(.*?)</h2>',
        html_text,
        re.DOTALL,
    )
    if not heads:
        return html_text
    order = [h[0] for h in heads]

    def norm(s):
        return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", s))

    title_by_anchor = {h[0]: norm(h[1]) for h in heads}
    text_by_anchor = {h[0]: re.sub(r"<[^>]+>", "", h[1]).strip() for h in heads}

    resolved = []
    used = set()
    auto = 0
    for item in tracks:
        if isinstance(item, dict):
            start = parse_time(item.get("start"))
            anchor = item.get("anchor")
            title = item.get("title")
        else:
            start, anchor, title = parse_time(item), None, None
        if start is None:
            continue
        if not anchor and title:
            want = norm(str(title))
            for a, t in title_by_anchor.items():
                if t == want and a not in used:
                    anchor = a
                    break
        if not anchor:
            while auto < len(order) and order[auto] in used:
                auto += 1
            if auto < len(order):
                anchor = order[auto]
                auto += 1
        if not anchor or anchor in used:
            continue
        used.add(anchor)
        resolved.append((anchor, start))

    for anchor, start in resolved:
        btn = _DEF_BTN.format(
            src=src,
            start=start,
            title=html.escape(text_by_anchor.get(anchor, ""), quote=True),
            poet=html.escape(poet, quote=True),
            subtitle=html.escape(subtitle, quote=True),
            cover=cover,
            href=href,
            icon=icon,
        )
        html_text = re.sub(
            r'(<p>\s*<a id="%s"></a>\s*</p>\s*<h2[^>]*>)(.*?)(</h2>)' % re.escape(anchor),
            lambda m: m.group(1) + m.group(2) + " " + btn + m.group(3),
            html_text,
            count=1,
            flags=re.DOTALL,
        )
        html_text = re.sub(
            r'(<li><a href="#%s">.*?</a>)' % re.escape(anchor),
            lambda m: m.group(1) + " " + btn,
            html_text,
            count=1,
            flags=re.DOTALL,
        )
    return html_text


def link_headings(html_text):
    """Make each poem heading a link to its own anchor so the URL hash updates."""
    def repl(m):
        anchor, attrs, content = m.group(1), m.group(2), m.group(3)
        return (
            f'<p><a id="{anchor}"></a></p>'
            f'<h2{attrs}><a class="heading-link" href="#{anchor}">{content}</a></h2>'
        )

    return re.sub(
        r'<p>\s*<a id="(poem-\d+)"></a>\s*</p>\s*<h2([^>]*)>(.*?)</h2>',
        repl,
        html_text,
        flags=re.DOTALL,
    )


def md_to_html(text):
    # ![caption](file.m4a)  ->  <audio>
    def media(match):
        cap = match.group(1).strip()
        src = match.group(2).strip()
        ext = os.path.splitext(src)[1].lower()
        if ext in AUDIO_EXTS:
            cap_html = f"<figcaption>{html.escape(cap)}</figcaption>" if cap else ""
            return (
                f'<figure class="audio-figure"><audio controls preload="metadata" '
                f'src="{html.escape(src, quote=True)}"></audio>{cap_html}</figure>'
            )
        return match.group(0)
    text = re.sub(r"^!\[([^\]]*)\]\(<?([^)>\s]+)>?\)\s*$", media, text, flags=re.MULTILINE)
    md = markdown.Markdown(
        extensions=MD_EXTENSIONS,
        extension_configs={"toc": {"slugify": unicode_slugify}},
    )
    return link_headings(extract_footnotes(md.convert(text)))


def rel(from_out, to_out, is_dir=False):
    to_out = str(to_out)
    if is_dir and to_out.endswith("/index.html"):
        to_out = to_out[: -len("/index.html")]
    r = os.path.relpath(to_out, str(from_out.parent)).replace(os.sep, "/")
    if is_dir and not r.endswith("/"):
        r += "/"
    return r


def render(template_name, **kw):
    tpl = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for key, val in kw.items():
        tpl = tpl.replace("{{" + key + "}}", str(val))
    return tpl


def discover():
    site_meta = load_yaml(LIT_DIR / "literature.yml")
    poets = []
    if not CREATORS_DIR.is_dir():
        return site_meta, poets
    for d in sorted(CREATORS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in EXCLUDE_DIRS:
            continue
        books = find_books(d)
        if not books:
            continue
        meta = load_yaml(d / "creator.yml") or load_yaml(d / "poet.yml")
        poets.append({"slug": d.name, "dir": d, "meta": meta, "books": books})
    return site_meta, poets


def build():
    site_meta, poets = discover()
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    (SITE_DIR / "static").mkdir(parents=True, exist_ok=True)
    for asset in STATIC_DIR.iterdir():
        if asset.is_file():
            shutil.copy2(asset, SITE_DIR / "static" / asset.name)
    # Publish generated per-work media (e.g. lyric visual pages) under /lyrics/
    # so their URLs stay stable regardless of where they live in the source.
    lyrics_out = SITE_DIR / "lyrics"
    for poet in poets:
        for book in poet["books"]:
            media = book["dir"] / "media"
            if not media.is_dir():
                continue
            lyrics_out.mkdir(parents=True, exist_ok=True)
            for item in sorted(media.iterdir()):
                if item.name.startswith("."):
                    continue
                dest = lyrics_out / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

    site_fa = site_meta.get("title_fa") or "ادبیات"
    site_en = site_meta.get("title_en") or "Literature"
    site_default = site_meta.get("default_lang") or "fa"

    # ---- assets + work metadata ----
    for poet in poets:
        for book in poet["books"]:
            bdir = book["dir"]
            bmeta = load_yaml(book.get("meta_path") or (bdir / "book.yml"))
            md_text = book["md"].read_text(encoding="utf-8")
            auto_title = first_heading(md_text) or book["slug"]
            media_dir = SITE_DIR / "media" / poet["slug"] / book["slug"]
            cover_src = find_asset(bdir, IMAGE_EXTS, bmeta.get("cover"), keyword="cover")
            audio_src = find_asset(bdir, AUDIO_EXTS, bmeta.get("audio"))
            book["cover"] = copy_asset(cover_src, media_dir, "cover" + cover_src.suffix.lower()) if cover_src else None
            book["audio"] = copy_asset(audio_src, media_dir, "audio" + audio_src.suffix.lower()) if audio_src else None
            book["meta"] = bmeta
            book["auto_title"] = auto_title
            book["content_dir"] = content_dir(md_text)
            book["html"] = md_to_html(md_text)

    def poet_name(poet):
        meta = poet["meta"]
        slug = poet["slug"].replace("_", " ").title()
        return meta.get("name_fa") or slug, meta.get("name_en") or slug

    def book_title(book):
        meta = book["meta"]
        return meta.get("title_fa") or book["auto_title"], meta.get("title_en") or book["auto_title"]

    def book_field(book, field):
        meta = book["meta"]
        return meta.get(f"{field}_fa") or "", meta.get(f"{field}_en") or ""

    def poet_lang(poet):
        return poet["meta"].get("lang") or site_default

    def book_lang(book):
        return book["meta"].get("lang") or ("fa" if book["content_dir"] == "rtl" else "en")

    def out_home():
        return SITE_DIR / "index.html"

    def out_poet(poet):
        return SITE_DIR / poet["slug"] / "index.html"

    def out_book(poet, book):
        return SITE_DIR / poet["slug"] / book["slug"] / "index.html"

    def page(out_path, title_fa, title_en, content, default_lang, crumb=""):
        html_out = render(
            "base.html",
            lang=default_lang,
            dir="rtl" if default_lang == "fa" else "ltr",
            title=title_fa if default_lang == "fa" else title_en,
            title_fa=html.escape(title_fa, quote=True),
            title_en=html.escape(title_en, quote=True),
            site_title=bi(site_fa, site_en),
            home_url=rel(out_path, out_home()),
            crumb=crumb,
            style_url=rel(out_path, SITE_DIR / "static" / "style.css"),
            script_url=rel(out_path, SITE_DIR / "static" / "player.js"),
            footnotes_script_url=rel(out_path, SITE_DIR / "static" / "footnotes.js"),
            lang_script_url=rel(out_path, SITE_DIR / "static" / "lang.js"),
            content=content,
            footer=bi(*STRINGS["footer"]),
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_out, encoding="utf-8")

    # ---- home ----
    cards = []
    for poet in sorted(poets, key=lambda p: poet_name(p)[0]):
        fa, en = poet_name(poet)
        n = len(poet["books"])
        links = []
        for book in sorted(poet["books"], key=lambda b: book_title(b)[0]):
            bfa, ben = book_title(book)
            links.append(
                f'<li><a href="{rel(out_home(), out_book(poet, book), is_dir=True)}">{bi(bfa, ben)}</a></li>'
            )
        cards.append(
            '<li class="card poet-card">'
            f'<a class="card-main" href="{rel(out_home(), out_poet(poet), is_dir=True)}">'
            f'<span class="card-text"><span class="card-title">{bi(fa, en)}</span>'
            f'<span class="card-meta">{bi(work_count(n, "fa"), work_count(n, "en"))}</span></span></a>'
            f'<ul class="book-links">{"".join(links)}</ul>'
            "</li>"
        )
    content = render(
        "home.html",
        heading=bi(*STRINGS["authors"]),
        tagline=bi(site_meta.get("tagline_fa") or "", site_meta.get("tagline_en") or ""),
        items="\n".join(cards),
    )
    page(out_home(), site_fa, site_en, content, site_default)

    # ---- author pages ----
    for poet in poets:
        out = out_poet(poet)
        fa, en = poet_name(poet)
        cards = []
        for book in sorted(poet["books"], key=lambda b: book_title(b)[0]):
            bfa, ben = book_title(book)
            thumb = f'<img class="card-thumb" src="{rel(out, book["cover"])}" alt="">' if book["cover"] else ""
            sfa, sen = book_field(book, "subtitle")
            cards.append(
                f'<li class="card"><a href="{rel(out, out_book(poet, book), is_dir=True)}">'
                f'{thumb}<span class="card-text"><span class="card-title">{bi(bfa, ben)}</span>'
                f'<span class="card-meta">{bi(sfa, sen)}</span></span></a></li>'
            )
        wiki_parts = []
        wfa = poet["meta"].get("wiki_fa") or poet["meta"].get("wiki") or ""
        wen = poet["meta"].get("wiki_en") or poet["meta"].get("wiki") or ""
        if wfa:
            wiki_parts.append(
                f'<span data-lang="fa"><a href="{html.escape(str(wfa), quote=True)}" target="_blank" rel="noopener">{html.escape(STRINGS["wiki"][0])}</a></span>'
            )
        if wen:
            wiki_parts.append(
                f'<span data-lang="en"><a href="{html.escape(str(wen), quote=True)}" target="_blank" rel="noopener">{html.escape(STRINGS["wiki"][1])}</a></span>'
            )
        wiki = f'<p class="bio">{"".join(wiki_parts)}</p>' if wiki_parts else ""
        content = render(
            "poet.html",
            name=bi(fa, en),
            wiki=wiki,
            books_heading=bi(*STRINGS["works"]),
            books="\n".join(cards),
            home_url=rel(out, out_home()),
            back_label=bi(*STRINGS["all_authors"]),
        )
        page(out, f"{fa} — {site_fa}", f"{en} — {site_en}", content, poet_lang(poet))

    # ---- work pages ----
    for poet in poets:
        pfa, pen = poet_name(poet)
        for book in poet["books"]:
            out = out_book(poet, book)
            tfa, ten = book_title(book)
            sfa, sen = book_field(book, "subtitle")
            rfa, ren = book_field(book, "reader")
            src = rel(out, book["audio"]) if book["audio"] else ""
            cover = rel(out, book["cover"]) if book["cover"] else ""
            href = rel(out, out_book(poet, book))
            native_fa = book["content_dir"] == "rtl"
            display_title = tfa if native_fa else ten
            display_poet = pfa if native_fa else pen
            display_sub = sfa if native_fa else sen
            cover_html = (
                f'<figure class="cover-figure"><img src="{cover}" alt="{html.escape(ten, quote=True)}"></figure>'
                if book["cover"] else ""
            )
            audio_html = ""
            if book["audio"]:
                audio_html = (
                    '<div class="book-audio">'
                    f'<button class="play-track" data-src="{src}" data-title="{html.escape(display_title, quote=True)}"'
                    f' data-poet="{html.escape(display_poet, quote=True)}" data-subtitle="{html.escape(display_sub, quote=True)}"'
                    f' data-cover="{cover}" data-href="{href}">'
                    f'<span class="ico">{_SVG_PLAY}</span>'
                    f'<span class="lbl">{bi(*STRINGS["listen"])}</span></button>'
                    f'<noscript><audio controls preload="metadata" src="{src}"></audio></noscript>'
                    "</div>"
                )
            body_html = book["html"]
            tracks = book["meta"].get("tracks") or []
            if book["audio"] and tracks:
                body_html = inject_tracks(
                    body_html, tracks, src=src, poet=display_poet,
                    subtitle=display_sub, cover=cover, href=href,
                )
            content = render(
                "book.html",
                title=bi(tfa, ten),
                subtitle=bi(sfa, sen),
                reader=bi(rfa, ren),
                cover=cover_html,
                audio=audio_html,
                body=body_html,
                body_dir=book["content_dir"],
                poet_url=rel(out, out_poet(poet), is_dir=True),
                back_label=bi(*STRINGS["back_works"]),
            )
            crumb = (
                '<span class="crumb"><span class="sep">/</span>'
                f'<a href="{rel(out, out_poet(poet), is_dir=True)}">{bi(pfa, pen)}</a>'
                '<span class="sep">/</span>'
                f'<span class="crumb-current">{bi(tfa, ten)}</span></span>'
            )
            page(out, f"{tfa} — {site_fa}", f"{ten} — {site_en}", content, book_lang(book), crumb=crumb)

    n_poets = len(poets)
    n_works = sum(len(p["books"]) for p in poets)
    print(f"Built {n_poets} author(s), {n_works} work(s), {n_poets + n_works + 1} pages.")
    print(f"Output: {SITE_DIR}")


def find_free_port(preferred):
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


class RangeRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with byte-range support (for audio/video seeking)."""

    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            path = self.translate_path(self.path)
            if os.path.isfile(path):
                self._serve_range(path, rng)
                return
        super().do_GET()

    def _serve_range(self, path, rng):
        size = os.path.getsize(path)
        match = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if not match:
            self.send_error(400, "Invalid Range")
            return
        start = int(match.group(1)) if match.group(1) else 0
        end = int(match.group(2)) if match.group(2) else size - 1
        if start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionResetError, BrokenPipeError):
            pass


def serve(preferred_port):
    port = find_free_port(preferred_port)
    handler = functools.partial(RangeRequestHandler, directory=str(SITE_DIR))
    httpd = http.server.ThreadingHTTPServer(("", port), handler)
    ip = lan_ip()
    print(f"Serving {SITE_DIR}")
    if port != preferred_port:
        print(f"(port {preferred_port} was busy, using {port})")
    print(f"  local: http://localhost:{port}/")
    if ip:
        print(f"  LAN:   http://{ip}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    ap = argparse.ArgumentParser(description="Build the literature static site")
    ap.add_argument("--serve", action="store_true", help="serve _site/ after building")
    ap.add_argument("--port", type=int, default=8000, help="preferred port for --serve")
    args = ap.parse_args()
    build()
    if args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
