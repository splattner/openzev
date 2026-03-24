# Feature Spec: Metering point management

- Spec ID: SPEC-2026-metering-point-management
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-03-24
- Target Release: Ongoing baseline
- Related Issues: n/a (baseline)
- Related ADRs: 0001, 0005, 0007, 0009
- Impacted Areas: backend, frontend, docs

## 1. Problem and outcome

Metering points are the foundation for imports, quality checks, and billing
correctness.  Operators need predictable rules for creating, assigning, and
maintaining metering points over time.

**Outcome:** a deterministic metering-point lifecycle with strong validation,
clear role boundaries, and traceable changes that prevent billing-impacting
inconsistencies.  This spec is sufficient to re-implement the metering-point
management feature from scratch.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| MeteringPoint CRUD | Create, edit, soft-deactivate metering points within scoped ZEVs |
| Meter types | `consumption`, `production`, `bidirectional` |
| MeteringPointAssignment | Temporal ownership windows linking meters to participants |
| Assignment validation | Overlap prevention, ZEV-scope enforcement, participant-validity containment |
| Participant serializer | Exposes nested metering points and assignment status |
| Permission model | ZEV-scoped permission classes with participant read-only access |

### Out of scope

- Real-time meter device communication/provisioning
- Utility-side meter master-data synchronization beyond existing imports
- Metering data (readings, imports, quality) — see `SPEC-2026-metering-import-quality`
- Billing logic — see `SPEC-2026-tariffs-billing`

---

## 3. Data model reference

### 3.1 MeteringPoint

Defined in `zev.models`.

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `zev` | FK → `Zev` (`CASCADE`) | Owning ZEV community |
| `meter_id` | `CharField(100)` | Swiss metering-point identifier (e.g. `CH9876543210987000000000044440859`) |
| `meter_type` | `MeteringPointType` | `consumption`, `production`, or `bidirectional` |
| `is_active` | `BooleanField` (default `True`) | Soft-deactivation flag; inactive meters are not deleted |
| `location_description` | `CharField(200)` | Free-text location hint (blank allowed) |
| `created_at` | `DateTimeField` (auto) | Creation timestamp |
| `updated_at` | `DateTimeField` (auto) | Last modification timestamp |

Ordering: `["meter_id"]`.

**Design decisions:**
- Metering points have no `valid_from` / `valid_to` of their own (ADR 0001).
  Temporal ownership is modeled exclusively on `MeteringPointAssignment`.
- The formerly deprecated `MeteringPoint.participant` FK has been removed
  (ADR 0009).  Assignments are the single source of truth for ownership.

### 3.2 MeteringPointType

| Value | Label | Direction inference |
|---|---|---|
| `consumption` | Consumption | Readings default to `in` |
| `production` | Production | Readings default to `out` |
| `bidirectional` | Bidirectional (Consumption + Production) | Sign of energy value determines direction: `≥ 0 → in`, `< 0 → out` |

Direction inference is applied during the import pipeline (see
`SPEC-2026-metering-import-quality`), not during management operations.

### 3.3 MeteringPointAssignment

Defined in `zev.models`.

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `metering_point` | FK → `MeteringPoint` (`CASCADE`) | Assigned meter |
| `participant` | FK → `Participant` (`CASCADE`) | Assigned participant |
| `valid_from` | `DateField` | Start of assignment (inclusive) |
| `valid_to` | `DateField` (nullable) | End of assignment (inclusive); `null` = open-ended |
| `created_at` | `DateTimeField` (auto) | Creation timestamp |
| `updated_at` | `DateTimeField` (auto) | Last modification timestamp |

Ordering: `["-valid_from", "-created_at"]`.

**Database constraints:**

| Constraint | Fields | Description |
|---|---|---|
| `uniq_metering_point_assignment_start` | `metering_point`, `participant`, `valid_from` | Prevents duplicate assignment start dates per meter+participant pair |

### 3.4 Assignment validation rules

Assignment validation is enforced in **two layers**: the model `clean()` method
and the serializer `validate()`.  Both enforce the same rules.

