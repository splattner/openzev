"""MkDocs hooks for the user guide site (see mkdocs.yml).

The chapters in docs/user-guide/ link to a few files outside it — the root
README, the Helm chart README, specs. Those resolve on GitHub but not on the
published site, so rewrite them to their GitHub URL at build time instead of
changing the Markdown.
"""

import posixpath
import re

GITHUB_BLOB = "https://github.com/splattner/openzev/blob/main/"
DOCS_DIR = "docs/user-guide"

# A Markdown link target that climbs out of the docs directory: ](../...)
OUTSIDE_LINK = re.compile(r"\]\((\.\./[^)\s]+)\)")


def _to_github(match: re.Match, page_dir: str) -> str:
    target, _, fragment = match.group(1).partition("#")
    repo_path = posixpath.normpath(posixpath.join(page_dir, target))
    url = GITHUB_BLOB + repo_path + (f"#{fragment}" if fragment else "")
    return f"]({url})"


def on_page_markdown(markdown, page, config, files):
    page_dir = posixpath.join(DOCS_DIR, posixpath.dirname(page.file.src_uri))
    return OUTSIDE_LINK.sub(lambda m: _to_github(m, page_dir), markdown)
