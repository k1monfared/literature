#!/usr/bin/env bash
# Generate a consistent image strip for a lyric file with Pollinations.AI.
# Input is a plain text file, one lyric line per line. Blank lines split stanzas
# in the HTML page, but they do not get their own images.
#
# Usage:
#   scripts/lyrics_images/generate_lyrics.sh --lyrics scripts/lyrics_images/data/lyrics/windmills_first_stanza.txt
#   scripts/lyrics_images/generate_lyrics.sh --lyrics scripts/lyrics_images/data/lyrics/windmills_first_stanza.txt --dry-run
#   scripts/lyrics_images/generate_lyrics.sh --lyrics scripts/lyrics_images/data/lyrics/windmills_first_stanza.txt --force
# An explicit --out overrides the default (later argparse values win).
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scripts/lyrics_images/lyrics_images.py --out creators/alan_and_marilyn_bergman/lyrics/media "$@"
