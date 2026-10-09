# Feature Spec: Privacy retention sweep (#795)

- Spec ID: SPEC-2026-10-privacy-retention-sweep
- Status: Completed
- Scope: Minor
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-09
- Target Release: next minor
- Related Issues: [#795](https://github.com/splattner/openzev/issues/795)
- Related ADRs: —
- Impacted Areas: backend | async jobs | docs

---

## 1. Problem and outcome

Three kinds of personal or tracking data had no expiry, unlike backups, export files and sessions:
the IP address and user agent on every `AuditEvent`, the recipient address on every `EmailLog`,
and consumed or expired one-time tokens.

**Outcome:** one sweep, run daily by Celery beat and on demand as `manage.py openzev_privacy_sweep`,
applies three instance-wide retention windows from settings. Each step is off at `0`, idempotent,
and reports through `--dry-run` before an operator trusts it.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Audit network details | `AuditEvent.ip_address` set to `NULL` and `user_agent` to `""` once the event is older than `PRIVACY_AUDIT_NETWORK_RETENTION_DAYS` (default 365). The event row stays. |
| Email logs | `EmailLog.recipient` and `error_message` set to `""` once the row is older than `PRIVACY_EMAIL_LOG_RETENTION_DAYS` (default 730). The row stays. |
| One-time tokens | `EmailVerificationToken`, `MagicLinkToken` and `ParticipantOnboardingToken` deleted `PRIVACY_TOKEN_GRACE_DAYS` (default 30) after they stopped being usable. |
| Retry guard | `retry-email` refuses a log whose recipient was blanked. |

### Out of scope

- Retention of `AuditEvent` rows, `Invoice`, `MeterReading` and other accounting data (legal floor, not a privacy ceiling).
- Per-ZEV windows; the settings are instance-wide.
- Addresses and network details that live in free-form fields elsewhere: `AuditEvent.summary` / `metadata_json` (an invoice email event names its recipient there), and `EmailLog.subject` when a custom template puts a name in it.

### Design decisions

- **`EmailLog` is blanked, not deleted.** The newest log per invoice drives the readiness cockpit's
  "delivery failed" item and the period overview's email status (`invoices.readiness`,
  `invoices.period_overview`), both for invoices that are not paid or cancelled. Deleting a
  two-year-old failed log would silently clear that item for a still-open invoice. `error_message`
  is blanked too because an SMTP error repeats the address. No migration is needed: `recipient`
  stays a non-null `EmailField`, holding `""`.
- **Tokens use the same definition of "unusable" as their `is_valid`/`is_active`**, then add the
  grace: consumed (`consumed_at`) or past `created_at + lifetime` (`EmailVerificationToken.LIFETIMES`
  per purpose, `MAGIC_LINK_LIFETIME`), or for onboarding tokens revoked (`revoked_at`) or past
  `expires_at`. A live token is never selected.
- **`0` keeps everything** for that step, as `BACKUP_SAFETY_RETENTION_DAYS` does.

## 3. Actors, permissions, and ZEV scope

No new endpoint and no UI. The command needs shell access to the deployment; the task is run by beat.
The sweep ignores ZEV scope: it acts on the whole instance.

## 4. Data model

No model or migration change. A new app `privacy` (in `INSTALLED_APPS`) holds code only.

### Settings (`config/settings.py`, environment, pinned in `config/settings_test.py`)

| Setting | Default | Meaning |
|---|---|---|
| `PRIVACY_AUDIT_NETWORK_RETENTION_DAYS` | `365` | Age of an `AuditEvent` (`created_at`) after which its IP and user agent are blanked. `0` = never. |
| `PRIVACY_EMAIL_LOG_RETENTION_DAYS` | `730` | Age of an `EmailLog` (`created_at`) after which recipient and error text are blanked. `0` = never. |
| `PRIVACY_TOKEN_GRACE_DAYS` | `30` | Days after a token stopped being usable before it is deleted. `0` = never. |

## 5. API contracts

One behaviour change: `POST /invoices/invoices/{id}/retry-email/{email_log_id}/` returns `400`
with `{"error": "The recipient of this attempt was removed by the privacy retention sweep. Send the invoice again."}`
when the log's `recipient` is `""`, before anything is queued. The order of checks is: log exists
(`404`), already sent (`400`), recipient blank (`400`), queue.

## 6. Async and integration behavior

- `privacy/sweep.py` — `sweep(*, dry_run=False, source=AuditEventSource.CELERY) -> dict`. Returns
  `{"dry_run", "audit_network", "email_log", "tokens": {"email_verification", "magic_link", "onboarding"}, "total"}`.
  A disabled step reports `0` (`{}` for tokens). Each step selects only rows that still hold something
  (`ip_address` not null or `user_agent` not empty; `recipient` or `error_message` not empty), so a
  second run reports zero. A dry run uses the same querysets with `.count()`.
- When a non-dry run changed anything it records one audit event: category `system`, action
  `privacy.swept`, target type `privacy.RetentionSweep`, `source` as passed, counts in `metadata_json`.
  An idle run and a dry run record nothing.
- `privacy/tasks.py` — `sweep_personal_data` (`@shared_task`), registered in `CELERY_BEAT_SCHEDULE` as
  `sweep-personal-data`, every 24 hours. Unlike the backup schedule it is a static entry, not an editable
  `PeriodicTask`: there is nothing for an administrator to time.
- `manage.py openzev_privacy_sweep [--dry-run]` — runs the same function with
  `AuditEventSource.MANAGEMENT_COMMAND`, for deployments without beat. Prints one line per step
  (`Would affect:` / `Affected:`) and a summary.

## 7. Frontend

None.

## 8. Implementation phases

Single phase.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The first run on a long-lived instance blanks a large audit table in one `UPDATE` | Audit rows are insert-only, so nothing contends for them; `--dry-run` shows the size first |
| An operator wants the old data | Every step is off at `0`; scrubbing is irreversible, which is the point, so the defaults are the generous end of "incident investigation" |
| Retry of a swept failed email | Refused with a message that says what to do |

## 10. Test plan

`backend/privacy/test_sweep.py` (18 tests): audit blanking keeps the event and actor, boundary of the
window, idempotence, `0` disables; email log blanking keeps status and subject; each token type
deleted only past expiry/consumption plus grace, live tokens kept (including a 10-day-old invitation
inside its 7-day lifetime plus grace), unique-live-onboarding constraint respected; dry run changes
nothing and records nothing; one audit event per effective run; an idle run records none; the command
and its `--dry-run`; the Celery task; the beat entry.
`invoices/test_batch_actions.py::TestInvoiceRetryEmailAction::test_retry_email_refuses_a_log_whose_recipient_was_swept`.
