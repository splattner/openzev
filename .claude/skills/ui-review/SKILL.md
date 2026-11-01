---
name: ui-review
description: Review the user interface and user experience of an implemented issue, PR, PR stack or screen area — from screenshots of the running app, not only code. Checks conformance to the UI specs (containers, panes, dialogs, buttons, badges, labels, forms, i18n, responsive), then judges whether the result is intuitive, uncluttered and lets each role see and do what it needs. Use when asked for a UI review, a UX review, a design review, or "how does this feel" on a feature.
---

# UI/UX review

`pr-review` asks whether a change is correct. This asks whether it is **good to
use**: whether an occasional, non-technical community manager or a participant
understands the screen, finds the task, and finishes it without help. The
answer comes from looking at the running app as each role sees it. Code is read
to explain what the screenshots show and to point at the fix, never instead of
them.

A UI review produces two kinds of result, kept apart:

1. **Spec conformance** — where the screen breaks a rule the UI specs set.
2. **Experience** — where the screen follows the rules and is still confusing,
   overloaded or incomplete. Some of these mean the *spec* should change; say so
   explicitly rather than bending the finding to fit an existing rule.

The review is drafted locally and shown in full. Nothing is posted to GitHub,
and no issue is opened, without asking first.

## Target

| Argument | Target |
|---|---|
| `123` | Issue or PR #123. For a tracking issue, every PR in its stack (`gh pr list --state all --search "<n>"`) |
| *(none)* | The current branch against `origin/main` |
| a route or area (`/tariffs`, "metering points") | That screen as it is now, no diff |

Start by stating out loud: the target, the PRs and branch in scope, the screens
(routes) affected, and the roles that reach them. Find the screens from the
diff, not from memory:

```
git diff --stat origin/main...HEAD -- frontend/src
git diff origin/main...HEAD -- frontend/src/App.tsx frontend/src/lib/navigation* frontend/src/i18n/locales/en.json
```

New locale keys are a fast map of every new string the user will read.

## 1. Read the guidance

The rules a screen is measured against. Read the sections named, not the whole
file each time.

| Source | What it decides |
|---|---|
| `docs/specs/2026-10-ui-patterns-and-component-catalog.md` | §4 which component for which need; **§5 where a thing opens** (rules A–F); §6 dialog, pane, disclosure, page; §8 forms; §9 actions; **§10.1 labels, badges, counts**; §10.2 feedback; §12 review checklist |
| `docs/specs/2026-04-frontend-management-page-design.md` | §4.1 shared component contracts; §7.1 page shell order; §7.2 table vs cards, sections vs tabs; **§7.3 action hierarchy**; §7.6 i18n; §7.7 responsive |
| `docs/specs/2026-08-ui-redesign-pdf-style.md` | §5.3 screen quality bar; §15.3 page anatomy (header, scope line, sheets, filter bar, toolbars) |
| `docs/adr/0040-overlay-and-disclosure-pattern-rules.md`, `0032-one-visual-language-for-screen-and-documents.md` | The decisions behind the two specs above |
| `docs/specs/2026-10-tariff-split-view.md` | The reference implementation of the detail pane |
| The feature's own spec (linked from the issue/PR) | Who the feature is for, what each role must see and do — the yardstick for "can the user do what they want" |
| `docs/specs/2026-03-community-and-access.md` §9 | Navigation, canonical routes, hubs, scope-aware shell |
| `docs/user-guide/<chapter>.md`, `15-glossary.md` | The words users already learned; the guide's screenshots are the *before* picture of existing screens |

Precedents that show how strictly the project applies these rules — read them
when a finding is borderline:

- **#1133** (quieter badges in the tariff pane): attributes are plain text or
  `.badge-tag`, not filled pills; no badge repeating what a heading says;
  current/upcoming distinguishable without colour alone.
- **PR #1125** (UI patterns phase 7): `button` plus exactly one variant; no
  `button danger`, no `button-primary button-outline`, no bare `button`; static
  presentation in classes, not `style={{}}`.
- **#1063** (UI patterns phase 2): `FormModal` `size` instead of widths, the
  universal dirty guard, `Disclosure`, `AppTabs`.
