---
name: release-notes
description: Draft, continue, or publish the user-facing release notes that sit above release-please's generated change list on a GitHub release. Use when preparing a release, when asked to write or update release notes, or when asked what a release should tell users.
---

# Release notes

Release-please already produces the complete change list. It cannot say which
of those changes a ZEV operator should care about, and its titles are written
for the person who made the change rather than the person who has to use it.
These notes are the part that has to be written.

They go **above** the generated list on the GitHub release, with the generated
list demoted under `## Full change list`. `CHANGELOG.md` stays purely
release-please's output — nothing hand-written goes there, because every merge
to `main` regenerates it.

## Three modes

Read the argument. With no argument, work out which applies from the state on
disk.

| Mode | When | What it does |
|---|---|---|
| `draft <version>` | No `docs/release-notes/<version>.md` yet | Build the change list, triage it, write the file |
| `continue [<version>]` | The file exists and the release has not been cut | Re-derive the change list, triage only what is new, update the file |
| `publish <version>` | The release exists on GitHub | Prepend the file's contents to the release body |

Drafting and publishing are necessarily separate: the GitHub release does not
exist until release-please's PR is merged, so there is nothing to publish into
until the release is cut. That is also why the draft lives in the repo rather
than in the release-please PR body, which is regenerated on every merge.

## 1. Build the change list

**Read it from the release-please PR, not from `git log`.** That PR is the
authoritative set for the release being prepared, and it already resolves
squash subjects to PR numbers.

```
gh pr list --state open --search "chore(main): release" --json number,title
gh pr view <number> --json body -q .body
```

Take the version from the PR title (`chore(main): release 1.8.0`).

Then check whether the release is actually ready:

```
gh pr list --state open --json number,title,labels
```

Anything open that is meant for this release — a headline feature especially —
means the change list is not final. Say so in the draft and to the user; do not
quietly write notes for a release that is still moving.

`git log v<previous>..origin/main --oneline` is a cross-check, not the source.
It will disagree with the PR where a squash subject was lost or re-recorded, and
the PR is right.

## 2. Triage by user impact

This is the whole job. Most of the change list does not belong in the notes at
all.

For each change, ask: **would someone running a ZEV do something new, or
something differently, because of this?**

