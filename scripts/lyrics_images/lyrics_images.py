#!/usr/bin/env python3
"""Generate a consistent dreamlike image strip for a lyric file.

The input is a UTF-8 text file with one lyric line per line. Blank lines are
stanza breaks in the HTML page, but they do not get images. Every non-empty
line gets one square image in lyrics/<song>/images/, plus lyrics/<song>/index.html
with each image placed directly under its lyric line.

The API works without a key (anonymous tier, adds a watermark and is slower).
A registered key removes the watermark and raises the rate limit. Provide it
via POLLINATIONS_API_KEY, secrets/pollinations.key, --key-file, or --key.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://image.pollinations.ai/prompt/"
DEFAULT_TEMPLATE = ROOT / "scripts" / "lyrics_images" / "data" / "prompts" / "lyric_dreamspace.txt"
DEFAULT_KEY_FILE = ROOT / "secrets" / "pollinations.key"
NEGATIVE = (
    "text, letters, words, captions, watermark, logo, signature, bright cheerful "
    "colours, saturated carnival lighting, crowded scene, multiple people, extra "
    "limbs, deformed hands, harsh daylight, sharp modern office"
)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "lyrics"


def title_from_stem(stem: str) -> str:
    words = re.sub(r"[_-]+", " ", stem).strip()
    return words[:1].upper() + words[1:] if words else "Lyric strip"


def read_lyrics(path: Path) -> tuple[list[dict], list[list[dict]]]:
    entries: list[dict] = []
    stanzas: list[list[dict]] = []
    current: list[dict] = []
    stanza = 1
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            if current:
                stanzas.append(current)
                current = []
                stanza += 1
            continue
        entry = {"number": len(entries) + 1, "stanza": stanza, "line": line}
        entries.append(entry)
        current.append(entry)
    if current:
        stanzas.append(current)
    return entries, stanzas


def seed_for(song: str, number: int, line: str) -> int:
    # The image API rejects seeds above the signed 32-bit maximum.
    digest = hashlib.sha1(("%s:%03d:%s" % (song, number, line)).encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) % 2147483647


def build_prompt(template: string.Template, title: str, line: str, number: int, total: int) -> str:
    return template.safe_substitute(
        title=title,
        line=line,
        number=number,
        total=total,
    ).strip()


def image_url(prompt: str, args: argparse.Namespace, seed: int, negative: str) -> str:
    params = {
        "width": args.width,
        "height": args.height,
        "seed": seed,
        "model": args.model,
        "nologo": "true",
        "enhance": "false",
    }
    if negative:
        params["negative_prompt"] = negative
    if args.key:
        params["token"] = args.key
    return ENDPOINT + urllib.parse.quote(prompt) + "?" + urllib.parse.urlencode(params)


def fetch(url: str, key: str | None, attempts: int = 4, base_delay: float = 5.0) -> bytes:
    headers = {"User-Agent": "literature/1.0 (lyric image strip generator)"}
    if key:
        headers["Authorization"] = "Bearer " + key
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if len(data) < 1024:
                raise RuntimeError("response too small, likely an error page")
            return data
        except urllib.error.HTTPError as exc:
            # 429 means the per-IP queue is full, so wait long and steady.
            last_error = exc
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 30.0 * (attempt + 1)
            else:
                wait = base_delay * (2 ** attempt)
            wait += random.uniform(0, 5)
            sys.stderr.write("  retry %d/%d after %s (%.0fs)\n" % (attempt + 1, attempts, exc, wait))
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            wait = base_delay * (2 ** attempt) + random.uniform(0, 2)
            sys.stderr.write("  retry %d/%d after %s (%.0fs)\n" % (attempt + 1, attempts, exc, wait))
            time.sleep(wait)
    raise RuntimeError("giving up: %s" % last_error)


def resolve_key(args: argparse.Namespace) -> str | None:
    if args.key:
        return args.key.strip()
    env = os.environ.get("POLLINATIONS_API_KEY", "").strip()
    if env:
        return env
    key_file = Path(args.key_file)
    if not key_file.is_absolute():
        key_file = ROOT / key_file
    if key_file.is_file():
        value = key_file.read_text(encoding="utf-8").strip()
        return value or None
    return None


def rel(path: Path, start: Path) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def render_html(out_path: Path, title: str, song: str, stanzas: list[list[dict]], model: str) -> None:
    sections: list[str] = []
    for stanza in stanzas:
        parts = ["<section class=\"stanza\">"]
        for entry in stanza:
            line = html.escape(entry["line"])
            src = html.escape(rel(entry["image"], out_path.parent))
            alt = html.escape("Dreamlike illustration for line %d" % entry["number"])
            parts.append(
                "  <figure>\n"
                "    <p class=\"lyric\">%s</p>\n"
                "    <img src=\"%s\" alt=\"%s\" loading=\"lazy\">\n"
                "  </figure>" % (line, src, alt)
            )
        parts.append("</section>")
        sections.append("\n".join(parts))

    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0;
    background: #10131d;
    color: #dfe5f2;
    font-family: Georgia, "Times New Roman", serif;
    line-height: 1.5;
  }}
  main {{
    max-width: 860px;
    margin: 0 auto;
    padding: 48px 20px 72px;
  }}
  h1 {{
    font-size: clamp(2rem, 5vw, 3.4rem);
    font-weight: 400;
    letter-spacing: 0.02em;
    margin: 0 0 8px;
  }}
  .meta {{
    color: #93a0b8;
    font-size: 0.95rem;
    margin-bottom: 40px;
  }}
  .stanza {{
    display: grid;
    gap: 42px;
  }}
  figure {{
    margin: 0;
  }}
  .lyric {{
    font-size: clamp(1.25rem, 3vw, 1.8rem);
    font-style: italic;
    margin: 0 0 14px;
  }}
  img {{
    display: block;
    width: 100%;
    max-width: 760px;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: 18px;
    background: #1a2030;
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.45);
  }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="meta">Song key: {song} · Image model: {model} · Generated locally with Pollinations.AI</p>
  {body}
</main>
</body>
</html>
""".format(
        title=html.escape(title),
        song=html.escape(song),
        model=html.escape(model),
        body="\n\n".join(sections),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one consistent image per lyric line via Pollinations.AI.")
    parser.add_argument("--lyrics", required=True, help="UTF-8 text file, one lyric line per line.")
    parser.add_argument("--song", default="", help="Slug for the output folder (default from --lyrics).")
    parser.add_argument("--out", default="media/lyrics", help="Output root, relative to the repo root (default media/lyrics).")
    parser.add_argument("--title", default="", help="Display title (default from --lyrics).")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Prompt template file.")
    parser.add_argument("--model", default="flux", help="Pollinations image model (default flux).")
    parser.add_argument("--negative", default=NEGATIVE, help="Negative prompt.")
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--delay", type=float, default=6.0, help="Seconds between requests (default 6).")
    parser.add_argument("--attempts", type=int, default=4, help="Retries per image on errors (default 4).")
    parser.add_argument("--backoff", type=float, default=5.0, help="Base seconds for retry backoff (default 5).")
    parser.add_argument("--key", default=None, help="API key (else POLLINATIONS_API_KEY or --key-file).")
    parser.add_argument("--key-file", default=str(DEFAULT_KEY_FILE), help="API key file (default secrets/pollinations.key).")
    parser.add_argument("--force", action="store_true", help="Regenerate even if an image exists.")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts, do not call the API.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N lyric lines.")
    args = parser.parse_args()

    lyrics_path = Path(args.lyrics)
    if not lyrics_path.is_absolute():
        lyrics_path = ROOT / lyrics_path
    if not lyrics_path.is_file():
        raise SystemExit("Lyrics file not found: %s" % lyrics_path)

    song = slugify(args.song or lyrics_path.stem)
    title = args.title.strip() or title_from_stem(lyrics_path.stem)
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = ROOT / template_path
    template = string.Template(template_path.read_text(encoding="utf-8"))
    entries, stanzas = read_lyrics(lyrics_path)
    if args.limit:
        entries = entries[: args.limit]
        stanzas = [[entry for entry in stanza if entry["number"] <= args.limit] for stanza in stanzas]
        stanzas = [stanza for stanza in stanzas if stanza]

    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    song_dir = out_root / song
    image_dir = song_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    key = resolve_key(args)
    if not key:
        print("No API key found, using the anonymous tier (watermark, lower limits).")

    total = len(entries)
    print("Generating %d image(s), song=%s, model=%s, %dx%d" % (total, song, args.model, args.width, args.height))

    made = skipped = failed = 0
    for index, entry in enumerate(entries):
        number = entry["number"]
        line = entry["line"]
        prompt = build_prompt(template, title, line, number, total)
        entry["prompt"] = prompt
        entry["seed"] = seed_for(song, number, line)
        entry["image"] = image_dir / ("%s-%03d.jpg" % (song, number))

        if args.dry_run:
            print("\n[%03d/%03d] %s\n%s" % (number, total, line, prompt))
            continue

        target = entry["image"]
        if target.is_file() and not args.force:
            skipped += 1
            continue
        url = image_url(prompt, args, entry["seed"], args.negative)
        sys.stderr.write("[%03d/%03d] line %03d\n" % (index + 1, total, number))
        try:
            data = fetch(url, key, attempts=args.attempts, base_delay=args.backoff)
        except RuntimeError as exc:
            failed += 1
            sys.stderr.write("  FAILED line %03d: %s\n" % (number, exc))
            continue
        target.write_bytes(data)
        made += 1
        if index + 1 < total:
            time.sleep(args.delay)

    html_path = song_dir / "index.html"
    manifest_path = song_dir / "manifest.json"
    render_html(html_path, title, song, stanzas, args.model)
    manifest = {
        "title": title,
        "song": song,
        "lyrics": rel(lyrics_path, ROOT),
        "model": args.model,
        "width": args.width,
        "height": args.height,
        "html": rel(html_path, ROOT),
        "entries": [
            {
                "number": entry["number"],
                "stanza": entry["stanza"],
                "line": entry["line"],
                "seed": entry["seed"],
                "image": rel(entry["image"], ROOT),
                "prompt": entry["prompt"],
            }
            for entry in entries
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not args.dry_run:
        print("Done. %d generated, %d skipped, %d failed." % (made, skipped, failed))
    print("HTML: %s" % rel(html_path, ROOT))
    print("Manifest: %s" % rel(manifest_path, ROOT))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
