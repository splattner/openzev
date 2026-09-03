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

Written with the `release-notes` skill (`.claude/skills/release-notes/`), which
carries the triage rules and the house voice.

v1.7.0 and earlier predate this directory; their notes exist only on the GitHub
releases.
