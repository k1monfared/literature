#!/usr/bin/env python3
"""Static builder for the literature site.

Scans LIT_DIR for poets and books and renders a small bilingual static site
into _site/. Folder layout (all optional metadata files fall back to sensible
defaults, so dropping a new folder in is enough):

    literature/
      literature.yml                 site title/tagline (fa/en)
      {poet}/
        poet.yml                     name_fa, name_en, bio_fa, bio_en
        {book}/
          book.yml                   title_fa/en, subtitle_fa/en, reader_fa/en,
                                     description_fa/en, cover, audio
          text.md                    the book text (markdown)
          <cover image>, <audio>     auto-discovered if not named in book.yml

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
TEMPLATE_DIR = LIT_DIR / "templates"
STATIC_DIR = LIT_DIR / "static"

EXCLUDE_DIRS = {"_site", "templates", "static", "scripts", "__pycache__", ".git"}
MD_EXTENSIONS = ["extra", "toc", "sane_lists", "md_in_html"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
AUDIO_EXTS = {".m4a", ".mp3", ".ogg", ".oga", ".wav", ".flac", ".opus", ".aac", ".m4b"}

LABELS = {
    "fa": {
        "poets_heading": "شاعران",
        "books_heading": "کتاب‌ها",
        "book_count": "{n} کتاب",
        "back_home": "فهرست شاعران",
        "back_poet": "فهرست کتاب‌های این شاعر",
        "listen": "شنیدن",
        "wiki_link": "بیشتر در ویکی‌پدیا",
        "lang_switch": "EN",
        "lang_switch_title": "Read this page in English",
        "footer": "مجموعه ادبیات",
    },
    "en": {
        "poets_heading": "Poets",
        "books_heading": "Books",
        "book_count": "{n} book(s)",
        "back_home": "All poets",
        "back_poet": "Back to this poet's books",
        "listen": "Listen",
        "wiki_link": "Read more on Wikipedia",
        "lang_switch": "فا",
        "lang_switch_title": "این صفحه را به فارسی بخوانید",
        "footer": "Literature collection",
    },
}


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


def first_heading(md_text, skip=("فهرست",)):
    for m in re.finditer(r"^##\s+(.+?)\s*#*\s*$", md_text, flags=re.MULTILINE):
        title = re.sub(r"\{#[^}]*\}$", "", m.group(1)).strip()
        if title and title not in skip:
            return title
    return None


def find_books(poet_dir):
    books = []
    for b in sorted(poet_dir.iterdir()):
        if not b.is_dir() or b.name.startswith(".") or b.name in EXCLUDE_DIRS:
            continue
        mds = sorted(b.glob("*.md"))
        if not mds:
            continue
        md_path = b / "text.md" if (b / "text.md").is_file() else mds[0]
        books.append({"slug": b.name, "dir": b, "md": md_path})
    return books


def find_asset(book_dir, exts, preferred_name=None, keyword=None):
    if preferred_name:
        p = book_dir / preferred_name
        if p.is_file():
            return p
    candidates = [f for f in sorted(book_dir.iterdir()) if f.is_file() and f.suffix.lower() in exts]
    if keyword:
        for f in candidates:
            if keyword in f.name.lower():
                return f
    return candidates[0] if candidates else None


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


_DEF_BTN = (
    '<button class="track-play" data-src="{src}" data-start="{start}"'
    ' data-title="{title}" data-poet="{poet}" data-subtitle="{subtitle}"'
    ' data-cover="{cover}" data-href="{href}" aria-label="Play">{icon}</button>'
)


def inject_tracks(html_text, tracks, *, src, poet, subtitle, cover, href, icon="&#9654;"):
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


def md_to_html(text):
    # [ref: URL]  ->  a small source line with a real link
    text = re.sub(r"^\[ref:\s*(\S+?)\]\s*$", r"منبع: <\1>", text, count=1, flags=re.MULTILINE)
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
    return extract_footnotes(md.convert(text))


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
    for d in sorted(LIT_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in EXCLUDE_DIRS:
            continue
        books = find_books(d)
        if not books:
            continue
        meta = load_yaml(d / "poet.yml")
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

    def site_title(lang):
        return site_meta.get(f"title_{lang}") or ("ادبیات" if lang == "fa" else "Literature")

    def tagline(lang):
        return site_meta.get(f"tagline_{lang}") or ""

    def footer(lang):
        return LABELS[lang]["footer"]

    # ---- asset copy + book metadata ----
    for poet in poets:
        for book in poet["books"]:
            bdir = book["dir"]
            bmeta = load_yaml(bdir / "book.yml")
            md_text = book["md"].read_text(encoding="utf-8")
            auto_title = first_heading(md_text)
            media_dir = SITE_DIR / "media" / poet["slug"] / book["slug"]
            cover_src = find_asset(bdir, IMAGE_EXTS, bmeta.get("cover"), keyword="cover")
            audio_src = find_asset(bdir, AUDIO_EXTS, bmeta.get("audio"))
            book["cover"] = copy_asset(cover_src, media_dir, "cover" + cover_src.suffix.lower()) if cover_src else None
            book["audio"] = copy_asset(audio_src, media_dir, "audio" + audio_src.suffix.lower()) if audio_src else None
            book["meta"] = bmeta
            book["auto_title"] = auto_title or book["slug"]
            book["html"] = md_to_html(md_text)

    def book_title(book, lang):
        return book["meta"].get(f"title_{lang}") or book["auto_title"]

    def poet_name(poet, lang):
        return poet["meta"].get(f"name_{lang}") or poet["slug"].replace("_", " ").title()

    # ---- path helpers for the two language trees ----
    def out_home(lang):
        return SITE_DIR / "index.html" if lang == "fa" else SITE_DIR / "en" / "index.html"

    def out_poet(lang, poet):
        base = SITE_DIR if lang == "fa" else SITE_DIR / "en"
        return base / poet["slug"] / "index.html"

    def out_book(lang, poet, book):
        base = SITE_DIR if lang == "fa" else SITE_DIR / "en"
        return base / poet["slug"] / book["slug"] / "index.html"

    def page(lang, out_path, title, content, switch_to, crumb=""):
        home = out_home(lang)
        html_out = render(
            "base.html",
            lang=lang,
            crumb=crumb,
            dir="rtl" if lang == "fa" else "ltr",
            title=title,
            site_title=site_title(lang),
            home_url=rel(out_path, home),
            lang_switch_url=rel(out_path, switch_to),
            lang_switch_label=LABELS[lang]["lang_switch"],
            lang_switch_title=LABELS[lang]["lang_switch_title"],
            style_url=rel(out_path, SITE_DIR / "static" / "style.css"),
            script_url=rel(out_path, SITE_DIR / "static" / "player.js"),
            footnotes_script_url=rel(out_path, SITE_DIR / "static" / "footnotes.js"),
            content=content,
            footer=footer(lang),
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_out, encoding="utf-8")

    # ---- home pages ----
    for lang in ("fa", "en"):
        cards = []
        for poet in sorted(poets, key=lambda p: poet_name(p, lang)):
            poet_out = out_poet(lang, poet)
            href = rel(out_home(lang), poet_out, is_dir=True)
            n = len(poet["books"])
            links = []
            for book in sorted(poet["books"], key=lambda b: book_title(b, lang)):
                links.append(
                    f'<li><a href="{rel(out_home(lang), out_book(lang, poet, book), is_dir=True)}">'
                    f'{html.escape(book_title(book, lang))}</a></li>'
                )
            cards.append(
                '<li class="card poet-card">'
                f'<a class="card-main" href="{href}">'
                f'<span class="card-text"><span class="card-title">{html.escape(poet_name(poet, lang))}</span>'
                f'<span class="card-meta">{LABELS[lang]["book_count"].format(n=n)}</span></span></a>'
                f'<ul class="book-links">{"".join(links)}</ul>'
                "</li>"
            )
        content = render(
            "home.html",
            heading=LABELS[lang]["poets_heading"],
            tagline=tagline(lang),
            items="\n".join(cards),
        )
        page(lang, out_home(lang), site_title(lang), content, out_home("en" if lang == "fa" else "fa"))

    # ---- poet pages ----
    for lang in ("fa", "en"):
        for poet in poets:
            out = out_poet(lang, poet)
            cards = []
            for book in sorted(poet["books"], key=lambda b: book_title(b, lang)):
                thumb = ""
                if book["cover"]:
                    thumb_url = rel(out, book["cover"])
                    thumb = f'<img class="card-thumb" src="{thumb_url}" alt="">'
                sub = book["meta"].get(f"subtitle_{lang}") or ""
                cards.append(
                    f'<li class="card"><a href="{rel(out, out_book(lang, poet, book), is_dir=True)}">'
                    f'{thumb}<span class="card-text"><span class="card-title">{html.escape(book_title(book, lang))}</span>'
                    f'<span class="card-meta">{html.escape(sub)}</span></span></a></li>'
                )
            wiki_url = poet["meta"].get(f"wiki_{lang}") or poet["meta"].get("wiki") or ""
            wiki = ""
            if wiki_url:
                wiki = (
                    f'<p class="bio"><a href="{html.escape(str(wiki_url), quote=True)}"'
                    f' target="_blank" rel="noopener">{LABELS[lang]["wiki_link"]}</a></p>'
                )
            content = render(
                "poet.html",
                name=html.escape(poet_name(poet, lang)),
                wiki=wiki,
                books_heading=LABELS[lang]["books_heading"],
                books="\n".join(cards),
                home_url=rel(out, out_home(lang)),
                back_label=LABELS[lang]["back_home"],
            )
            page(lang, out, f"{poet_name(poet, lang)} — {site_title(lang)}", content,
                 out_poet("en" if lang == "fa" else "fa", poet))

    # ---- book pages ----
    for lang in ("fa", "en"):
        for poet in poets:
            for book in poet["books"]:
                out = out_book(lang, poet, book)
                cover_html = ""
                if book["cover"]:
                    cover_html = (
                        f'<figure class="cover-figure">'
                        f'<img src="{rel(out, book["cover"])}" alt="{html.escape(book_title(book, lang))}">'
                        f"</figure>"
                    )
                src = rel(out, book["audio"]) if book["audio"] else ""
                cover = rel(out, book["cover"]) if book["cover"] else ""
                href = rel(out, out_book(lang, poet, book))
                title = html.escape(book_title(book, lang), quote=True)
                poet_attr = html.escape(poet_name(poet, lang), quote=True)
                subtitle_val = book["meta"].get(f"subtitle_{lang}") or ""
                subtitle = html.escape(subtitle_val, quote=True)
                audio_html = ""
                if book["audio"]:
                    audio_html = (
                        '<div class="book-audio">'
                        f'<button class="play-track" data-src="{src}" data-title="{title}"'
                        f' data-poet="{poet_attr}" data-subtitle="{subtitle}"'
                        f' data-cover="{cover}" data-href="{href}">'
                        f'&#9654; {LABELS[lang]["listen"]}</button>'
                        f'<noscript><audio controls preload="metadata" src="{src}"></audio></noscript>'
                        "</div>"
                    )
                body_html = book["html"]
                tracks = book["meta"].get("tracks") or []
                if book["audio"] and tracks:
                    body_html = inject_tracks(
                        body_html, tracks,
                        src=src, poet=poet_name(poet, lang), subtitle=subtitle_val,
                        cover=cover, href=href,
                    )
                content = render(
                    "book.html",
                    title=html.escape(book_title(book, lang)),
                    subtitle=html.escape(subtitle_val),
                    reader=html.escape(book["meta"].get(f"reader_{lang}") or ""),
                    cover=cover_html,
                    audio=audio_html,
                    body=body_html,
                    poet_url=rel(out, out_poet(lang, poet), is_dir=True),
                    back_label=LABELS[lang]["back_poet"],
                )
                crumb = (
                    f'<span class="sep">/</span>'
                    f'<a href="{rel(out, out_poet(lang, poet), is_dir=True)}">{html.escape(poet_name(poet, lang))}</a>'
                    f'<span class="sep">/</span>'
                    f'<span class="crumb-current">{html.escape(book_title(book, lang))}</span>'
                )
                page(lang, out, f"{book_title(book, lang)} — {site_title(lang)}", content,
                     out_book("en" if lang == "fa" else "fa", poet, book), crumb=crumb)

    n_pages = sum(len(p["books"]) for p in poets) * 2 + len(poets) * 2 + 2
    print(f"Built {len(poets)} poet(s), {sum(len(p['books']) for p in poets)} book(s), {n_pages} pages.")
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