#### Rule 1 — ZEV-scope match

The participant must belong to the same ZEV as the metering point:

```
participant.zev_id == metering_point.zev_id
```

Model violation → `"Participant must belong to the same ZEV as the metering point."`
Serializer violation → `{"participant": "Participant must belong to the metering point's ZEV."}` (field-level error)

#### Rule 2 — Date integrity

`valid_to` (when set) must be on or after `valid_from`:

```
valid_to >= valid_from
```

Model violation → `"valid_to must be on or after valid_from."`
Serializer violation → `{"valid_to": "valid_to must be on or after valid_from."}` (field-level error)

#### Rule 3 — Non-overlapping windows

A metering point may have **at most one active assignment at any time**.
Overlap detection query:

```python
existing.filter(
    valid_from__lte=(self.valid_to or date.max)
).filter(
    Q(valid_to__isnull=True) | Q(valid_to__gte=self.valid_from)
).exists()
```

This evaluates to `True` when any existing assignment's window intersects with
the proposed window.  On update, the current instance is excluded from the
overlap check (`exclude(pk=self.pk)`).

Violation → `"A metering point can only have one active assignment at a time."`

#### Rule 4 — Participant validity containment

Assignment dates must fall within the participant's own validity window:

```
valid_from >= participant.valid_from
valid_to   <= participant.valid_to  (when both are set)
```

Violations (raised as field-level errors in the serializer):
- `{"valid_from": "Assignment valid_from cannot be before the participant's valid_from ({date})."}`
- `{"valid_to": "Assignment valid_to cannot be after the participant's valid_to ({date})."}`

---

## 4. API endpoints

### 4.1 Metering points

Routed under `/api/v1/zev/metering-points/` via DRF `ModelViewSet`.

| Method | URL | Permission | Description |
|---|---|---|---|
| `GET` | `/metering-points/` | Authenticated (scoped) | List metering points |
| `POST` | `/metering-points/` | `MeteringPointPermission` | Create metering point |
| `GET` | `/metering-points/{id}/` | Authenticated (scoped) | Retrieve single metering point |
| `PUT/PATCH` | `/metering-points/{id}/` | `MeteringPointPermission` | Update metering point |
| `DELETE` | `/metering-points/{id}/` | `MeteringPointPermission` | Delete metering point |

### 4.2 Metering point assignments

Routed under `/api/v1/zev/metering-point-assignments/` via DRF `ModelViewSet`.

| Method | URL | Permission | Description |
|---|---|---|---|
| `GET` | `/metering-point-assignments/` | Authenticated (scoped) | List assignments (filterable, see §4.3) |
| `POST` | `/metering-point-assignments/` | `MeteringPointAssignmentPermission` | Create assignment (validated per §3.4) |
| `GET` | `/metering-point-assignments/{id}/` | Authenticated (scoped) | Retrieve single assignment |
| `PUT/PATCH` | `/metering-point-assignments/{id}/` | `MeteringPointAssignmentPermission` | Update assignment (re-validated per §3.4) |
| `DELETE` | `/metering-point-assignments/{id}/` | `MeteringPointAssignmentPermission` | Delete assignment |

### 4.3 Assignment filtering

The assignment list endpoint accepts an optional query parameter:

| Param | Type | Description |
|---|---|---|
| `metering_point` | UUID | Filter assignments to a single metering point |

### 4.4 Participant serializer enrichment

The `ParticipantSerializer` exposes computed metering-point data:

| Field | Type | Source |
|---|---|---|
| `metering_points` | `MeteringPointSerializer[]` | All distinct metering points linked via any assignment |
| `has_metering_point_assignment` | `boolean` | `True` if participant has any assignment records |

---

## 5. Actors, permissions, and ZEV scope

### 5.1 Permission classes

Both permission classes inherit from `BaseZevScopedPermission`, which resolves
the ZEV from the object (via `_get_zev()`) and enforces owner matching.

