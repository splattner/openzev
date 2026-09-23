---
name: spec-validate
description: Verify that a spec in docs/specs/ still tells the truth about the code — field tables, endpoints, permission classes, serializer fields, TypeScript types, component paths, test names and counts. Use when asked to validate, check, or audit a spec, after changing code a baseline spec describes, or before relying on a spec to re-implement something.
---

# Validate a spec

`docs/specs/README.md` sets the bar: someone must be able to **re-implement the
feature from the spec alone, without reading the code**. A spec meets that bar
on the day it is written and then quietly stops meeting it, because the code
keeps moving and the prose does not. Nothing in CI checks this.

Validation is the step `AGENTS.md` already requires and nobody performs: *verify
every claim against the actual code — field names, types, defaults, permission
classes, endpoint paths, serializer fields, test method names, and test counts.*

This skill reports drift. It only edits the spec when asked, and only where the
code is the authority — see below, because getting that backwards turns a real
bug into a "documentation fix".

## Which way the truth runs

Decide this **before** reporting anything. It determines whether a mismatch is a
spec defect or a code defect.

| Spec kind | How to tell | Authority | A mismatch means |
|---|---|---|---|
| **Baseline** | Listed as a baseline in `AGENTS.md`; describes what exists today | **The code** | The spec is wrong — fix the spec |
| **Completed feature** | Listed under completed feature specs in `AGENTS.md` (shipped) | **The code** | The spec is wrong — fix the spec |
| **Reference** | `2026-04-frontend-management-page-design.md` and kin; prescribes a pattern | **The spec** | The code diverges from the agreed pattern — report against the code |
| **Forward / unimplemented** | Describes work not yet built; no matching code, or an implementation tracker alongside | **The spec** | Either not built yet, or built differently — never "fix" the spec to match |

If the kind is ambiguous, say so and stop rather than guessing — a wrong call
here produces confidently wrong output.

## Target and scope

A baseline spec runs to well over a thousand lines and makes hundreds of claims.
Validating all of it on every run is not useful work.

| Argument | Scope |
|---|---|
| `<spec file>` | That spec, sections chosen as below |
| `<area>` (e.g. "invoices", "tariffs") | Resolve via the scope-mapping table in `docs/specs/README.md` |
| *(none)* | The spec(s) owning what the current diff touches — `git diff origin/main...HEAD --name-only` |
| `--section 4.2` | Only that section |
| `--full` | Every section, reported section by section |

Default scope is **the sections covering what changed**, plus the mechanical
pre-pass over the whole file — that is cheap and catches drift anywhere. Say
which spec and which sections are in scope before starting.

## 1. Mechanical pre-pass

Two classes of claim are checkable without judgement, so do them first over the
whole spec.

**File and symbol paths.** Every `backend/…`, `frontend/…`, `docs/…` path and
every `` `ClassName` ``/`` `function_name` `` the spec names should resolve. A
path that no longer exists is unambiguous drift and often reveals a rename the
rest of the section missed.

**Test counts and names.** Extract candidates, then adjudicate each one by
reading the line — do not trust the extraction:

```python
# candidates only — every hit needs a human/agent read of the line
import re, pathlib
for i, line in enumerate(pathlib.Path(SPEC).read_text().splitlines(), 1):
    if re.search(r'\b\d+\s+(tests?|test methods|test classes)\b', line):
        print(f"{i}: {line.strip()[:160]}")
```

Then count the truth. Test modules are named **both** `test_*.py` and `tests.py` —
globbing only `test_*.py` misses `backend/exports/tests.py` and reports every class
in it as "not found", which looks like catastrophic drift and is not:

```bash
grep -cE '^\s+def test_' backend/<app>/<file>.py      # methods in a file
awk '/^class <Name>/{f=1;next} /^class /{f=0} f&&/def test_/{c++} END{print c}' <file>.py
grep -cE '\b(it|test)\(' frontend/tests/<file>.test.ts
```

Three failure modes, all of which produce false drift if you skip the read:

- One line names several classes with per-class counts **and** a total —
  `` `A` (7), `B` (5) and `C` (2) — 28 tests`` — the total is not any one class's
  count, and may cover files the line does not name.
- A count may be scoped to *files* or *classes*, not methods: "(8) — 25 test
  methods across 5 files" holds two different numbers, both correct.
- A class name may appear in more than one test module.
- A spec may hold **two layers** — an original "planned" test plan and a later "as
  shipped" summary — with a disclaimer that supersedes only *some* of the stale
  tables. Read what the disclaimer actually names: tables it does not name are
  still drift, and the spec then contradicts itself in two places.
- When two specs state different counts for the same class, the disagreement
  itself locates the stale one. Grep the other specs for a class before
  concluding, and report which spec is wrong.
- **Rollups are their own claim.** Lines like `Total: 48 test methods across 7
  classes` or `— 25 test methods across 5 classes` are invisible to per-class
  extraction and go stale the moment any member changes. Grep for them
  (`Total:`, `across N classes`) before calling a spec clean, and recompute
  which classes each one actually sums — a rollup may deliberately cover a
  subset of the file.

Only report a count as drift when the line's own wording makes the claim
unambiguous.

