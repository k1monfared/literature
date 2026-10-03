#!/usr/bin/env bash
# Generate a consistent image strip for a lyric file with Pollinations.AI.
# Input is a plain text file, one lyric line per line. Blank lines split stanzas
# in the HTML page, but they do not get their own images.
#
# Usage:
#   scripts/generate_lyrics.sh --lyrics scripts/lyrics/windmills_first_stanza.txt
#   scripts/generate_lyrics.sh --lyrics scripts/lyrics/windmills_first_stanza.txt --dry-run
#   scripts/generate_lyrics.sh --lyrics scripts/lyrics/windmills_first_stanza.txt --force
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/lyrics_images.py "$@"