| Class | View-level (list/create) | Object-level (read/write) | Participant safe methods |
|---|---|---|---|
| `MeteringPointPermission` | Admin or ZEV owner | Admin, or owner of meter's ZEV | **Yes** — participants may read |
| `MeteringPointAssignmentPermission` | Admin or ZEV owner | Admin, or owner of assignment's ZEV | **No** |

**ZEV resolution chain** in `_get_zev()`:

| Object type | Resolution |
|---|---|
| `MeteringPoint` | `obj.zev` |
| `MeteringPointAssignment` | `obj.metering_point.zev` |

### 5.2 Queryset scoping

| ViewSet | `admin` | `zev_owner` | `participant` |
|---|---|---|---|
| `MeteringPointViewSet` | All metering points | `zev__owner = user` | Meters linked via `assignments__participant__user = user` (read-only) |
| `MeteringPointAssignmentViewSet` | All assignments | `metering_point__zev__owner = user` | `participant__user = user` (read-only, but blocked at view-level permission) |

The `MeteringPointAssignmentViewSet` queryset uses `select_related("metering_point", "metering_point__zev", "participant")` to minimize N+1 queries.

### 5.3 Permission summary matrix

| Action | `admin` | `zev_owner` (own ZEV) | `participant` |
|---|---|---|---|
| List metering points | All | Own ZEV | Own assigned meters (read-only) |
| Create metering point | Yes | Yes | No (403) |
| Update metering point | Yes | Yes (own ZEV) | No (403) |
| Delete metering point | Yes | Yes (own ZEV) | No (403) |
| List assignments | All | Own ZEV | Blocked (403 at view level) |
| Create assignment | Yes | Yes | No (403) |
| Update assignment | Yes | Yes (own ZEV) | No (403) |
| Delete assignment | Yes | Yes (own ZEV) | No (403) |

---

## 6. Serialization

### 6.1 MeteringPointSerializer

| Fields | Mode | Notes |
|---|---|---|
| All model fields | Read/write | `fields = "__all__"` |
| `id`, `created_at`, `updated_at` | Read-only | Auto-generated |

### 6.2 MeteringPointAssignmentSerializer

| Fields | Mode | Notes |
|---|---|---|
| All model fields | Read/write | `fields = "__all__"` |
| `id`, `created_at`, `updated_at` | Read-only | Auto-generated |

The serializer's `validate()` method enforces all four assignment validation
rules from §3.4. This runs on both create and update, resolving fields from the
incoming data or falling back to the existing instance values.

### 6.3 Frontend types

```typescript
interface MeteringPoint {
  id: string
  zev: string
  meter_id: string
  meter_type: 'consumption' | 'production' | 'bidirectional'
  is_active: boolean
  location_description?: string
}

interface MeteringPointAssignment {
  id: string
  metering_point: string
  participant: string
  valid_from: string
  valid_to?: string | null
  created_at: string
  updated_at: string
}
```

---

## 7. Soft deactivation

Metering points use the `is_active` boolean flag instead of hard deletion when
operational history must be preserved:

- Setting `is_active = False` marks a meter as deactivated.
- Deactivated meters remain visible in list views and are queryable.
- Historical readings, assignments, and invoice references remain intact.
- Hard deletion (`DELETE`) is allowed but cascades to readings and assignments.

**Guidance:** prefer soft deactivation when a meter has historical readings or
invoices.  Use hard deletion only for meters created in error with no data.

---

## 8. Downstream integration

### 8.1 Billing engine

The billing engine resolves participant metering points via assignments:

```python
MeteringPointAssignment.objects.filter(
    participant=participant,
    valid_from__lte=period_end,
).filter(
    Q(valid_to__isnull=True) | Q(valid_to__gte=period_start)
)
```

Only assignments overlapping the billing period are included.  The engine reads
`MeterReading` data for those meters within the period window.

### 8.2 Period overview

The invoice period-overview endpoint (see `SPEC-2026-invoice-lifecycle-comms`)
uses assignment windows to compute metering completeness per participant.

### 8.3 Data quality

The data-quality-status endpoint (see `SPEC-2026-metering-import-quality`)
resolves current participant assignment to display participant names alongside
gap detection results.

