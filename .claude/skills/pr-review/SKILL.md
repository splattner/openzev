---
name: pr-review
description: Review a pull request and produce the structured review comment this project uses — must-fix items, in-scope improvements, other observations, and what was actually validated. Use when asked to review a PR, review a branch before opening a PR, or do a second pass on a PR that has been updated.
---

# PR review

Every review in this repository comes out in the same shape, so the author can
read it the same way every time: what blocks the merge, what is worth doing
while the file is already open, and what is only worth knowing. A review that
mixes a data-loss bug in with a naming preference makes the author triage the
reviewer's output, which is the reviewer's job.

The review is drafted locally and shown in full before anything is posted. It
is never posted without being asked first, unless the invocation passed
`--post`.

## Target

| Argument | Target |
|---|---|
| `123` | PR #123 |
| *(none)* | The PR for the current branch; if there is none, the branch diff against `origin/main` |
| `<branch>` | That branch's PR, or its diff against `origin/main` |
| `--post` | Skip the confirmation and post when the review is done |

Resolve it first, and say out loud which PR and how many files are in scope
before starting to read. If the current branch has no PR, the review still runs
— it is then a pre-PR review, and the "PR hygiene" gates below become advice
about the PR to open rather than findings.

```
gh pr view <n> --json number,title,state,headRefName,baseRefName,body,isDraft
gh pr diff <n>
```

For a local branch with no PR, use the merge base, not a two-dot diff — a
two-dot diff shows everything that landed on `main` since the branch started
and will produce findings about code the author never touched:

```
git diff origin/main...HEAD
```

Check for uncommitted local changes (`git status`) before concluding that
something is missing; the working tree may already contain it.

## 1. Read before judging

In order, and none of it is optional:

1. **The PR body.** It states intent and links the spec. A finding that
   contradicts a stated, deliberate decision is a question, not a must-fix.
2. **The linked spec**, and any baseline spec in `docs/specs/` that covers the
   touched area (`AGENTS.md` lists which spec owns which area). The spec is the
   contract; a diff that silently diverges from it is a finding even when the
   code is correct.
3. **The changed files in full**, not the hunks. Most real bugs in a diff are
   about what the changed line interacts with — a caller three functions up, a
   serializer the new field never reached, a permission class that no longer
   matches the queryset.
4. **The other side of any contract.** A changed DRF serializer means reading
   `frontend/src/types/api.ts` and the TanStack Query consumer. A changed
   workflow transition means reading the frontend's action-visibility logic.

## 2. Verify

CI is the authority on whether the suite passes. `pr-quality.yml` already runs
lint, `manage.py check`, the full pytest suite, the frontend lint, style, hex
sweep, unit tests and build, and `helm lint`. Re-running those locally
duplicates CI and proves nothing it has not already proved, so read the result
rather than reproducing it:

```
gh pr checks <n>
gh pr view <n> --json headRefOid
```

Check that the checks ran against the **current head commit** (`headRefOid`),
not an earlier push — a green result for a stale SHA is no signal.

- **Green on the head SHA:** run nothing CI already covers. Say so in
  Validation. Local commands are then only for what CI does not run (see
  "Beyond CI" below) or to confirm one specific suspected bug.
- **Red:** the failing job is a must-fix, and the review says which job and why.
  Read the log (`gh run view <run-id> --log-failed`); do not reproduce the
  failure blind.
- **No signal:** a pre-PR branch, a draft, a stale SHA, or docs-only paths that
  `pr-quality.yml` skips. Say so, and fall back to the table below, running only
  what the diff touches. Do not run the full suite.

Fallback commands, for when CI has no signal for the head commit:

| Diff touches | From | Command |
|---|---|---|
| any `backend/**.py` | `backend/` (`source ../.venv/bin/activate`) | `ruff check . && python manage.py check` |
| `backend/<app>/**` | `backend/` | `python -m pytest <app> -q` |
| models or migrations | `backend/` | `python manage.py makemigrations --check --dry-run` |
| `frontend/src/**` | `frontend/` | `npm run lint && npm run test:unit` |
| styles, tokens, colors | `frontend/` | `npm run lint:style && node ../scripts/check-frontend-hex.mjs` |
| types, imports, build risk | `frontend/` | `npm run build` |
| `charts/**` | repo root | `helm lint ./charts/openzev` |
| docs or specs only | — | nothing — CI skips these paths too |

Use the Node version in `.node-version` for frontend commands.

### Beyond CI

These are worth doing even when CI is green, because no workflow covers them:

- **Migrations:** when models or migrations changed, from `backend/`
  (`source ../.venv/bin/activate`): `python manage.py makemigrations --check --dry-run`.
- **Visual check:** if a user-facing frontend change can be seen in the running
  dev stack, check whether the stack is already up (`docker ps` / `podman ps`)
  and look at it, including at ~400px width; otherwise say it was not visually
  checked.
- **Confirming a suspected bug:** a single targeted test or command that
  reproduces a concrete concern raised during the read. This is investigation,
  not validation — do not widen it into a suite run.

Record every command that was run and its result — the Validation section
reports them verbatim. Do not list checks CI ran as if the review ran them.

## 3. Gates

Beyond correctness, check each of these against the diff. They are the things
that break in this repository specifically.