- **#1081**, the tariff split view: what "a record opened from a list" looks
  like.

## 2. Plan the scenarios

A screen reviewed once, as admin, at 1440px, in English, is not reviewed. Write
down the matrix before capturing, and keep it small enough to actually look at
every image (typically 15–40 shots).

**Personas** (seed_demo accounts, password `<name>1234`):

| Persona | Use for |
|---|---|
| `admin` | Platform view; admin-only setup |
| `owner` | Issuer of ZEV 1 + 2: the typical manager, community switcher |
| `manager` | Representative of ZEV 1, manager of ZEV 2 |
| `viewer` / `treuhand` | Read-only: write controls absent, not disabled; problems still visible |
| `anna` | Plain participant, one ZEV |
| `ben` | Participant with several metering points (flat + parking with charger) |
| `clara` | Participant in ZEV 2 (different data shape) |
| `mixed` | Manager in one ZEV, participant in another: does the shell make the two roles clear? |
| `household`, `organisation` | Joint household / organisation participants |
| `newcomer` | No ZEV yet: first-run, empty states |

Pick the personas the feature spec names, plus the read-only one and at least
one that should *not* see the feature (to confirm it is absent, not broken).

**States** — each one a separate shot where the feature has it: not set up /
empty, typical, a lot (many records, long names), error or stale data, loading
if it is slow enough to be seen, feature flag off. If the seed lacks a state,
create it through the UI or the API in the dev stack and restore it afterwards
(see the dev-stack memory: restore prior values, not defaults).

**Viewports**: 1440 (desktop), 1024 (narrow laptop: where panes collapse) and
400 (phone).

**Languages**: `de` (primary audience) everywhere; `fr` or `it` on the busiest
screens (longest labels, catches wrapping and truncation); `en` only where the
release notes need it.

**Interactions**: every dialog, pane, disclosure, confirmation and the empty
submit of every form (shows validation). These are `steps` in the plan.

## 3. Capture

The dev stack must be running and seeded (`podman ps` / `docker ps`; see
`AGENTS.md`), and Node must be the version in `.node-version`. Then write a plan
to the scratchpad and run the capture script from `frontend/`:

```
node ../.claude/skills/ui-review/capture.mjs <scratchpad>/ui-plan.json
```

The script's header documents the plan format (personas, widths, langs, steps,
`mode: "viewport"` for dialogs, `forcedColors: true`). It writes one PNG per
persona × language × width and a `report.json` per shot with console errors,
failed API requests, horizontal overflow (and which elements cause it), leaked
i18n keys, the page title and `h1`. Every `!` line it prints is already a
finding candidate. Each persona costs one sign-in; the backend allows 40 per
hour per IP, so do not loop the script.

Use selectors that survive translation (`role=button[name=/Speichern|Save/]`,
CSS classes, `data-*`). A failing step is recorded and the shot still taken,
so a missing control is visible, not silently skipped.

For keyboard and focus behaviour, which a still image cannot show, add steps
(`{"press": "Tab"}` ×n, `{"press": "Escape"}`) and shoot the result, or read the
behaviour tests the spec names.

## 4. Look at every screenshot

Open each image with the Read tool. Before reading any code, for each screen
write down, in a sentence each:

1. **Five-second test.** What is this page for, and what is the most
   important thing on it? If that is not obvious from the image, it is a
   finding.
2. **First action.** Where would this persona click to do the job the spec
   gives them? Is that the visually primary control?
3. **What draws the eye.** List what is coloured, filled, bold or large.
   Does it deserve it (§10.1)? Count the distinct badges and the visible
   buttons in one row or card.

Then compare with a sibling: put the new screen next to the reference screen of
the same kind (a list beside the tariff or participant list, a pane beside the
tariff pane, a dialog beside the participant dialog, a dashboard beside the
existing dashboard). Same job, different shape is a consistency finding.

For changes to existing screens, compare with the user-guide screenshot of that
screen (`docs/user-guide/screenshots/`) as the before picture.

## 5. Check conformance

Work through this list against screenshots and code together. Every item names
its rule so a finding can cite it.

**Containers (§5, §6, ADR 0040)**
- Record opened from a list → detail pane, viewing and editing in the same
  place (rule A); create opens the same container as edit (F).
