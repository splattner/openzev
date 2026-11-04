# Feature Spec: Notification center (#989)

- Spec ID: SPEC-2026-11-notification-center
- Status: In Progress
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-11-04
- Target Release: next minor
- Related Issues: #989 (see also #862 document inbox, #761 parties vs. accounts, #861 draft invoices, #925 supplementary sync)
- Related ADRs: none (the "store type and payload, render in the client" decision is recorded in §4.1)
- Impacted Areas: backend | frontend | async jobs | docs

---

## 1. Problem and outcome

Things happen in OpenZEV that the people involved only learn about by looking: new metering data arrives,
an invoice is sent or paid, an import fails. Participants have to come back and check. Managers have the
readiness/attention cockpit (`2026-03-invoice-lifecycle-and-communication.md` §5.6a), which shows what is
wrong *now* but not what *happened* since they last looked. Email covers some of this, nothing in the web UI does.

Outcome: a bell in the shell header with an unread count and a list of recent notifications, each linking to
the thing it is about. A notification is an **event** ("this happened"), never a **state** ("this is wrong");
the cockpit stays the place for current problems and is not duplicated.

## 2. Scope

### In scope (first version)

| Area | Details |
|---|---|
| Model and service | `notifications.Notification`, one `notify()` function, an event registry |
| API | list (paginated, unread filter), unread count, mark one read, mark all read |
| Participant events | `invoice.sent`, `invoice.paid`, `metering.data` |
| Manager events | `import.finished`, `import.failed`, `invoices.generated`, `invoices.generation_failed` |
| Frontend | bell and panel in the shell header, polling, one renderer per type through `react-i18next` |
| Retention | read and unread windows, as a step of the privacy sweep |
| Backup and transfer | excluded from both the backup archive (`EXCLUDED_MODELS`) and the ZEV transfer archive: notifications are transient |

### Out of scope

- Every other candidate event in #989 (overdue, cancelled/replaced, annual statement, contract, tariff change,
  assignment change, security, data gap, period ready, email failed, dynamic price gap, sync failure, new
  participant, admin events). The registry makes each a small follow-up.
