# ADR 0038: Order invoice-generation locks with restore and approval

- Status: Accepted
- Date: 2026-10-16

## Context

Generation must serialize for a participant even when no invoice exists.
Approval locks invoice rows, while community restore locks the ZEV before
replacing participants. Taking a participant lock first can deadlock with
restore; checking invoice status without holding its row can race approval.

## Decision

Within generation's existing transaction, take a PostgreSQL ZEV `FOR KEY SHARE`
lock before the participant lock. It conflicts with restore's `FOR UPDATE`
but permits other generators and numbering's `FOR NO KEY UPDATE`. Django has
no key-share queryset option, so this one query uses parameterized SQL.

Lock the participant by primary key, excluding its related party, then lock
all overlapping invoices in primary-key order before checking status and
deleting replaceable rows. Workflow transitions already lock those invoices.
Dynamic-source and number-allocation locks follow; all locks last until the
surrounding transaction ends. SQLite retains its existing single-writer behavior.

## Consequences

Concurrent generators may still calculate for different participants; shared
source and numbering locks may serialize them. A competing approval must finish
before regeneration decides, or wait until regeneration finishes. Restore and
generation acquire their common parent lock before participant locks.

## Alternatives considered

- An exclusive ZEV lock at entry would serialize every participant's calculation.
- Locking existing participants before restore's ZEV lock would miss concurrent
  participant inserts.
- A final status recheck would not protect invoices already collected for deletion.
