#!/usr/bin/env python3
"""
generate_emoji_shortcodes.py

Regenerates bin/emoji_shortcodes.json from iamcal/emoji-data (MIT licensed)
-- not part of the bot's runtime path, run this by hand if Slack starts
sending a shortcode that still doesn't convert and emoji-data has since
added it. See the "Emoji shortcodes" note in CLAUDE.md for why this
dataset, not the `emoji` PyPI package, is the source of truth here: its
`short_names` match Slack's own shortcode naming directly (same hyphens,
same "male-cook"/"woman-shrugging"/"flag-la" style), since Slack's emoji
picker is historically built on this same dataset.

    uv run bin/generate_emoji_shortcodes.py
"""
import json
import urllib.request
from pathlib import Path

SOURCE_COMMIT = "13ee711e222ea17fe537bfea953c687866f16411"
SOURCE_URL = f"https://raw.githubusercontent.com/iamcal/emoji-data/{SOURCE_COMMIT}/emoji.json"
OUTPUT_PATH = Path(__file__).parent / "emoji_shortcodes.json"

# Slack's ":skin-tone-N:" digits (2-6, Fitzpatrick scale II-VI) map to
# these modifier codepoints -- emoji-data's skin_variations are keyed by
# the modifier's own hex, not Slack's digit, so this bridges the two.
SKIN_TONE_DIGIT_TO_MODIFIER_HEX = {
    "2": "1F3FB", "3": "1F3FC", "4": "1F3FD", "5": "1F3FE", "6": "1F3FF",
}


def main() -> None:
    with urllib.request.urlopen(SOURCE_URL) as resp:
        data = json.load(resp)

    shortcodes = {}
    for entry in data:
        unified = entry.get("unified")
        if not unified:
            continue
        skin_variations = entry.get("skin_variations") or {}
        tones = {
            digit: skin_variations[hex_code]["unified"]
            for digit, hex_code in SKIN_TONE_DIGIT_TO_MODIFIER_HEX.items()
            if hex_code in skin_variations
        }
        record = {"unified": unified}
        if tones:
            record["tones"] = tones
        for name in entry.get("short_names", []):
            shortcodes[name] = record

    OUTPUT_PATH.write_text(json.dumps(shortcodes, indent=1, sort_keys=True) + "\n")
    print(f"Wrote {len(shortcodes)} shortcodes to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