- Email, push, SMS or any other channel. `notify()` keeps a delivery seam (`_deliver`), nothing else is built.
- Real-time delivery (WebSocket/SSE), replies, manager-authored announcements (#862).
- Per-type muting. The registry carries a `mandatory` flag so that security types can never become mutable
  when preferences arrive.
- Feeding the audit stream. Audit is for traceability, not user-facing; the two stay separate.

## 3. Actors, permissions, and ZEV scope

Every endpoint requires authentication and returns only the caller's own notifications. There is no admin
or cross-account view. Impersonation reads as the impersonated account, like every other endpoint.

A notification has an **audience** (`manager` or `participant`) fixed when it is created. **Visibility is
decided at read time**, so a notification never reveals more than the account may see now:

| Audience | Visible while |
|---|---|
| `manager` | the recipient currently manages the notification's ZEV (`zev.access.managed_zev_ids`, i.e. an active manager grant or a managing party role) **and** the ZEV is not disabled |
| `participant` | the notification's `participant` row has `user` = the recipient and is current (`live_participant_q`: `valid_to` open or not passed) **and** the ZEV is not disabled |

Consequences:

- When a participant link ends (`valid_to` passes), or a manager grant is revoked, older notifications about
  live data disappear from the list and from the unread count. They are not deleted; if the access returns
  they reappear. The retention sweep removes them eventually.
- A manager who is also a participant sees manager notices through the grant and participant notices through
  their own participant row, and not the other way round.
- **Recipients are resolved when the event happens**, not when it is read: an account added later gets no
  backlog, and a participant without an account gets no notification and none retroactively once linked.
- **Document inbox (#862).** Not built. When it lands, a notification about a delivered document may stay
  visible after the participant link ends only if the document itself stays available; until then the
  live-access rule above applies to every type.

Frontend: the bell renders for every signed-in account in a scoped shell; no `ProtectedRoute` change.

## 4. Data model

### 4.1 Notification

**Model:** `notifications.models.Notification` (new app `notifications`).

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | UUID | `uuid4` | primary key |
| `recipient` | FK `accounts.User` | | `CASCADE`, `related_name="notifications"` |
| `zev` | FK `zev.Zev` | | `CASCADE`, `related_name="notifications"` |
| `participant` | FK `zev.Participant` | `null` | `CASCADE`; set for the `participant` audience, null for `manager` |
| `audience` | char(12) | | `NotificationAudience`: `manager`, `participant` |
| `type` | char(40) | | a key of the registry, e.g. `invoice.sent` |
| `payload` | JSON | `{}` | small, ids and the minimum needed to render the line; never amounts or names |
| `target_type` | char(40) | `""` | what the link points at: `invoice`, `metering_point`, `import_log`, `period`, or empty |
| `target_id` | char(64) | `""` | id of the target |
| `dedupe_key` | char(120) | `""` | see §4.2 |
| `created_at` | datetime | `now` | refreshed when a notification is coalesced |
| `read_at` | datetime | `null` | null = unread |

Indexes: `(recipient, read_at, -created_at)`; `(zev)`. Constraint
`notifications_one_unread_per_dedupe_key`: unique `(recipient, dedupe_key)` where `dedupe_key != ""` and
`read_at IS NULL`. Ordering: `-created_at`, `-id`.

**Store the type and payload, not rendered text.** The frontend renders through `react-i18next`, so each
account sees its own language and no user-facing string is stored. The payload may hold ids, dates, counts
and a meter id; it holds no amount, name, address or email, because those are personal data and would
outlive their source. Anything else is looked up through the normal scoped endpoints when the user opens
the target.

### 4.2 Event registry and `notify()`

**File:** `notifications/registry.py` — `EventType` dataclass (`key`, `audience`, `mandatory`, `coalesce`,
`target_type`, `payload_keys`) and `EVENTS: dict[str, EventType]`.

| Type | Audience | Target | Payload keys | Dedupe |
|---|---|---|---|---|
| `invoice.sent` | participant | `invoice` | `invoice_number`, `period_start`, `period_end` | once per invoice: `invoice.sent:<invoice id>` |
| `invoice.paid` | participant | `invoice` | `invoice_number` | once per invoice: `invoice.paid:<invoice id>` |
| `metering.data` | participant | `metering_point` | `meter_id`, `first_day`, `last_day` | coalesced per metering point per local day: `metering.data:<metering point id>:<YYYY-MM-DD>` |
| `import.finished` | manager | `import_log` | `import_log_id`, `source`, `rows_imported`, `rows_skipped`, `issues` | none |
| `import.failed` | manager | `import_log` | `import_log_id`, `source`, `rows_skipped`, `issues` | none |
| `invoices.generated` | manager | `period` | `period_start`, `period_end`, `created`, `failed` | none |
| `invoices.generation_failed` | manager | `period` | `period_start`, `period_end` | none |

A `dedupe_key` has two meanings, chosen by the registry's `coalesce` flag:

- `coalesce=False` ("once"): if the recipient already has a notification with that key, read or not,
  nothing is created.
- `coalesce=True`: if the recipient has an **unread** one, it is updated in place (payload merged by the
  type's `merge`, `created_at` refreshed); otherwise a new one is created. A daily sync therefore produces
  one line per metering point per day, not a pile; reading it and receiving more data the same day creates
  a fresh one. `metering.data` merges `first_day` as the minimum and `last_day` as the maximum.

**Function:** `notify(type, *, zev, recipients, participant_for=None, payload, target_id="", dedupe_key="", exclude=())`.

- `recipients` is an iterable of accounts, or of `(account, participant)` pairs for the participant audience;
  the resolvers `manager_accounts(zev)` and `participant_account(participant)` (in
  `notifications/recipients.py`) build them. `manager_accounts` is the accounts with an active manager grant
  plus the accounts of a managing party role (`zev.access.role_managers`), de-duplicated.
- It validates the type and payload keys against the registry (an unknown type or key raises, so tests
  catch it), then runs inside `transaction.on_commit`, so a rolled-back business transaction notifies
  nobody.
- Writing **never raises into the caller**: a failed write is logged and skipped. A notification is a
  convenience, and an invoice must not fail to send because a bell could not be written. The producer
  functions in `notifications/producers.py` are wrapped the same way (`best_effort`), so a failing
  recipient query cannot fail the action either. Unknown types and payload keys are the exception: they
  raise at once, as programming errors that the tests catch.
- Disabled ZEVs notify nobody.
- `exclude` removes accounts, used so that the manager who ran an import is not notified of their own action.
- Delivery seam: after the rows are written, `notify()` calls `_deliver(notifications)` which today does
  nothing; a future email channel hooks in there without touching a call site.

### 4.3 Producers (call sites)

| Event | Where | Rule |
|---|---|---|
| `invoice.sent` | `invoices.workflow.record_email_delivery` | only when `sent_at` was empty before (first delivery, not a resend), and the invoice status is `sent` afterwards; recipient is the invoice's participant account |
| `invoice.paid` | `workflow.record_payment` and `workflow.mark_invoice_paid` | when the status becomes `paid` |
| `metering.data` | `metering.views.ImportView._do_import`, through `notifications.producers.notify_metering_data(log)` | per metering point that received readings of the batch (`MeterReading.import_batch == log.batch_id`); recipients are accounts of participants with an assignment on that point that overlaps the covered days |
| `import.finished` / `import.failed` | the same place | `import.failed` when no row was imported and the log has errors or `result_status == "rejected"`; otherwise `import.finished` (its `rows_skipped` and `issues` tell a partial failure). The importing account is excluded |
| `invoices.generated` / `invoices.generation_failed` | `invoices.tasks.generate_zev_invoices_task` | `generated` at the end (with `failed` = participants that failed); `generation_failed` where the task records an aborted batch |

Imports that are not an upload by a person (ZEV transfer archive restore, seeding, backups) do not notify.

## 5. API contracts

Router `notifications/urls.py`, mounted at `/api/v1/notifications/` (`config/urls.py`). Permission:
`IsAuthenticated`. Querysets are built by `notifications.visibility.visible_to(user)`, the one place that
implements §3.

| Endpoint | Method | Behaviour |
|---|---|---|
| `/api/v1/notifications/` | GET | Paginated list (`PageNumberPagination`, 20 per page), newest first. `?unread=true` filters to unread, `?zev=<id>` to one ZEV. |
| `/api/v1/notifications/unread-count/` | GET | `{"count": n}`, same visibility rules. Cheap: polled. |
| `/api/v1/notifications/<id>/read/` | POST | Sets `read_at` if empty; returns the notification. 404 for another account's or an invisible one. |
| `/api/v1/notifications/read-all/` | POST | Marks every visible unread notification read, optionally limited by `?zev=`. Returns `{"updated": n}`. |

**Serializer `NotificationSerializer`** — `id`, `type`, `audience`, `zev` (id), `zev_name`, `payload`,
`target_type`, `target_id`, `created_at`, `read_at`; all read-only. `zev_name` is shown so that an account in
several communities can tell them apart.

## 6. Async and integration behavior

- No new Celery task for delivery: rows are written in the request or task that raises the event.
- **Retention** (`privacy/sweep.py`, step `notifications`, `PRIVACY_NOTIFICATION_READ_RETENTION_DAYS` default
  `30`, `PRIVACY_NOTIFICATION_UNREAD_RETENTION_DAYS` default `180`; `0` keeps everything, like the other
  steps). Read rows are deleted when `read_at` is older than the read window; unread rows when `created_at`
  is older than the unread window. The step reports a count and the `privacy.swept` audit event includes it.
- **Backup** (`backups/registry.py`): `notifications.Notification` is in `EXCLUDED_MODELS`: transient events,
  pruned by the sweep, and a restored one would announce something that happened before the backup.
- **ZEV transfer archive**: notifications are per-account and not portable, so they are not part of it.

## 7. Frontend

### 7.1 NotificationBell

**File:** `frontend/src/components/NotificationBell.tsx`, mounted in the header of `Layout.tsx`.

- Count: `useQuery({ queryKey: queryKeys.notifications.unreadCount(), queryFn: fetchUnreadNotificationCount, refetchInterval: 60_000, refetchIntervalInBackground: false })`.
- Panel: a popover (dialog semantics, focus managed, Escape closes) opened from the bell; loads
  `queryKeys.notifications.list({ unread: false })` when opened. Each row shows an icon, the rendered
  line, the community name when the account has more than one, and a relative time; unread rows are
  marked. Activating a row marks it read and navigates to its target. "Mark all read" sits in the panel
  header. Empty state through `EmptyState`.
- Mutations invalidate `queryKeys.notifications.all`.
- On a narrow viewport the panel is full-width under the header.

### 7.2 Rendering and links

`frontend/src/lib/notifications.ts` holds `notificationText(t, notification)` (key
`notifications.types.<type>` with the payload as interpolation values) and `notificationLink(notification)`:

| `target_type` | Link |
|---|---|
| `invoice` | `/billing/invoices/<id>` for the manager audience, `/me/invoices` for the participant audience |
| `metering_point` | `/me/metering-points` |
| `import_log` | `/metering/imports` |
| `period` | `/billing/invoices` |

An unknown `type` (for example a newer server) renders `notifications.types.unknown` and no link.
Strings live in all four locale files (`de`, `en`, `fr`, `it`) under `notifications.*`.

### TypeScript types

**File:** `frontend/src/types/api.ts` — `Notification`, `NotificationType` (union of §4.2 keys),
`NotificationAudience`, `NotificationPayload` (record of string, number or null).

### API client functions

**File:** `frontend/src/lib/api/notifications.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchNotifications(params)` | GET | `/notifications/` |
| `fetchUnreadNotificationCount()` | GET | `/notifications/unread-count/` |
| `markNotificationRead(id)` | POST | `/notifications/<id>/read/` |
| `markAllNotificationsRead(zevId?)` | POST | `/notifications/read-all/` |

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A notification leaks data after access ends | High | Visibility decided at read time (§3), one queryset function, tested per role and per ended link |
| Notification failure breaks a business action | High | `notify()` swallows and logs; runs in `on_commit` |
| Pile-up from frequent syncs | Medium | Coalescing per metering point per day; retention |
| Polling load | Low | One indexed count query per minute per open tab; background tabs do not poll |
| Personal data in payloads | Medium | Registry whitelists payload keys; ids and counts only |
| A new model forgotten in backup coverage | Low | `backups` coverage test fails until it is registered (done in this change) |

## 9. Test plan

### Backend — `notifications/`

- `test_visibility.py`: a manager sees manager notices of their ZEV and not of another; a viewer does not;
  a participant sees their own and not a colleague's; an ended participant link hides older notices and a
  restored one shows them again; a revoked grant hides; a disabled ZEV hides; a manager-and-participant
  account sees each audience only through the matching access; unread count follows the same rules.
- `test_service.py`: unknown type and payload key raise; `on_commit` (nothing on rollback); a failing write
  does not raise into the caller; "once" dedupe; coalescing updates an unread row and starts a new one
  after it was read; `exclude`; disabled ZEV notifies nobody; participants without an account get nothing.
- `test_api.py`: list pagination, `unread`, `zev` filter, unread count, mark read (own, other account's →
  404, invisible → 404), read all, unauthenticated 401.
- `test_producers.py`: `invoice.sent` on first delivery only, not on resend, not for a draft; `invoice.paid`
  from mark-paid and from the closing partial payment; `metering.data` per point, per day, only for
  participants whose assignment overlaps; an import excludes its uploader; `import.failed` vs
  `import.finished`; generation task success and abort; transfer import notifies nobody.
- `privacy/test_sweep.py`: the notification step (windows, `0` off, idempotent, dry run).
- `backups/test_archive.py` coverage tests keep passing with the model excluded.

### Frontend

- `tests/notification-bell.test.ts`: badge count and accessible name, empty state, mark read and navigate,
  no second mark for a read one, mark all read, community name only across communities, Escape.
- `tests/notifications.test.ts`: translation key and payload, links per target, unknown type fallback.
- `npm run lint`, `lint:style`, hex sweep, `test:unit`, `build`; screenshots at desktop and ~400px.

### Acceptance criteria

- [ ] A participant with an account sees a notification when an invoice is sent, when it is paid, and when
      new readings arrive for their metering point (one per point per day).
- [ ] Managers see import and invoice-generation outcomes; the uploader is not told of their own import.
- [ ] After a participant link ends, or a grant is revoked, their notifications stop appearing.
- [ ] No notification carries an amount, name or email address.
- [ ] A failure to write a notification never fails the action that raised it.
- [ ] Read notifications are removed after 30 days and unread after 180 by the daily sweep.
- [ ] Strings exist in `de`, `en`, `fr`, `it`; the bell works at ~400px.