| Gate | Finding when |
|---|---|
| **Spec** | The diff changes API behavior, response shape, billing/tariff logic, invoice workflow state, data model, async delivery guarantees, or role/ZEV scope — and the owning baseline spec in `docs/specs/` is untouched or now contradicts the code |
| **API contract** | A serializer or response shape changed without `frontend/src/types/api.ts` and its consumers changing in the same PR |
| **Invoice workflow** | A transition, permission, or state changed on the backend without the matching frontend action visibility |
| **Migrations** | A model field changed with no migration, a migration that is not reversible, or a data migration that assumes a non-empty or single-tenant table |
| **ZEV scope & roles** | A new queryset, endpoint, or serializer that does not scope by ZEV, or a permission class that no longer matches what the view returns |
| **i18n** | User-facing text hardcoded in any language instead of `react-i18next`; a new key added to one locale in `frontend/src/i18n/locales` but not the others |
| **Design tokens** | Raw hex, `rgb()` or `rgba()` outside the tokens, without the file being in `scripts/hex-migration-allowlist.json` with an `@alpha` suffix |
| **Tests** | New behavior with no test; a test that asserts the implementation rather than the behavior; a backend test placed away from the affected app's test module |
| **Reuse** | New UI that duplicates an existing component in `frontend/src/components/`, or a new CSS utility that already exists |
| **User guide** | The change alters what a user sees or does, and the matching chapter in `docs/user-guide/` is untouched |
| **PR hygiene** | Title is not Conventional Commits (`feat(scope): …`); the template's spec or validation sections are empty; `CHANGELOG.md` was hand-edited; per-PR release notes were written |
| **Scope** | Unrelated reformatting, or a second feature smuggled into the diff — both make the PR harder to review and to revert |

A gate that does not apply to the diff is not mentioned. A gate that applies and
passes is not mentioned either, except where saying so is useful in Validation.

## 4. Triage into three buckets

The bucket is decided by **consequence if merged as-is**, never by how much work
the fix is.

**Must fix before merge** — merging causes a wrong result, data loss, a security
or scope hole, a broken build or red CI, an unreversible migration, a broken
contract between backend and frontend, or a spec that now lies about the code.
If you cannot describe the concrete failure, it is not a must-fix.

**Worth doing in this PR** — the code works, but it is below the bar the
repository holds, and the fix belongs here because these files are already open:
a missing test for the new branch, a duplicated component, a missing translation
key, an error path that swallows the cause, a spec section that is now thin.
Non-blocking, and the author can decline with a reason.

**Worth mentioning** — everything the author should know but not act on now: a
pre-existing problem the diff brushed against, a follow-up worth an issue, a
design decision worth recording in an ADR, or a genuinely good solution worth
pointing at so it gets reused. Keep this short and never pad it.

Rules that keep the output worth reading:

- Every must-fix names `file:line` and a concrete failure — inputs or state, and
  the wrong outcome that follows.
- Nothing a linter, formatter or the hex sweep already catches. CI is doing that.
- No findings about untouched code, unless the diff broke it — those belong in
  bucket three.
- No stylistic preference dressed as a defect.
- At most one suggested fix per finding, one line, and only when it is obvious.
- If a bucket is empty, keep the heading and write *None.* An empty bucket is
  information.
- Do not claim the tests pass. Say which command ran and what it printed.

## 5. The comment

Draft it to the scratchpad directory as a `.md` file, then show it in full.

```markdown
## Review — <PR title> (#<n>)

**Verdict:** <Request changes | Approve with comments | Looks good>

<One or two sentences: what the PR does, and the single most important thing
about it. Not a restatement of the title.>

### Must fix before merge

1. **<The claim in one line>** — `path/to/file.py:42`
   <What goes wrong: the inputs or state, and the wrong outcome.>
   <Optional: one-line fix.>

### Worth doing in this PR

- **<The claim in one line>** — `path/to/file.tsx:88` — <why it belongs here>

### Worth mentioning

- <Observation, follow-up, or something done well. No action required.>

### Validation

- CI: <green on `<short-sha>` | red — which job and why | not run, because …>
- Ran: `<command>` → <result> *(only what CI does not cover, or a fallback when CI had no signal)*
- Not checked: <the honest blind spots — what this review did not cover>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Use `file:line` in backticks for local reviews. When the comment is posted to a
GitHub PR, link the blob instead so the reference is clickable:
`[backend/invoices/views.py:42](https://github.com/splattner/openzev/blob/<sha>/backend/invoices/views.py#L42)`,
with `<sha>` the PR head commit.

## 6. Post

Show the full draft, then ask whether to post it. Post it as one comment — not
a formal review — so it does not block or approve on the user's behalf:

```
gh pr comment <n> --body-file <scratchpad>/pr-<n>-review.md
```

Confirm the target PR number before posting, and check the PR is still open
(`gh pr view <n> --json state`). With `--post`, skip the ask but still print the
draft and the resulting comment URL.

## 7. Re-review

When the PR was already reviewed and has new commits, do not repeat the whole
review. Read the previous comment, diff what changed since it
(`git log <sha-at-review>..<head>`), and post the short form:

```markdown
## Re-review — <PR title> (#<n>)

**Verdict:** <…>

- ✅ Fixed: <finding> — <how>
- ⚠️ Still open: <finding> — <why it still matters>
- 🆕 New: <anything the new commits introduced>

### Validation
- <as above, for what was re-run>
```

Findings the author declined with a reason are not re-raised. They move to
*Worth mentioning* once, or disappear.
