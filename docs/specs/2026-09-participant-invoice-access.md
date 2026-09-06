# Feature Spec: Participant access from the invoice

- Spec ID: SPEC-2026-participant-invoice-access
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-06
- Target Release: —
- Related Issues: [#589](https://github.com/splattner/openzev/issues/589)
- Related ADRs: —
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

`send_participant_invitation()` (`backend/zev/services.py:98`) is the only door
in: it generates a temporary password, sets `must_change_password`, and emails a
username and that password. Before seeing a single number a participant must
find the email, log in with a generated password, then invent and store a new
one.

That is a poor trade for what they get. A resident checks their electricity
twice a year — when the bill arrives, and when it looks wrong. The account
outlives their interest in it by months, and the password chosen under duress is
forgotten by the next billing period. So most participants never activate, and
the consumption data that would explain the bill stays behind a login they never
passed.

The invoice, meanwhile, is already in their hands. It is the one artefact we can
be confident reached the right person.

**Outcome of this iteration:** a participant scans a QR on their invoice and
sees that invoice and what drove it, with no account. From that page they can
ask for a link to everything else, which arrives at the address already on file.
Nobody invents a password at any point.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — model | `invoices.InvoiceAccessToken`: per-invoice bearer token, revocable |
| Backend — model | `accounts.MagicLinkToken`: one-time, short-lived, issues a session |
| Backend — API | `GET /api/v1/public/invoices/<prefix>/` — tier 1, unauthenticated |
| Backend — API | `POST /api/v1/public/magic-link/request/`, `POST /api/v1/public/magic-link/consume/` — tier 2 |
| Backend — PDF | Second QR on the invoice, beside the existing QR-Rechnung |
| Backend — settings | `Zev.participant_invoice_access` opt-in flag |
| Backend — audit | `AuditEventSource.INVOICE_LINK`; issuance and consumption events |
| Frontend | `PublicInvoicePage` at `/i/:prefix`, outside `ProtectedRoute` |
| Docs | `docs/user-guide/` — operator-facing description of the opt-in |

### Out of scope

- **Replacing the password invitation.** It stays for participants who want a
  conventional account, and for owners and admins, who are unaffected by all of
  this. This spec adds a door; it does not close one.
- ~~A consumption chart on the public page.~~ **Delivered.** All three figures
  from the insights page — energy comparison, average daily profile and the
  energy-flow diagram — are served verbatim from `pdf_charts`, on their own
  cached route (§5.5).
- **A QR on the annual statement or contract.** Same mechanism would apply, but
  each document carries its own disclosure question. See §10.
- **Passwordless login for owners and admins.** A management account is not a
  document-bearer credential and should not become one.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Unchanged. Can revoke any invoice token via the admin console |
| `zev_owner` | Opts their ZEV in; can revoke tokens for their own invoices |
| `participant` | Unchanged when logged in; gains the two public paths below |
| `guest` (bearer of an invoice) | Tier 1: read that one invoice. Tier 2: request a link to the address on file — never chooses the address |

**Backend:** both public views are `permission_classes = [AllowAny]` with
`authentication_classes = []`, matching `verify_email`
(`backend/accounts/views.py:508`). Neither view reads `request.user`.

**Frontend:** `/i/:prefix` sits outside `ProtectedRoute` entirely, like the
login route.

## 4. Data model

### 4.1 `InvoiceAccessToken`

**Model:** `invoices.models.InvoiceAccessToken`

Shaped after `accounts.ApiKey` (`backend/accounts/models.py:52`) for the prefix,
which is stored in clear and indexed so a lookup costs one indexed query. It
departs from `ApiKey` on the secret, which is **not** hashed.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | PK |
| `invoice` | `FK(Invoice, CASCADE)` | — | `related_name="access_tokens"` |
| `prefix` | `CharField(16)` | — | `unique`, `db_index`. Appears in the URL |
| `secret` | `CharField(64)` | — | Stored in clear — see below |
| `created_at` | `DateTimeField` | `auto_now_add` | |
| `revoked_at` | `DateTimeField` | `null=True` | Set by owner or admin |
| `last_used_at` | `DateTimeField` | `null=True` | Written at most once per hour |

**The secret is stored in clear**, and the `ApiKey` precedent deliberately does
not carry over. An API key is hashed because its blast radius exceeds the
database it lives in: it authenticates actions across the whole API, so a leaked
key table hands an attacker capabilities they could not otherwise reach. This
token grants read access to exactly one invoice — a row in the same database as
the token. Anyone who can read this table can already read what it protects, so
hashing defends nothing that is not already open.

What hashing *would* cost is the property §4.1 requires below: a secret that
cannot be recovered cannot be reprinted, and a regenerated PDF must carry the
same QR as the copy already in the post.

The alternative — deriving the secret from `SECRET_KEY` by HMAC and storing
nothing — was rejected because rotating `SECRET_KEY` is ordinary practice and
would silently invalidate every QR ever printed, with no signal that it had
happened. A stored secret has a bounded, visible downside; a derived one has an
unbounded, silent one.

**No `expires_at`.** The token's lifetime is the invoice's: it is printed on a
document that stays meaningful for years, and a link that dies while the paper
it is printed on is still in a folder is a support ticket, not a security
control. Revocation is the control, and it is per-token or per-ZEV.

**Stability across regeneration.** `get_or_create_for_invoice(invoice)` returns
the existing unrevoked token if there is one. `Invoice.pdf_file` is persisted
(`backend/invoices/models.py:46`) and a regenerated PDF must carry the same QR
as the copy already in the post — so the token is created on first render and
reused on every subsequent one. Revoking mints nothing; the next render creates
a fresh token and the old printed link is dead, which is the intended and only
way a printed link stops working.

**The printed URL** is `{FRONTEND_URL}/i/<prefix>?s=<secret>`, built by
`access_tokens.public_url()`. It points at the SPA rather than the API because
it is a page a person opens; the route resolves the token through the API
itself.

### 4.2 `MagicLinkToken`

**Model:** `accounts.models.MagicLinkToken`

Shaped after `EmailVerificationToken` (`backend/accounts/models.py:96`), which
already does one-time email-borne authentication.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `user` | `FK(User, CASCADE)` | — | `related_name="magic_link_tokens"` |
| `token` | `CharField(64)` | — | `unique`, `db_index` |
| `created_at` | `DateTimeField` | `auto_now_add` | |
| `consumed_at` | `DateTimeField` | `null=True` | |

`is_valid()` — unconsumed and within **15 minutes**. Shorter than
`EmailVerificationToken`'s 24 h because this one mints a session rather than
confirming an address, and because the holder requested it seconds earlier.

### 4.3 `Zev.participant_invoice_access`

| Field | Type | Default | Notes |
|---|---|---|---|
| `participant_invoice_access` | `BooleanField` | `False` | Opt-in per ZEV |

Default `False`, and the migration opts nobody in — the same rule
`zev.0023_zev_itemize_tariff_bands` followed in 1.9.0. This changes a document
participants receive and exposes data without a login; that is an operator's
decision to take, not one to inherit on upgrade.

With the flag off, no QR is drawn, no token is minted, and both public endpoints
return 404 for that ZEV's invoices.

## 5. API contracts

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/public/invoices/<prefix>/` | GET | `AllowAny` | Tier 1: one invoice |
| `/api/v1/public/invoices/<prefix>/charts/` | GET | `AllowAny` | Tier 1: its three figures |
| `/api/v1/public/magic-link/request/` | POST | `AllowAny` | Tier 2: email a link |
| `/api/v1/public/magic-link/consume/` | POST | `AllowAny` | Tier 2: mint a session |

Routed under a new `public/` prefix so that "unauthenticated by design" is
visible in the URL and greppable in the router, rather than a property you learn
by reading a permission class.

### 5.1 Tier 1 — read one invoice

`GET /api/v1/public/invoices/<prefix>/?s=<secret>`

The prefix selects the row; the secret is compared against `hashed_secret` with
`hmac.compare_digest`.

**Response 200:**

```json
{
  "invoice_number": "SON-00014",
  "zev_name": "ZEV Sonnenhof",
  "participant_name": "Anna Muster",
  "period_start": "2026-01-01",
  "period_end": "2026-03-31",
  "status": "paid",
  "is_paid": true,
  "total_chf": "238.87",
  "currency": "CHF",
  "energy_summary": {
    "local_kwh": "320.5",
    "grid_kwh": "180.0",
    "total_kwh": "500.5",
    "local_share_pct": "64"
  },
  "items": [
    {"category": "energy", "description": "Solarstrom ZEV",
     "quantity": "412.500", "unit": "kWh", "unit_price": "0.22500",
     "total_chf": "92.81"}
  ],
  "pdf_url": "/api/v1/public/invoices/ab12cd34ef56/pdf/?s=…",
  "magic_link_available": true
}
```

| Status | When |
|---|---|
| 200 | Token found, not revoked, secret matches, ZEV opted in |
| 404 | Unknown prefix, revoked token, secret mismatch, or ZEV not opted in |
| 429 | Throttled |

**404 for every failure, including a wrong secret.** Distinguishing "no such
invoice" from "wrong secret" tells a scanner which prefixes exist.

`energy_summary` is `pdf_stats._build_energy_summary(invoice)` verbatim — the
same four figures the insights page prints, read off `Invoice.total_local_kwh`
and `total_grid_kwh` rather than recomputed, so the page and the paper cannot
disagree. It is `null` when the invoice has no consumption, which is the same
condition that suppresses the insights page and the QR (§6).

`is_paid` is derived from `status`, not stored twice. It is the one field that
can change after the paper was printed, and showing it is the point: "have I
paid this?" is the second question a reader has, after "what is it for?".

The response deliberately carries **no participant email, address, or bank
detail** — only what is already printed on the pages the reader is holding, plus
the line items behind the total. It does not include other invoices, other
participants, or ZEV-wide totals.

**Throttle:** `InvoiceLinkThrottle(SimpleRateThrottle)`, scoped by IP, 60/hour.
The prefix is 16 hex characters over a 32-character secret; the throttle exists
to make enumeration pointless rather than merely expensive.

### 5.2 Tier 1 — the PDF

`GET /api/v1/public/invoices/<prefix>/pdf/?s=<secret>`

Same lookup and failure behaviour; streams `Invoice.pdf_file` with
`Content-Disposition: inline`. Returns 404 when the invoice has no stored PDF
rather than rendering one on demand — an unauthenticated endpoint must not be
able to trigger a WeasyPrint render.

### 5.3 Tier 2 — request a link

`POST /api/v1/public/magic-link/request/` with `{"prefix": "...", "s": "..."}`.

The invoice token identifies the participant, so **the caller never supplies an
email address.** The link is sent to `participant.email`, which the operator set.
This removes account enumeration from the design rather than mitigating it: there
is no address field to probe.

**Response is always 202** with `{"detail": "If the account can be reached, a
link has been sent."}` — including when the participant has no email on file.

Creates the user via `ensure_participant_account()` if absent, then clears what
that helper sets for the invitation flow: the temporary password becomes
unusable and `must_change_password` goes to `False`. Nothing here transmits that
password, so leaving it usable would keep alive a credential nobody holds and
nobody can rotate — and leaving the flag set would strand a magic-link user in a
form asking them to change a password they were never given.

**Consuming a link also disarms an outstanding invitation.** A participant who
was invited, never activated, and then used a magic link instead would otherwise
leave the emailed temporary password valid indefinitely.

**Throttle:** `MagicLinkRequestThrottle` at 5/hour keyed on the **invoice
prefix**, with `InvoiceLinkThrottle`'s per-IP ceiling applying to the same view.
Keying the tighter limit on the prefix is what stops a leaked invoice being used
to bombard one mailbox, which an IP-keyed limit would not.

### 5.4 Tier 2 — consume

`POST /api/v1/public/magic-link/consume/` with `{"token": "..."}`.

Marks `consumed_at`, issues the normal auth cookies via the same helper
`verify_email` uses, and returns the user payload. Subsequent requests are an
ordinary participant session with ordinary participant scoping.

| Status | When |
|---|---|
| 200 | Valid, unconsumed, within 15 minutes |
| 400 | Unknown, consumed, or expired |
| 429 | Throttled |

### 5.5 Tier 1 — the charts

`GET /api/v1/public/invoices/<prefix>/charts/` returns the insights page as
data: `{title, intro, charts: [{key, title, description, svg}]}`, laid out on
the page the way the PDF lays it out — a section heading and intro, then each
figure under its own title and description.

**The copy travels with the pictures**, rather than being looked up in the
frontend's locale. A chart's embedded labels are rendered in the ZEV's
`invoice_language`, so a reader whose browser is English opening an invoice a
ZEV issues in German must not get an English heading over a German diagram. The
document has one language and the server knows which.

A chart that cannot be drawn is **absent**, not null: a fee-only invoice has no
consumption to profile, and the page should not have to filter holes.

**Its own route, not part of the invoice payload.** Building these runs
`build_invoice_pdf_period_context`, which reads every meter reading in the
period via `community_totals_by_timestamp`. The invoice figures are a few
indexed reads; the pictures are a full period of allocation work, and the
former must not wait behind the latter.

**Cached for an hour**, keyed on the invoice id *and* its `updated_at`. The
cache is what stops an unauthenticated caller making the server redo that work
per request; the `updated_at` component is what stops a regenerated invoice
serving the previous period's picture.

**Built by `pdf_charts`, verbatim.** The same functions the PDF calls, so the
screen and the paper cannot drift. A failure logs and returns three nulls: the
invoice already rendered without them, and failing the page for a missing
picture would be the wrong trade.

**Escaping is load-bearing here.** The flow diagram labels nodes with
`participant_name`, which an operator types, and the page injects the SVG with
`dangerouslySetInnerHTML`. Everything reaching the SVG goes through
`pdf_charts._esc`, and `test_a_hostile_participant_name_cannot_inject_markup`
asserts it — the cost of being wrong is script execution on a page served
without a session.

## 6. Async and integration behavior

**Email.** A new `EMAIL_TEMPLATE_DEFAULTS` entry `participant_magic_link`,
overridable through the existing `EmailTemplate` admin like
`participant_invitation`. Context: `participant_name`, `zev_name`, `link_url`,
`valid_minutes`.

**QR rendering.** `qrcode==8.2` is already a dependency, distinct from
`qrbill==1.2.0`. The Swiss QR-Rechnung payload is regulated and cannot carry a
portal URL, so this is a **second, separate** QR.

**It goes on the insights page** (`.insights-page`, `invoice_pdf.html:850`),
never on the payment page and never on a page carrying the QR-Rechnung. Three
reasons, in order of weight:

1. **It cannot be confused with the payment code.** `.payment-page` and
   `.insights-page` both carry `break-before: page`, so the two QRs are never
   on the same sheet — including under `inline_qr_payment`, where the slip
   sits on page 1 and the insights page is still its own.
2. **It is already the consumption page.** The link leads to the same figures
   the page prints, so the QR is an invitation to see more of what the reader
   is looking at rather than an unrelated marketing square.
3. **It costs no page.** 1.7.0 brought a typical invoice to one page plus
   insights; this adds nothing to that count.

**No insights page means no QR.** `pdf._build_access_qr()` takes
`energy_summary` as an argument rather than re-deriving the condition, so the
page and the code are decided by the same value. A fee-only invoice with no
consumption has nothing to show online and gets no QR.

**A QR failure must not cost the invoice.** `_build_access_qr` catches and logs,
returning `None`. A document that fails to render because a convenience link
could not be built would be a bad trade.

**Rendered size 24 mm**, against the QR-Rechnung's standard-fixed 46 mm, and
captioned "This is not a payment code" in all four locales. A second QR on an
invoice that did not say so would be read as the one people already expect, and
paying the wrong thing is the only failure here that costs money.

## 7. Frontend

### 7.1 `PublicInvoicePage`

**File:** `frontend/src/pages/PublicInvoicePage.tsx`

- Route: `/i/:prefix`, `?s=` in the query. Registered **outside**
  `ProtectedRoute`, alongside the login route.
- Query: `useQuery({ queryKey: ['public-invoice', prefix, s], queryFn: fetchPublicInvoice })`
- Renders: ZEV name, participant name, period, status, line items grouped by
  category in the invoice's own order, total, and a PDF download.
- A "See all my statements" action, shown when `magic_link_available`, posting
  to the request endpoint and then rendering "check your inbox" — the same panel
  whether or not an address exists, matching the 202.
- 404 renders a plain "This link is not valid" page with no detail and no retry
  affordance.

**No app chrome.** The page must not mount the authenticated `Layout`: a reader
here has no ZEV switcher, no nav, and no session, and showing the shell of an
app they cannot enter is worse than a plain document.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export interface PublicInvoiceItem {
  category: 'energy' | 'grid_fees' | 'levies' | 'metering'
  description: string
  quantity: string
  unit: string
  unit_price: string
  total_chf: string
}

export interface PublicInvoice {
  invoice_number: string
  zev_name: string
  participant_name: string
  period_start: string
  period_end: string
  status: string
  total_chf: string
  currency: string
  items: PublicInvoiceItem[]
  pdf_url: string
  magic_link_available: boolean
}
```

## 8. Audit

A new `AuditEventSource.INVOICE_LINK`, alongside `API_KEY` — which exists for
exactly this reason, so an action is traceable to the credential that took it
and not only to the person it belongs to.

| Event | When | Notes |
|---|---|---|
| `invoice_link.viewed` | Tier 1 GET succeeds | At most one per token per hour, so a reader refreshing does not flood the log |
| `invoice_link.magic_link_requested` | Tier 2 request | Records the invoice, not the email |
| `invoice_link.magic_link_consumed` | Tier 2 consume | Becomes an ordinary session afterwards |
| `invoice_link.revoked` | Owner or admin revokes | Actor is the manager |

## 9. Security model

The load-bearing claim, stated plainly so it can be argued with:

> **A link that shows only the invoice it is printed on grants the bearer
> nothing they do not already have.**

Invoices travel by post, get forwarded as PDFs to accountants and landlords, and
get printed and left on kitchen tables. The bearer set is therefore wider than
the participant, and always was — the paper carries the same figures. Tier 1
adds no disclosure to that set; it changes the format.

Tier 2 does grant something new, which is why it does not travel on paper. It
goes to the mailbox the operator recorded, and the requester never names the
destination.

Two consequences that constrain the design and are not negotiable within it:

1. **Tier 1 must never show anything the printed document does not.** That is
   the limit, and it is deliberately stated as a principle rather than a list
   of forbidden fields — an earlier draft banned "a neighbour's figure or a
   ZEV-wide total", which turned out to forbid something the paper itself
   prints.

   The energy-flow diagram is the case that settled it. It names other
   producers and shows community totals, and it is on the **same sheet as the
   QR that leads here** — a reader is looking at it while they scan. Serving it
   therefore discloses nothing to that bearer, and refusing to serve it would
   have protected nobody while making the page disagree with the paper.

   The test is not "is this figure about the reader" but "is this figure on the
   document in their hands". A second invoice, a different participant's
   invoice, or any ZEV-wide report that is not printed on this one all still
   fail it.
2. **Tier 1 resolves to one row.** Participant-wide scoping is the thing that
   has already been wrong here: #579 leaked the previous and next holder's
   readings because assignment dates were missing from the predicate. A bearer
   path that inherits that scoping is a far larger surface than one that
   resolves a prefix to a single `Invoice`.

## 10. Deferred decisions

| Decision | Taken | Revisit when |
|---|---|---|
| ~~Consumption chart on the public page~~ | Delivered — all three, verbatim (§5.5) | — |
| QR on annual statement and contract | No | Each document needs its own disclosure argument |
| Token expiry | No — revocation instead | If a leaked-invoice incident ever happens |
| Second factor on tier 1 | No | If tier 1 ever widens beyond one invoice |
| Replacing the password invitation | No | If magic-link uptake makes the password path vestigial |
| Per-participant opt-out | No — per-ZEV only | If a participant asks not to have a QR on their bill |

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| QR mistaken for the payment code | High — a misdirected payment | Separate placement, distinct size, explicit caption; never adjacent to the QR-Rechnung slip |
| Tier 1 widened later "just a little" | High — invalidates §9 | §9 states the constraint; a test asserts the response contains no other invoice's number |
| Leaked invoice used to spam a mailbox | Medium | Per-prefix throttle of 5/hour, tighter than the per-IP one |
| Operator opted in without realising | Medium — data exposed without a login | Default off, migration opts nobody in, and the setting names the consequence rather than the mechanism |
| Magic-link user trapped in a password form | Medium — no password to change | `must_change_password` explicitly not set; a test covers the full request → consume → authenticated-request path |
| Invoice regenerated, printed QR dies | Medium — support burden | `get_or_create_for_invoice` reuses the unrevoked token; a test regenerates a PDF and asserts the prefix is unchanged |
| Public endpoint triggers a render | Medium — unauthenticated CPU | The PDF route streams stored bytes only and 404s when absent |

## 12. Test plan

### Backend — `invoices/test_public_invoice_access.py`

**`PublicInvoiceAccessTests`**

| Test | Asserts |
|---|---|
| `test_valid_token_returns_the_invoice` | 200, invoice number and total match |
| `test_wrong_secret_is_404` | 404, and the body is byte-identical to the unknown-prefix 404 |
| `test_unknown_prefix_is_404` | 404 |
| `test_revoked_token_is_404` | 404 |
| `test_zev_not_opted_in_is_404` | 404 even with a valid token |
| `test_response_carries_no_other_invoice` | No other invoice number appears in the payload |
| `test_response_omits_contact_and_bank_detail` | Email, address and IBAN absent |
| `test_pdf_route_streams_stored_bytes` | 200, `application/pdf` |
| `test_pdf_route_404s_when_no_stored_pdf` | 404, and no render was attempted |

**`InvoiceAccessTokenTests`**

| Test | Asserts |
|---|---|
| `test_token_is_stable_across_pdf_regeneration` | Prefix unchanged after re-render |
| `test_revoke_then_render_mints_a_new_token` | New prefix; old one 404s |
| `test_only_the_hash_is_stored` | Secret not recoverable from the row |

**`MagicLinkTests`**

| Test | Asserts |
|---|---|
| `test_request_sends_to_the_address_on_file` | Mail sent to `participant.email`, not to anything supplied |
| `test_request_without_email_still_returns_202` | Same body as the success case |
| `test_consume_issues_a_session` | Auth cookies set; a follow-up request is authenticated |
| `test_consume_is_one_time` | Second attempt 400 |
| `test_expired_token_is_400` | Past 15 minutes |
| `test_magic_link_user_is_not_forced_into_password_change` | `must_change_password` false |
| `test_per_prefix_throttle_limits_mailbox_bombing` | Sixth request in an hour 429s |

**`PublicInvoiceAuditTests`**

| Test | Asserts |
|---|---|
| `test_view_records_one_event_per_hour` | Two views in a minute record one event |
| `test_events_use_the_invoice_link_source` | `AuditEventSource.INVOICE_LINK` |

### Frontend — `frontend/tests/public-invoice.test.ts`

Pure mapping only: the URL builder produces `/i/<prefix>?s=<secret>`, and the
404 state maps to the plain invalid-link view.

### Acceptance criteria

- [ ] A participant scans the QR on their invoice and sees that invoice, with no login
- [ ] The same link shows nothing about any other invoice or participant
- [ ] Regenerating the invoice PDF does not break a QR already in the post
- [ ] Revoking a token breaks the printed link, and nothing else
- [ ] "See all my statements" delivers a link to the address on file, and the
      requester never names that address
- [ ] A magic-link user reaches the participant portal without ever setting a password
- [ ] A ZEV that has not opted in prints no QR and serves no public route
- [ ] No migration opts an existing ZEV in

## 13. Resolved in review

| Question | Decision |
|---|---|
| Where the second QR goes | The **insights page** — never a sheet carrying the QR-Rechnung. §6 |
| Consumption figures on tier 1 | **Yes**, `energy_summary` verbatim from the insights page. §5.1 |
| `status` in the payload | **Yes** — whether it is paid is the second question a reader has. §5.1 |
| Audit event on a QR open | **Yes** — `invoice_link.viewed`, throttled to one per token per hour. §8 |

## 14. Open questions

- **Should the operator *see* the view events?** They are recorded either way
  (§8). Surfacing "this participant opened their bill" in the audit log is a
  different question from recording it, and worth deciding before the log UI
  gains a filter for it.
- **Does the savings callout belong on the public page?** `savings_data` is
  computed for the invoice already and is the most persuasive number a ZEV
  produces. It is also a claim rather than a measurement, and wants its own
  wording review.
