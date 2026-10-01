# ADR 0027: Access is granted per ZEV; the platform role only says "admin or not"

- Status: Accepted
- Date: 2026-10-01
- Supersedes: ADR 0003

## Context

ADR 0003 scoped every request by one platform-wide role per account (`admin`, `zev_owner`,
`participant`, `guest`) plus two single-valued relations: `Zev.owner` (a required FK to the
one account that may manage a ZEV) and `Participant.user`. That model cannot express the
relationships people actually have to communities
([#761](https://github.com/splattner/openzev/issues/761)):

- a tenant in two ZEVs needs two logins (and two passwords, two 2FA enrolments, two audit
  trails) for one person;
- an owner of one ZEV who rents in another is rejected by the account-link gate, and even if
  linked, `ZevScopedQuerySetMixin._scope_by_role` returns from the owner branch and never
  adds what they see as a participant;
- a property manager (Verwaltung) running several communities, a co-owner in a vZEV formed by
  several landowners, or a bookkeeper who only needs to look cannot be given access at all —
  only the single `Zev.owner` account can manage a ZEV.

The role and `Zev.owner` are read in several dozen places as "what can this account do", when what is meant is
almost always "what can this account do *in this ZEV*". The role also gets rewritten as a side
effect of unrelated actions (`unlink_account` demotes to `guest`, an owner change promotes and
demotes, inviting a participant sets `participant`), which shows it is really a cached guess
at the account's current relationship to one community.

#761 also separates two layers that the current model fuses: the **parties** of a ZEV (who
issues invoices, who represents it toward the grid operator — legal facts that exist whether
or not anyone logs in) and **accounts** (logins and what they may do). This ADR decides the
account layer only. The party layer (dated issuer/representative roles, replacing
`Zev.owner`) is a later phase with its own decision record.

## Decision

**1. The platform role narrows to one fact: admin or not.** `User.role` keeps two values,
`admin` and `user`. An admin sees and manages everything and needs no relationship to any
ZEV. Nothing else about an account is platform-wide. `guest` disappears: it is an account
with no relationships.

**2. Managing or viewing a ZEV is a dated, per-ZEV grant.** A new `ZevAccessGrant(zev, user,
role, valid_from, valid_to)` with `role` = `manager` (today's owner rights) or `viewer`
(sees everything a manager sees in that ZEV, changes nothing; downloads and exports are
reads). An account may hold grants in any number of ZEVs, and a ZEV may have any number of
managers and viewers. Admins and the ZEV's own managers grant and revoke; the last active
manager of a ZEV cannot be removed or downgraded. Dates follow ADR 0001's inclusive window,
so the history of who could act on a ZEV, and when, is data rather than only audit events.

**3. Participant access stays on `Participant.user`, not on a grant.** A participant row
already carries `valid_from`/`valid_to`; copying that into a membership table would create a
second source of truth for the same relationship. An account may be linked to any number of
participant rows, in the same or different ZEVs. What a participant sees ends at the row's
`valid_to`, except their invoices that were sent to them, which they keep.

**4. Scoping is the union of everything an account holds.** `ZevScopedQuerySetMixin`
returns: everything for an admin; otherwise the rows of every ZEV the account has a manager
or viewer grant for, **plus** the rows reached through its participant links. An account with
one relationship sees exactly what it sees today.

**5. Writes are default-deny below `manager`.** For unsafe methods the scoped queryset narrows
to the ZEVs the account *manages*, so any write — including custom detail actions — by a
viewer or participant to a row outside those ZEVs resolves to 404 before any view code runs.
A view that is a POST but semantically a read (creating an export job) lists itself in an
explicit allow-list. Hand-written ownership checks (`zev.owner != request.user`) become
`can_manage(user, zev)` for writes and `can_view(user, zev)` for reads, through one helper
module (`zev/access.py`); `User.is_zev_owner` is removed so no caller can keep reading the old
fact by accident.

**6. Account-level behaviour keys on the account, not a relationship.** Impersonation targets
any non-admin account and assumes everything that account holds. The 2FA policy becomes one
switch (required for every account, or for none), since a per-role policy has nothing left to
key on.

**7. `Zev.owner` stays during the transition, as the issuer pointer only.** It is still read
to find the invoice/contract issuer until the party layer replaces it, and creating a ZEV or
changing its owner ensures that account holds a manager grant. Nothing reads it for access.

## Consequences

Positive:
- One login per person, whatever their relationships; one password, one 2FA enrolment, one
  audit trail.
- Co-owners, a Verwaltung and read-only bookkeepers are representable, and managers can set
  them up without an admin.
- Access is decided per ZEV in one module, and the write rule is enforced centrally rather
  than relying on every custom action to remember an ownership check.
- The role is no longer rewritten as a side effect of linking, unlinking or ownership changes.

Trade-offs:
- The frontend shell can no longer branch on one role: it has to know the account's relation
  to the *selected* ZEV, so the ZEV switcher becomes a community switcher listing every ZEV
  the account relates to.
- Large, mechanical test churn (the old role values appear in ~75 test modules).
- A per-role 2FA policy ("only admins") is no longer expressible.
- Until the party layer lands, `Zev.owner` and the grant can diverge (an owner whose manager
  grant was revoked still appears as the issuer). That is intended — it is the case of a legal
  owner who hands management to a Verwaltung — but it is a state to keep in mind.

## Alternatives considered

1. One `ZevMembership(user, zev, role: owner | participant, valid_from, valid_to)` for both
   management and participation (the shape #761 first proposed).
   - Duplicates `Participant.valid_from/valid_to` into a second table that must be kept in
     sync with the row billing actually uses; a participant leaving would have to be ended in
     two places.
2. Keep the role and add per-ZEV grants only for co-owners and managers.
   - Leaves the role as a second, global answer to "may this account act here" that every call
     site would have to reconcile with the grants; the tenant-in-two-ZEVs and
     owner-who-rents-elsewhere cases stay broken.
3. Keep `Zev.owner` as the permanent "billing owner" and layer grants beside it.
   - Keeps the account/party fusion: the legal issuer would still have to be a login. Rejected
     for the target model; kept only as a transition (decision 7).
4. Per-membership impersonation (choose which relationship to step into).
   - Impersonation exists to see what a person sees; a person sees the union. Choosing a slice
     adds UI and a new failure mode without a use case.

## Notes

- Spec: [`docs/specs/2026-10-zev-access-grants.md`](../specs/2026-10-zev-access-grants.md).
- Prerequisite: #861 / PR #863 (participants see only invoices sent to them), whose condition
  `invoices.models.sent_to_participant()` is what former participants keep.
- Phase 2 of #761 (party roles, dropping `Zev.owner`) and phase 3 (buildings) get their own
  records.