## 2. Claim walk

For each section in scope, take every factual claim and resolve it. The spec's
structure maps onto where truth lives:

| Spec claim | Truth lives in | Check |
|---|---|---|
| Field table under a model heading | `backend/<app>/models.py` | Name, field class, `max_length`, `null`/`blank`, `default`, `on_delete`, `choices`, `related_name` — each column, not just existence |
| Computed properties | same model | The property exists and its logic matches the stated condition |
| Enum value/label tables | the `TextChoices`/`Choices` class | Every value present, no extras, labels match |
| Endpoint path and method | `urls.py`, router registrations, viewset | Resolve the **full** path through every including `urls.py` prefix and any `url_path=` action. Matching only the last segment passes almost anything and proves nothing |
| Permission class | `accounts/permissions.py`, `zev/permissions.py`, the view's `permission_classes` | The class exists **and** the view really uses it |
| ZEV scoping claims | the queryset / `ZevScopedQuerySetMixin` usage | Scoping is applied on read *and* write paths |
| Serializer fields, read-only | the serializer | `fields`, `read_only_fields`, `SerializerMethodField`s, validators |
| Response shape | serializer + any custom `to_representation` | Key names and nesting as printed |
| Async behaviour | the Celery task, retry/`acks_late` settings | Task name, retry policy, idempotency claim |
| Migration claims | `backend/<app>/migrations/` | The named migration exists and does what is described |
| Frontend component / route | `frontend/src/**` | File path, exported component name, route path |
| TanStack query keys, mutations | the hook or page | Key tuples match exactly — these drift silently |
| TypeScript types | `frontend/src/types/api.ts` | Interface fields and optionality match the serializer |
| Settings / feature flags | `settings.py`, `AppSettings` | Name, default, and where it is read |

Read the code, never infer from another part of the spec. A section that agrees
with a neighbouring section but not with the code is still wrong.

## 3. The reverse check

Drift runs both ways, and this direction is the one that breaks the
re-implementability bar — the spec is not *wrong*, it is *incomplete*, so a
reader who trusts it builds something subtly different.

For each model, serializer, enum, endpoint group or TypeScript interface the
section documents, list what the code actually has and diff it against the
table. Report fields, endpoints, permissions and types that exist in code but
appear nowhere in the spec.

Exclude what the spec deliberately scopes out — check the section's own "Out of
scope" and any stated exclusion before calling something undocumented.

## 4. Verdicts

| Verdict | Meaning |
|---|---|
| **WRONG** | Spec states something the code contradicts. Quote both. |
| **MISSING** | Spec describes something that does not exist in the code at all. |
| **UNDOCUMENTED** | Code has something the section should list and does not. |
| **STALE** | Numbers, names or paths that were right once — counts, renamed symbols. |
| **UNVERIFIABLE** | Rationale, intent, trade-offs. Not drift. Do not report as a finding. |

Every finding carries the spec location (`docs/specs/<file>.md:<line>`), the code
location (`path:line`), and what each one says. A finding without both sides is
not ready to report.

## 5. Report

```markdown
## Spec validation — <spec file>

**Kind:** <baseline | completed feature | reference | forward> → authority: <code | spec>
**Scope:** <sections validated, or "full file">
**Claims checked:** <n>  ·  WRONG <n>  ·  MISSING <n>  ·  UNDOCUMENTED <n>  ·  STALE <n>

### Wrong
1. **<claim in one line>** — spec `docs/specs/<f>.md:412` · code `backend/zev/models.py:88`
   Spec: <quote>
   Code: <quote>

### Missing
### Undocumented
### Stale

### Not checked
<sections skipped and why — the reader needs to know what this run did not cover>
```

Keep empty headings and write *None.* An empty category is a result.

If scope was partial, **Not checked** is mandatory. A validation report that
looks complete but covered a third of the file is worse than none.

## 6. Fixing

Only with `--fix`, and only where the authority is the code — baseline and
completed feature specs. Never "fix" a forward or reference spec into agreement
with the code: there the mismatch is the finding.

Rules when applying:

- Change only the claims reported. Do not rewrite surrounding prose, reflow
  tables, or restructure sections — `AGENTS.md` is explicit that only affected
  sections change.
- Match the section's existing detail level and table columns.
- UNDOCUMENTED items get a real row at the documented bar (type, default,
  constraint), not a name and an empty cell.
- Leave WRONG-in-a-reference-spec and everything in a forward spec alone; those
  are code findings.
- After changing any count, recompute every rollup that includes it in the same
  edit. A corrected member count under a stale total is still a wrong spec.
- Read the diff for prose damage. Splicing a clause into a wrapped sentence can
  leave it ungrammatical even when every number is right.
- Show the resulting diff and re-verify each edited claim against the code
  afterwards. An edit made from the report rather than from the code can
  reproduce the extraction's own mistakes.

## Rules

- Resolve every claim against code you actually opened. Never validate a spec
  from memory of the codebase.
- Uncertain resolution is reported as uncertain, with what you checked, not
  rounded into a confident verdict.
- Do not touch the code to make a baseline spec true — that inverts the
  authority. Report it and stop.
- Prose about *why* is not drift. Only claims about *what* are.