### 8.4 Import pipeline

The CSV and SDAT-CH importers look up metering points by `meter_id` within the
user's accessible ZEV scope.  The `meter_type` determines default reading
direction when no explicit direction column is present.

---

## 9. Observability, auditability, and security

- **Timestamps:** `created_at` and `updated_at` on both models provide
  modification history.
- **Role enforcement:** queryset scoping is the server-side source of truth;
  frontend route guards are UX-only.
- **Cross-ZEV isolation:** assignment validation rejects cross-ZEV
  participant-to-meter links at both model and serializer levels.
- **Cascade behavior:** `MeteringPoint` deletion cascades to readings and
  assignments.  `MeteringPointAssignment` deletion cascades from both the
  metering point and the participant side.

---

## 10. Rollout and rollback

- Tightened validations should be rolled out with compatibility checks for
  existing data.
- Rollback must not orphan participant links or invalidate historical invoice
  references.
- Recovery path must include data-fix guidance for invalid assignment windows.
- The migration that removed the deprecated `MeteringPoint.participant` FK
  backfilled missing assignments from legacy data before dropping the column
  (ADR 0009).

---

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Overlapping assignment windows causing double-counting in billing | High | Non-overlap constraint in model `clean()` + serializer `validate()` with exact overlap query (§3.4 rule 3) |
| Cross-ZEV assignment or data exposure | High | ZEV-scope checks in permissions + queryset scoping + serializer validation (§3.4 rule 1) |
| Hard-deleting meters breaks historical billing/import traceability | High | Soft-deactivation via `is_active` flag; CASCADE only on explicit delete (§7) |
| Assignment dates outside participant validity window | Medium | Containment check in serializer `validate()` (§3.4 rule 4) |
| Meter type mismatch causing wrong direction inference on import | Medium | Explicit `meter_type` validation on create/update; import pipeline uses inferenced direction (§3.2) |

---

## 12. Test plan

### Backend

Tests are distributed across `metering/tests.py` and the invoice test suite.

| Area | Validated |
|---|---|
| Queryset scoping | Admin sees all; owner sees own ZEV; participant sees assigned meters (read-only) |
| Assignment validation | Overlap rejection, ZEV-scope enforcement, participant-validity containment, date integrity |
| CRUD operations | Create/update/delete for metering points and assignments with permission checks |
| Soft deactivation | `is_active = False` preserves history; meter remains queryable |
| Billing integration | Engine resolves assignments for period; only overlapping assignments contribute readings |
| Period overview | Assignment-aware gap detection, no-assignment exclusion |

Test commands:
```
python -m pytest metering/ accounts/ invoices/ -q
```

### Frontend

- Form validation and error rendering for metering-point create/edit
- Assignment date-range picker with overlap/containment feedback
- List filtering by meter type, active/inactive status
- Build and type checks: `npm run build`

### Manual verification

- Create/modify/deactivate meters across role boundaries and verify access
  control.
- Update assignment windows mid-period (close old assignment `valid_to`, create
  new with `valid_from`) and verify no gap/overlap regression.
- Attempt cross-ZEV assignment and verify rejection.
- Confirm billing and quality views behave correctly after metering-point
  lifecycle changes.

---

## 13. Acceptance criteria

- [ ] Metering-point CRUD is fully ZEV-scope-safe for `admin` and `zev_owner` (§5)
- [ ] Participants can read their assigned metering points but cannot mutate (§5.3)
- [ ] Assignment overlap is rejected by both model and serializer validation (§3.4 rule 3)
- [ ] Cross-ZEV participant-to-meter assignment is rejected (§3.4 rule 1)
- [ ] Assignment dates must fall within participant validity window (§3.4 rule 4)
- [ ] Soft deactivation preserves historical readings, assignments, and invoice references (§7)
- [ ] Assignment queryset supports filtering by `metering_point` parameter (§4.3)
- [ ] Participant serializer exposes nested metering points and assignment flag (§4.4)
- [ ] Billing engine and period overview correctly resolve assignment windows (§8)
