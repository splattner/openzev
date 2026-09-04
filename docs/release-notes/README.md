# Release notes

The user-facing notes that sit above release-please's generated change list on
each GitHub release.

Release-please produces the complete list of what changed. It cannot say which
of those changes matter to someone running a ZEV, and its titles are written
for the person who made the change. These files are the part that has to be
written by hand.

- One file per release, `<version>.md`, holding the prose only.
- Drafted and reviewed here, then prepended to the `v<version>` GitHub release
  body when the release is cut. `CHANGELOG.md` stays purely release-please's
  output — anything hand-written there is wiped by the next merge to `main`.
- The state block at the foot of each file records which PRs were judged and
  how, including the ones deliberately left out, so a draft can be picked up
  later or by someone else.

## Screenshots

`screenshots/` holds the images the notes embed, named `<version>-<slug>.png`.
They are **frozen artefacts**: a 1.9.0 image documents the 1.9.0 UI, so it is
never regenerated — re-shooting it against a later UI would illustrate that
release with a product it never shipped. This is the opposite of
`docs/user-guide/screenshots/`, which is regenerated as a set whenever the
interface moves.

Capture a UI shot with `npm run shot` from `frontend/` (see the header of
`frontend/screenshots/shot.spec.ts`). For a figure from a generated document,
render the PDF from a throwaway test and crop it with
`scripts/crop-pdf-figure.py`, which finds the line-item table by its header
bar so a before/after pair lines up exactly. Reference it from the draft with a path
relative to the draft — `screenshots/x.png` — which is correct in the repo and
in review; `scripts/release-notes-body.mjs` rewrites it to a tag-pinned
absolute URL at publish time, because a release body resolves relative paths
against the repository root rather than against this directory.

Written with the `release-notes` skill (`.claude/skills/release-notes/`), which
carries the triage rules and the house voice.

v1.7.0 and earlier predate this directory; their notes exist only on the GitHub
releases.