**A headline feature is usually several PRs.** Shared metering points in 1.8.0
was five (#460, #461, #462, #463, #464) plus supporting fixes; the notes have
one section, written around the capability. Group first, then triage the group
— triaging PR by PR produces a list of implementation steps instead of a
description of what someone can now do.

**Its own `###` section** — yes, and they need to be told how. Something
previously impossible is now possible, or a workflow changes shape. These get a
few paragraphs: what it does, where it is in the UI, what it costs, and what it
deliberately does *not* do. Two to five per release; more than five means the
triage is too generous.

**`### Also new`** — yes, but it needs no explanation. One line each. A better
default, a new filter, a term corrected in a translation.

**`### Fixes worth knowing about`** — a bug that produced wrong numbers, lost
data, blocked a workflow, or crossed a tenant boundary. The test is whether
someone might need to go and check their own data. Name the symptom first, then
the cause: the reader is trying to work out whether it affected them.

**`### Under the hood`** — refactors, new internal structure, test and CI work.
One short paragraph for the whole release, or leave the section out. Include it
only where it explains why something is now more reliable, or where an ADR was
written that a future maintainer would want to find.

**Omitted entirely** — dependency bumps, lint and formatting, docs-only
changes, and anything whose only effect is on contributors. A release note that
lists these buries the four things that matter.

Worked examples from 1.8.0, since the line is easier to see than to state:

| Change | Bucket | Why |
|---|---|---|
| Community billing for shared metering points | Section | A community can bill a shape it could not bill before |
| Import tariffs from a grid operator's Art. 7b publication | Section | Replaces a yearly manual transcription; needs explaining |
| Price bands can apply in only some months | Section | Seasonal tariffs were previously unbillable |
| Tariffs can carry more than a high and a low band | Section | Same — a whole tariff shape becomes expressible |
| Pick the grid operator from the official ElCom list | Also new | A better input on a form. Nothing new is possible |
| Move document downloads to /reports, slim the dashboard | Also new | Things moved; no decision for the user to make |
| Give every paginated list ordering a unique tiebreaker | Fix | Paginated walks could drop rows — check your data |
| Parallelize the test suite with pytest-xdist | Omit | Contributors only |

## 3. Write it

Structure, in order. Leave out any section with nothing in it.

1. **Opening paragraph.** One or two sentences: what this release is for. If
   there are fixes people should apply promptly, say so here.
2. `### <Feature>` — one per headline change.
3. `### Also new`
4. `### Fixes worth knowing about`
5. `### Under the hood`
6. `### Upgrading` — see below.

### Voice

Follow the v1.7.0 notes; read them before writing (`gh release view v1.7.0`).

- Address the reader as *you*. Name the UI path in bold: **Account → API keys**.
- Be concrete. "A typical invoice now fits on one page instead of three", not
  "improved invoice layout".
- **Say what a feature cannot do.** The API-keys section is the model: it spends
  a paragraph on what a key deliberately cannot reach. That is what makes the
  notes trustworthy rather than promotional.
- No marketing register: no "seamless", "powerful", "revolutionise". No emoji.
- A short code block or `curl` example where it saves a paragraph.
- Numbers where you have them, and only where you have checked them.

### Screenshots

Most sections do not need one. A screenshot earns its place when the reader
has to *find* something ("tick this box, here"), or when a change is visual
and a paragraph describing it would be longer and vaguer than the picture. A
new default, a fixed calculation or an API change gets no screenshot — there
is nothing to look at.

At most one or two per release. Never in `Also new` (if it needs a picture it
needs a section) and never in `Fixes worth knowing about`.

**Taking one.** The stack must be running and seeded. From `frontend/`:

```
SHOT_NAME=1.9.0-band-setting SHOT_URL=/zev-settings \
  SHOT_SELECTOR='.form-section' npm run shot
```

`SHOT_SELECTOR` is usually what you want: crop to the card or table that
changed rather than shipping 1400px of chrome around it. The helper writes to
`docs/release-notes/screenshots/` and defaults to the English UI. Its header
comment lists the rest (`SHOT_MODE`, `SHOT_WAIT`, `SHOT_NO_PIN`, and the
`SCREENSHOT_*` connection variables, which is where to look when login fails).

Name files `<version>-<slug>.png`, or `<version>-<slug>-before.png` /
`-after.png` for a pair.

**Before/after** is two stacked images with bold captions, not one composed
picture and not an HTML table — this renders the same in the repo, in the PR
review and in the release body:

```markdown
**Before** — one line at the blended average rate

![...](screenshots/1.9.0-bands-before.png)

**After** — one line per band

![...](screenshots/1.9.0-bands-after.png)
```

Only use before/after where the *before* is genuinely reproducible. If showing
it means generating throwaway billing data on a real instance, show the
control the reader has to find instead, and let the prose carry the contrast.

**Always write the path relative to the draft** (`screenshots/x.png`). It is
correct in the repo and in the PR, and the publish step rewrites it — see §6.
Do not hand-write a `raw.githubusercontent.com` URL, and never use a `../`
path: in a release body the `..` eats the tag ref and the image breaks.

**Alt text is not a caption.** It is what a reader gets when the image does not
load, so say what the picture shows, not "Screenshot".

### The Upgrading section

Migrations are the part most likely to be wrong by hand. Derive them:

```
git diff --name-only v<previous>..origin/main -- 'backend/*/migrations/*.py' | grep -v __init__
```

With a handful, list them with one line each on what they do. With more than
about six, group by app and give the count plus what changed, rather than a
flat list nobody reads. Say whether they are additive or rewrite data, and
whether downtime is expected.

Also state, if applicable:

- **Configuration changes** — new or changed environment variables or settings.
- **Deployment changes** — anything an operator must do by hand. 1.8.0's
  Postgres volume fix moves the cluster and starts empty until restored; that
  belongs at the top of the notes, not buried in Upgrading.
- **Removals and breaking changes** — an endpoint gone, a payload shape
  changed, a setting no longer read. Always call these out explicitly, with
  what to use instead. Check the change list for `!` conventional-commit
  markers and for anything a spec marks superseded.

  **A method split is not a removal but is still breaking.** 1.8.0 moved
  contract issuance from `GET` to `POST`; the `GET` remains but no longer
  generates a document, so it now 404s where it used to succeed. Nothing in the
  change list says "breaking". Read the view for any endpoint whose HTTP method
  or side effects changed, and describe what a script would now have to do
  differently.

## 4. Save the draft

Write to `docs/release-notes/<version>.md`, and end the file with the state
block so `continue` knows what has already been judged:

```markdown
<!-- release-notes-state
version: 1.8.0
source-pr: 434
triaged:
  461: section   # community billing for shared metering points
  519: also-new  # grid-operator picker
  523: omit      # contributors only
-->
```

Every PR from the change list must appear here exactly once, including the
omitted ones — an untriaged PR is the only thing `continue` needs to look at,
and "omit" is a decision worth being able to see in a diff.

Commit it on a branch and open a PR like any other change. It is reviewable
prose about the release, and it stays as the archive: v1.7.0's notes exist only
on GitHub, which is why this directory exists.

## 5. Continue a draft

1. Re-derive the change list (step 1).
2. Compare against `triaged:` in the state block.
3. Triage only what is new, and fold it into the existing text — do not rewrite
   sections that are already settled unless a new change changes their story.
4. If a new headline feature arrived, revisit the opening paragraph: it frames
   the release and is the thing most likely to have gone stale.

## 6. Publish

Only after release-please's PR is merged and the release exists.

A cut produces two releases: `v<version>` and `chart-openzev-<version>`. The
notes go on `v<version>`.

```
gh release view v<version> --json body -q .body > /tmp/generated.md
node scripts/release-notes-body.mjs <version> --generated /tmp/generated.md > /tmp/body.md
gh release edit v<version> --notes-file /tmp/body.md
```

The script assembles the body: the prose from `docs/release-notes/<version>.md`,
then `## Full change list`, then the generated body with its own
`## [<version>]` heading kept. It also does the two things that are easy to get
wrong by hand:

- **Strips the `release-notes-state` block.** Bookkeeping for `continue` mode;
  it must not reach the published release.
- **Pins every relative image path** to `https://raw.githubusercontent.com/<repo>/v<version>/…`.
  This is necessary because a release body has no file context: GitHub resolves
  a relative path against the *repository root* at the tag, while the same
  markdown in the repo resolves it against `docs/release-notes/`. One path
  cannot satisfy both, so the draft keeps the repo-correct one and the publish
  step rewrites it. It refuses to build a body that references an image which
  does not exist, because a broken image in a published release is not
  something you can quietly fix afterwards.

Read the result back and check the two halves did not run together — the
`## Full change list` heading is what separates them. If the notes carry an
image, open the released page and confirm it actually renders: the URL is
pinned to the tag, so it only resolves once the release is cut.

## Checks before publishing

- Every claim about behaviour is true of the code that shipped, not of the PR
  description. Verify anything you did not write yourself — reading a spec's
  "Problem and outcome" gives the framing, but the code gives the truth, and
  specs are written before the compromises.
- **Every UI path checked against the interface**, not guessed from the feature
  name. Grep the locale files for the label you are about to print in bold. A
  wrong path is worse than no path: it sends the reader looking in the wrong
  place and makes them doubt the rest.
- Every number checked.
- **Every screenshot shows the version being released**, not a newer UI. These
  are frozen artefacts: never regenerate an old release's images.
- Every migration listed.
- Removals called out.
- No change that belongs in a section is sitting in `Also new` because it was
  easier to summarise in one line.