- Only a confirmation opens over a pane or dialog; a sub-form is an inline
  section; at most two layers (B). No overlay `Drawer` (C).
- A short self-contained task → `FormModal` with a named `size`, Cancel then the
  primary submit, dirty guard on X/Cancel/Escape/scrim/navigation.
- A page only when §6.4 says so (own navigation, a shareable URL, recovery, or
  more room than `lg`). Steps or size alone do not make a page (D).
- Secondary material in a `Disclosure`; tabs only for mutually exclusive
  working views (`AppTabs`), never for filters.
- Narrow screens show one surface at a time, with X and Back returning to the
  list with its state (E).

**Actions (§9, SPEC-2026-04 §7.3, PR #1125)**
- One primary action per header, toolbar or task context.
- At most two visible non-destructive row actions; the rest in `ActionMenu`.
- `button` + exactly one variant; `-compact` in rows; labelled on mobile.
- Destructive actions confirm through `ConfirmDialog` and stay out of form
  footers.
- Labels name the task ("Quelle verbinden", "Tarif erstellen"), not "OK" or
  "Submit". A disabled control says why, near the control.

**Labels, badges, counts (§10.1, #1133)**
- Counts only for a concrete task (a filtered population, affected records).
- Classification (role, meter type, capability) → `.badge-tag` or plain text,
  never a filled pill.
- Normal state undecorated; no green on every healthy record.
- A problem → `IssueText` with a link to its fix for users who may act; the same
  text without the link for read-only users.
- No badge that repeats its section heading or a neighbouring badge.
- Colour never carries meaning alone.

**Page anatomy and states (SPEC-2026-04 §7.1, SPEC-2026-08 §15.3, §10.2)**
- `PageHeader` with scope eyebrow, `h1`, one-sentence description; page title in
  the browser tab.
- `PageState`/`PageSkeleton` for loading and failure, `EmptyState` with an
  authorised action, `Notice` for persistent state, toast only for transient
  success.
- Sheets not nested in sheets; toolbar filters left, actions right.

**Forms (§8)**
- Label above, helper below, error below that; one column for short forms.
- Errors after first submit, by the field; a non-field failure is a `Notice` in
  the form, not only a toast. Values kept on failure; busy state while saving.

**Text and language (SPEC-2026-04 §7.6)**
- No hardcoded text; no leaked keys (the report lists them); plurals via
  `_one`/`_other`; frozen terms (ZEV, vZEV, SDAT-CH, units) untranslated.
- The same thing has the same name across the app, the user guide and the
  glossary (Messpunkt, Teilnehmer, Gemeinschaft…). A new term needs a reason.
- No developer vocabulary on screen (capability, source type, payload, token
  scope, TTL) without a plain-language explanation for the persona.

**Responsive and accessible (SPEC-2026-04 §7.7, §12)**
- No horizontal overflow at 400px (the report measures it); tables become cards
  or scroll inside their sheet, not the page.
- Long French/Italian labels wrap without breaking the layout.
- Visible focus, sensible tab order, Escape closes the topmost layer, focus
  returns to the invoking control. Forced-colours shot keeps every state
  distinguishable.

Useful greps on the changed files:

```
git diff origin/main...HEAD -- frontend/src | grep -nE '^\+.*(badge-|className="button|style=\{\{|<Drawer|<Tabs|FormModal|maxWidth|window\.confirm)'
```

## 6. Judge the experience

The specs cannot answer these. Answer them per persona and per task from the
feature spec, with the screenshots as evidence.

- **Can they see what they need?** The number or state the persona came for is
  the most prominent thing, with its unit (kW vs kWh vs CHF), its time (now,
  today, which period) and its quality (measured, estimated, forecast, stale,
  incomplete coverage). Two kinds of figure that mean different things must not
  look the same.
- **Can they do what they want?** Walk each task click by click from the
  sidebar. Count the steps. Note every dead end, every place the user must
  guess, every action only reachable from somewhere unrelated, and every
  set-up step the screen depends on without saying where it is done.
- **Is it overloaded?** Everything on screen should serve the persona's task on
  this visit. Candidates for removal or a `Disclosure`: technical details,
  configuration shown on a read screen, repeated facts, explanatory text that
  restates the heading, rarely used actions as buttons.
- **Is it consistent?** Same job, same pattern as elsewhere in the app (step 4's
  sibling comparison). Similar records reached from different places should
  look and behave the same.
- **Does it guide?** First run and empty states explain what to do next and
  offer the action. Errors say what went wrong and how to fix it.
- **Is it safe and private?** Consequences of destructive or consent steps are
  stated before the step. A participant never sees another participant's
  individual data; a role that should not see the feature does not see a hint
  of it either.
- **Does it fit where it lives?** Navigation placement, page name and the hub
  it sits in match how users think about the task, not how the backend models
  it. Return paths (Back, X, deep links) land where the user came from.
- **Does the user guide still describe it?** A chapter that tells the user to
  click something that no longer exists is a finding.

## 7. Triage

Decide by consequence for the user, not by how much work the fix is.

**Must fix before merge** — a persona cannot complete a task the spec promises;
the screen misleads (a figure read as something it is not, a state shown as
current when stale); data visible to a role that must not see it; a broken
interaction, console error, failed request or 400px overflow on the feature's
screens; untranslated text; a clear breach of a §5 container rule or §9/§10.1
rule that the project has already enforced elsewhere (cite the precedent).

**Worth doing in this PR / stack** — the task works but is harder than it needs
to be: wrong emphasis, an extra step, a decorative badge, a missing empty-state
action, a label that names the model instead of the task, an inconsistency with
the sibling screen.

**Spec questions** — places where following the spec produced a worse result,
or where the spec is silent and the feature had to invent a pattern. Propose
the spec change (file and section) and say whether it should block the PR.

**Follow-ups** — real problems outside the reviewed change, or larger redesigns
worth their own issue. Draft the issue title and one paragraph; do not open it
without asking.

Rules:

- Every finding references a screenshot (file name) and, where the cause is in
  code, `file:line`.
- One proposal per finding, concrete enough to implement ("move *Disconnect*
  into the `ActionMenu`", not "simplify the actions").
- Say what works well, briefly: patterns worth reusing are findings too.
- If a bucket is empty, keep the heading and write *None.*

## 8. The report

Write it to the scratchpad as `ui-review-<target>.md` and show it in full. Embed
the few screenshots that carry the main findings with absolute paths; list the
rest by name.

```markdown
## UI/UX review — <target>

**Verdict:** <Ready | Ready after the must-fixes | Needs another iteration>

<Two or three sentences: who the feature serves, whether they can do their
job, and the single most important change.>

### Scope
- Screens: <routes>
- Personas: <…> · Viewports: 1440 / 1024 / 400 · Languages: <…>
- Screenshots: <dir> (<n> shots), report: <dir>/report.json

### Task walkthroughs
| Persona | Task | Steps | Result |
|---|---|---|---|
| anna | See how much of her consumption is local right now | 2 | ✅ / ⚠️ <why> |

### Must fix before merge
1. **<Claim>** — `<screenshot>` · `path/to/file.tsx:42` · <rule>
   <What the user experiences.> → <Proposal.>

### Worth doing in this PR / stack
- **<Claim>** — `<screenshot>` · <rule> → <proposal>

### Spec questions
- **<Spec §>** — <what the spec says, what happened, proposed change>

### Follow-ups
- <Draft issue title> — <one paragraph>

### What works well
- <…>

### Validation
- Captured: <command, plan file> — <n> shots, <n> flagged by the report
- Looked at: <which shots were read>
- Not checked: <honest blind spots: personas, states or interactions not covered>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## 9. After the report

Ask before any of these:

- Posting the report to the PR or issue (`gh pr comment` / `gh issue comment`
  with `--body-file`). Screenshots are not attached by `gh`; describe them, or
  ask whether to commit selected ones somewhere first.
- Opening follow-up issues.
- Fixing findings. If asked, fix in the PR the finding belongs to (the right
  layer of a stack), re-run only the affected shots, and update the report
  with before/after.

Clean up anything created in the dev stack for a state (records, flags,
settings) and say what was restored.
