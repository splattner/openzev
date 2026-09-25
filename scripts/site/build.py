#!/usr/bin/env python3
"""Render the landing page in every language into docs/site/.

    python scripts/site/build.py          # write the pages
    python scripts/site/build.py --check  # fail if the committed pages are stale

German is the default and lives at the site root; the other languages get their
own directory (fr/, it/, en/). The page text is in scripts/site/lang/<code>.json,
the markup in scripts/site/template.html. Values may contain HTML; anything that
ends up inside an attribute must not contain a double quote (checked below).
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "docs" / "site"
BASE = "https://www.openzev.ch/"

DEFAULT = "de"
LANGS = {  # code -> (switcher label, og:locale)
    "de": ("DE", "de_CH"),
    "fr": ("FR", "fr_CH"),
    "it": ("IT", "it_CH"),
    "en": ("EN", "en_GB"),
}
ATTR_KEYS = ("meta_description", "lang_label", "flow_aria")
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def out_path(code: str) -> Path:
    return OUT / "index.html" if code == DEFAULT else OUT / code / "index.html"


def url_for(code: str) -> str:
    return BASE if code == DEFAULT else f"{BASE}{code}/"


def load(code: str) -> dict:
    return json.loads((HERE / "lang" / f"{code}.json").read_text(encoding="utf-8"))


def render(code: str, template: str, text: dict) -> str:
    root = "" if code == DEFAULT else "../"
    hreflang = [
        f'<link rel="alternate" hreflang="{c}" href="{url_for(c)}">' for c in LANGS
    ]
    hreflang.append(f'<link rel="alternate" hreflang="x-default" href="{url_for(DEFAULT)}">')
    switcher = []
    for c, (label, _) in LANGS.items():
        href = (root + ("" if c == DEFAULT else f"{c}/")) or "./"
        current = ' aria-current="page"' if c == code else ""
        switcher.append(
            f'          <a href="{href}" hreflang="{c}" lang="{c}"{current}>{label}</a>'
        )
    values = {
        **text,
        "lang": code,
        "root": root,
        "base": BASE,
        "canonical": url_for(code),
        "og_locale": LANGS[code][1],
        "hreflang_links": "\n".join(hreflang),
        "lang_switcher": "\n".join(switcher),
    }
    missing = set(PLACEHOLDER.findall(template)) - values.keys()
    if missing:
        raise SystemExit(f"{code}: template keys without a value: {sorted(missing)}")
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def main() -> int:
    check = "--check" in sys.argv[1:]
    template = (HERE / "template.html").read_text(encoding="utf-8")
    used = set(PLACEHOLDER.findall(template))
    texts = {code: load(code) for code in LANGS}

    reference = set(texts[DEFAULT])
    for code, text in texts.items():
        if set(text) != reference:
            diff = sorted(set(text) ^ reference)
            raise SystemExit(f"{code}.json and {DEFAULT}.json differ in keys: {diff}")
        for key in ATTR_KEYS:
            if '"' in text[key]:
                raise SystemExit(f'{code}.json: "{key}" is used in an attribute, no double quotes')
    generated = {"lang", "root", "base", "canonical", "og_locale", "hreflang_links", "lang_switcher"}
    unused = reference - (used - generated)
    if unused:
        raise SystemExit(f"keys never used by the template: {sorted(unused)}")

    stale = []
    for code, text in texts.items():
        html = render(code, template, text)
        path = out_path(code)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != html:
                stale.append(path.relative_to(OUT.parent.parent))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            print(f"wrote {path.relative_to(OUT.parent.parent)}")
    if stale:
        print("Stale pages, run `python scripts/site/build.py`:", *stale, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
