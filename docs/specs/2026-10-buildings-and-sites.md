# Feature Spec: Buildings and sites — where a ZEV's metering points are (#761 phase 3)

- Spec ID: SPEC-2026-10-buildings-and-sites
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-04
- Target Release: next minor
- Related Issues: [#890](https://github.com/splattner/openzev/issues/890), [#761](https://github.com/splattner/openzev/issues/761) (phase 3), #515 (LEG, not ruled out)
- Related ADRs: [ADR 0029](../adr/0029-buildings-between-zev-and-metering-points.md), [ADR 0028](../adr/0028-zev-parties-and-dated-roles.md) (`landowner` role)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

OpenZEV knows where an invoice goes (the participant's party address) but not where a meter is
(ADR 0029, Context). A vZEV's registration with the grid operator lists metering points by
location, and a vZEV with several landowners cannot say who owns which building.

**Outcome:**

- A ZEV has one or more **buildings** (address, optional EGID).
- Every metering point belongs to one building; `location_description` is the unit within it.
- A landowner role can name the building it owns.
- Buildings are managed in ZEV settings → Buildings; the simple one-building ZEV shows no new
  field anywhere else.
- Existing data migrates: one building per ZEV, one per distinct participant address in a vZEV.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Model | `zev.Building`; `MeteringPoint.building` (required); `ZevPartyRole.building` (optional, landowner only); data migration |
| Service | `zev/buildings.py`: default building, migration rule shared with the importer |
| API | `/api/v1/zev/buildings/` CRUD; `building` on metering points; `building` on party-role assign and a building change on landowner rows |
| Creation flows | Wizard, self-setup, admin create, transfer import create the default building |
| Transfer / backups | Archive format 6 (`buildings.json` in the `metering_points` section); backups registry |
| Frontend | ZEV settings → Buildings tab; building select in the metering-point form; building column and filter in the metering-point list; building on landowner rows; "copy address from building" in the participant form; "copy address from participant" in the building form |
| Demo | `seed_demo`: the vZEV demo gets more than one building |
| Docs | User guide (ZEV setup, metering points, participants, transfer), baseline specs |

### Out of scope

- Using the building in generated documents (invoices, contracts, annual statement) or template
  variables. Follow-up once the data exists.
- Dated buildings (ADR 0029 decision 1).
- Geocoding buildings or showing them on the participants map.
- Looking up EGIDs in the federal register (GWR); the EGID is typed.
- LEG (#515).
- MCP tools.

## 3. Actors, permissions, and ZEV scope

| Actor | Buildings of a ZEV |
|---|---|
| admin | Read and write in every ZEV |
| manager (grant or managing role) | Read and write in its ZEVs |
| viewer (grant) | Read in its ZEVs |
| participant | No building endpoint; sees its metering points' `building_name` through the metering-point API |
| no relation | Nothing |

Backend: `BuildingViewSet` uses `ZevScopedQuerySetMixin` with `zev_lookup = "zev"`,
`scope_parent_path = ("zev",)`, no participant path, and `BaseZevScopedPermission`
(`allow_participant_safe_methods = False`, as `PartyViewSet`). Unsafe methods
require `can_manage`; a disabled ZEV is read-only for non-admins (existing rule). Frontend: the
Buildings tab follows `useCommunityAccess().canManage` for its write controls.

## 4. Data model

### 4.1 Building

**Model:** `zev.models.Building`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` PK | `uuid4` | |
| `zev` | FK → `Zev` | — | `CASCADE`, `related_name="buildings"` |
| `name` | `CharField(200)` | — | required; a label ("Haus A", "Bahnhofstrasse 10") |
| `address_line1` | `CharField(200)` | `""` | blank |
| `address_line2` | `CharField(200)` | `""` | blank |
| `postal_code` | `CharField(10)` | `""` | blank |
| `city` | `CharField(100)` | `""` | blank |
| `egid` | `PositiveIntegerField` | `null` | blank; `MaxValueValidator(999_999_999)` (GWR EGIDs have at most 9 digits) |
| `notes` | `TextField` | `""` | blank |
| `created_at`, `updated_at` | `DateTimeField` | auto | |

`Meta.ordering = ["name", "id"]`.

**Constraints:** `UniqueConstraint(fields=["zev", "egid"], condition=Q(egid__isnull=False),
name="unique_building_egid_per_zev")`.

**Properties:** `address_lines` — `[address_line1, address_line2, "{postal_code} {city}"]`
with blanks dropped.

`__str__` → `name`.

### 4.2 MeteringPoint

| Change | Detail |
|---|---|
| `building` | New FK → `Building`, `RESTRICT`, `related_name="metering_points"`, **not null** after the migration. `RESTRICT` (not `PROTECT`) so deleting a ZEV cascades to both its buildings and its metering points |
| `clean()` | `"The building belongs to another ZEV."` when `building.zev_id != zev_id` (key `building`) |
| `save()` | When `building_id` is unset and `zev_id` is set: `building = buildings.default_building(zev)` (§4.4). Internal paths, fixtures and the seed keep working |
| `location_description` | Unchanged column; help text "Unit within the building (flat, floor, common areas)" |

### 4.3 ZevPartyRole

| Change | Detail |
|---|---|
| `building` | New FK → `Building`, null, `SET_NULL`, `related_name="landowner_roles"` |
| `clean()` | `building` set on a non-landowner row → `{"building": "Only a landowner role names a building."}`; building in another ZEV → `{"building": "The building belongs to another ZEV."}` |
| Constraint | `one_open_role_per_party` is replaced by `UniqueConstraint(fields=["zev", "party", "role", "building"], condition=Q(valid_to__isnull=True), nulls_distinct=False, name="one_open_role_per_party_building")`: a party may hold several open landowner rows, one per building |

### 4.4 Service `zev/buildings.py`

- `building_name_for(address_line1, postal_code, city, fallback)` → `address_line1` if set, else
  `"{postal_code} {city}".strip()` if set, else `fallback`.
- `address_key(party)` → `(address_line1, postal_code, city)` each stripped and casefolded;
  `None` when `address_line1` is blank (no building of its own).
- `default_building(zev)` → the ZEV's oldest building (`order_by("created_at", "id")`); when the
  ZEV has none, creates one with `initial_building_fields(zev)` and returns it.
- `initial_building_fields(zev, *, issuer=None)` → the fields of a ZEV's first building. With
  the issuer (`parties.issuer_on(zev, today)`, else the most recent issuer row's party) having an
  `address_line1`, and `zev.postal_code` blank or equal to the issuer's postal code: the issuer's
  `address_line1`, `address_line2`, `postal_code`, `city`, name via `building_name_for`. Otherwise
  `postal_code = zev.postal_code`, other address fields blank, `name = zev.name`.
- `ensure_initial_building(zev)` → `default_building(zev)` (called by every creation flow after
  the issuer role exists, so the address can default from it).
- `assign_buildings_from_participants(zev, points)` → the vZEV rule (§4.5) on live models, used
  by the transfer importer for archives without buildings.

`PartyRole` assignment (`zev/parties.py`):

- `assign_role(zev, party, role, valid_from, *, valid_to=None, building=None)`: `building` is
  only accepted for `landowner`, must be in the ZEV; the "already holds this role" check becomes
  per `(party, building)`: `"The party already owns this building."` when a building is given,
  else the existing `"The party already holds this role."`.
- `set_landowner_building(row, building)`: changes the building of a landowner row (no history
  needed; the row's dates are unchanged). Refuses non-landowner rows and an open duplicate.

### 4.5 Migration

`zev.0040_building` (schema): creates `Building`; adds `MeteringPoint.building` nullable; adds
`ZevPartyRole.building`; swaps the role constraint (§4.3).

`zev.0041_buildings_from_existing_data` (data, `RunPython`, reverse no-op): per ZEV, using
historical models:

1. Issuer party: the role row with `role="issuer"` that is open, else the one with the latest
   `valid_from`; `None` if none.
2. **`zev_type == "zev"`:** one building with `initial_building_fields` (re-implemented on the
   historical models), every metering point of the ZEV attached to it.
3. **`zev_type == "vzev"`:**
   - For each participant (ordered `party__sort_name, party__first_name, id`) whose party has an
     address key, one building per distinct key, named via `building_name_for` (fallback the ZEV
     name), with the party's address fields. Participants with the same key share a building.
   - For each metering point: take its assignments with the greatest `valid_from`; if all of
     their participants map to one building, attach it there.
   - Every other metering point (no assignment, assignees in several buildings, assignee without
     address) goes to the **default building**: the issuer's building when the issuer party's
     key is among the buildings, else a building created with `initial_building_fields`.
   - A vZEV with no participant address and no metering point still gets one building
     (`initial_building_fields`).
4. Every ZEV ends with at least one building.

`zev.0042_meteringpoint_building_required` (schema): `MeteringPoint.building` not null.

Landowner rows keep `building = NULL` (nothing records the link today).

## 5. API contracts

### 5.1 Buildings (`/api/v1/zev/buildings/`, new; `BuildingViewSet`)

`GET` list / retrieve, `POST`, `PATCH`, `DELETE` (`http_method_names` without `put`). Filter
`?zev=<uuid>`. Audited with `AuditedCreateDestroyMixin` + `AuditedUpdateMixin`:
`audit_action_category = GOVERNANCE`, `audit_action_type = "building.update"`,
`audit_target_type = "zev.Building"`, target display `name`, create/destroy metadata
`{"zev_id": …}`.

**`BuildingSerializer`** fields: `id`, `zev`, `name`, `address_line1`, `address_line2`,
`postal_code`, `city`, `egid`, `notes`, `metering_point_count`, `created_at`, `updated_at`
(read-only: `id`, `metering_point_count`, `created_at`, `updated_at`). `metering_point_count`
from a queryset annotation, falling back to a live count. `zev` is not changeable on update
(`"A building cannot move to another ZEV."`). `egid` duplicate within the ZEV →
`{"egid": "Another building of this ZEV has this EGID."}`.

**`DELETE`:** `400 {"detail": "This building still has metering points."}` when it has any.
Landowner rows pointing at it are unlinked (`SET_NULL`).

### 5.2 Metering points

`MeteringPointSerializer` gains `building` (writable, `PrimaryKeyRelatedField`, not required)
and `building_name` (read-only, `source="building.name"`). `validate()`:

- `building` given and in another ZEV → `{"building": "The building belongs to another ZEV."}`.
- On create without `building`: the ZEV's only building is used; with several buildings →
  `{"building": "Choose the building of this metering point."}`; with none → the default
  building is created (§4.4).

`MeteringPointViewSet.get_queryset` adds `select_related("building")`; `?building=<uuid>`
filters.

### 5.3 Party roles

- `ZevPartyRoleAssignSerializer` gains `building` (optional, nullable); passed to
  `assign_role`. Non-landowner with a building → 400 (`building` key).
- `ZevPartyRoleSerializer` gains `building` and `building_name` (read-only, null when unset).
- New `POST /api/v1/zev/party-roles/{id}/building/` (`ZevPartyRoleBuildingSerializer`:
  `building` nullable) → `set_landowner_building`; manage permission; audited as
  `party_role.building` (GOVERNANCE) with metadata `{"role", "party", "building"}`.

### 5.4 Self-setup and wizard

Request shapes unchanged. `OwnerMeteringPointInputSerializer` unchanged (points go to the
created building).

## 6. Creation flows

| Flow | Where | Building |
|---|---|---|
| Admin wizard | `services.create_zev_with_owner_setup` | `ensure_initial_building(zev)` after `ensure_initial_roles`; its metering points created with that building |
| Self-setup | `services.create_zev_for_existing_owner` | `ensure_initial_building(zev)` after the roles |
| Admin create | `ZevViewSet.create` | `ensure_initial_building(zev)` (no issuer yet → postal code only) |
| Transfer import | `transfer/importer.py` | §8 |
| Seed demo | `seed_demo` | the ZEV demo: one building; the vZEV demo: one building per participant house, metering points attached accordingly |

## 7. Frontend

### 7.1 Types (`frontend/src/types/api.ts`)

```ts
export interface Building {
    id: string
    zev: string
    name: string
    address_line1: string
    address_line2: string
    postal_code: string
    city: string
    egid: number | null
    notes: string
    metering_point_count: number
    created_at: string
    updated_at: string
}
export type BuildingInput = Pick<Building, 'zev' | 'name' | 'address_line1' | 'address_line2'
    | 'postal_code' | 'city' | 'egid' | 'notes'>
```

`MeteringPoint` gains `building: string`, `building_name: string`; `MeteringPointInput` gains
`building?: string`. `ZevPartyRole` gains `building: string | null`, `building_name: string | null`.
`ZevSettingsTab` gains `'buildings'`.

### 7.2 API client (`lib/api/zev.ts`, `queryKeys.ts`)

`fetchBuildings(zevId)`, `createBuilding`, `updateBuilding`, `deleteBuilding`,
`setPartyRoleBuilding(roleId, building)`; `assignPartyRole` accepts `building`. Query key
`zev.buildings(zevId)`; building mutations invalidate it and the metering-point list.

### 7.3 ZEV settings → Buildings (`features/zev/ZevBuildingsSection.tsx`, `BuildingFormModal.tsx`)

- New tab `buildings` between `people` and `billing`; route `/zev-settings/buildings`; in
  `OUTSIDE_THE_FORM` (saves on its own).
- A list of buildings (name, address lines, EGID, metering-point count, landowners whose role
  names it), following `2026-04-frontend-management-page-design.md` (card list, "Add building"
  primary action, row actions edit / delete with icons).
- Delete is disabled with a tooltip when `metering_point_count > 0`.
- `BuildingFormModal`: name, address (line 1, line 2, postal code, city), EGID (number input),
  notes; on create, a "Copy address from participant" select (participants' parties with an
  address) that fills the address and, when the name is empty, the name.
- Intro text explains the building is where the meters are, as opposed to the billing address.

### 7.4 Metering points (`features/meteringPoints/*`)

- `MeteringPointFormModal`: a "Building" select, shown when the ZEV has more than one building
  (with one, the field is hidden and the building is sent implicitly by the backend default).
  `location_description` label becomes "Unit within the building".
- `MeteringPointsList`: a building column/line when the ZEV has more than one building.
- `MeteringPointsToolbar`: a building filter when the ZEV has more than one building.

### 7.5 People & access (`features/zev/ZevPartiesSection.tsx`)

- Landowner rows show their building's name, and an action to set or change it (select of the
  ZEV's buildings, plus "Not specified").
- Assigning a landowner offers an optional building select.
- `landownersHint` text: the owners of the plots or buildings; with several buildings, link each
  landowner to the one it owns.

### 7.6 Participants (`features/participants/ParticipantFormModal.tsx`)

When the ZEV has a building with an address, the create form shows "Copy address from building"
(select of buildings; one building → a button) that fills the billing address fields.

### 7.7 i18n

All new strings in `de`, `en`, `fr`, `it` (`pages.zevSettings.tabs.buildings`,
`pages.zevSettings.buildings.*`, `pages.meteringPoints.form.building`,
`pages.participants.form.copyFromBuilding`, …).

## 8. Transfer archive and backups

- `FORMAT_VERSION = 6`, `SUPPORTED_FORMAT_VERSIONS = {1, 2, 3, 4, 5, 6}`.
- `BUILDINGS_FILE = "buildings.json"`, written with the `metering_points` section:
  `[{"id": <archive id>, **BUILDING_FIELDS}]`, `BUILDING_FIELDS = ("name", "address_line1",
  "address_line2", "postal_code", "city", "egid", "notes")`.
- `METERING_POINT_FIELDS` export also `"building_id"` (archive id); `PARTY_ROLE_FIELDS` export
  `"building_id"` (archive id or null).
- `SUBCOUNT_SECTIONS["buildings"] = SECTION_METERING_POINTS`; manifest counts include
  `buildings`.
- **Import order:** when `metering_points` is selected and the archive is format ≥ 6, buildings
  are imported right after the ZEV, before the participants section, so landowner roles can
  resolve their building. A landowner role whose building is absent (metering points not
  selected) imports without one.
- **Archives < 6, or metering points selected without buildings:** metering points import
  without a building, then `assign_buildings_from_participants` applies the §4.5 rule.
- **No metering-points section:** the importer calls `ensure_initial_building(zev)` after the
  participants section.
- Backups: `Building` added to `backups/registry.py` before `MeteringPoint` (FK order).

## 9. Observability and audit

Building create / update / delete are audit events (§5.1). A metering point's building change is
covered by the existing metering-point update event. Landowner building changes:
`party_role.building`.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| A migrated vZEV has a building per participant even where a participant's billing address is not its meter's location | The rule is documented as a guess; the Buildings tab shows the metering-point count, and merging is moving points then deleting the empty building |
| A metering-point creation path forgets the building | `MeteringPoint.save()` default; the column is not null |
| Restore from backup: FK order | Registry order test |
| Constraint swap on `ZevPartyRole` fails on duplicate open rows | The old constraint was stricter, so no existing data violates the new one |

## 11. Test plan

Backend (`backend/zev/test_buildings.py`, new):

- model: EGID uniqueness per ZEV; `MeteringPoint.save()` default building (none → created; one
  → used); building in another ZEV rejected in `clean()`.
- `initial_building_fields`: issuer address copied when postal codes match or ZEV postal code
  blank; only ZEV postal code otherwise; no issuer.
- migration rule (function tested directly, plus a migration test with `MigrationExecutor`):
  ZEV → one building, all points; vZEV → per distinct address, shared address → one building,
  shared metering point across buildings → default, unassigned → default, issuer building is the
  default.
- API: CRUD per role (admin, manager, viewer read-only, participant 404/403, unrelated 404);
  delete with metering points → 400; EGID duplicate → 400; disabled ZEV read-only.
- metering-point API: building required with several buildings; implicit with one; cross-ZEV
  building rejected; `?building=` filter.
- party roles: landowner with building; non-landowner with building → 400; same party two
  buildings allowed; same building twice → 400; `building/` action; audit events.
- creation flows: wizard, self-setup, admin create each create one building with the expected
  address; wizard points attached.

Backend (`backend/zev/test_transfer.py`): format 6 round trip (buildings, point buildings,
landowner building); format 5 archive → vZEV rule; metering points not selected → default
building; landowner role keeps no building when buildings are not imported.

Backend (`backend/backups`): registry order covers `Building`.

Frontend unit tests: building select visible only with several buildings; copy address from
building fills the participant form.

## 12. Acceptance criteria

- Every existing metering point has a building after the migration; vZEVs get one per
  participant address.
- A new ZEV (wizard, self-setup, admin create) has one building with the issuer's address when it
  matches the grid connection's postal code.
- In a one-building ZEV, the metering-point form and list look as before.
- A landowner can be linked to the building it owns, including two buildings for one party.
- Format 6 archives round-trip buildings; format ≤ 5 archives import with the migration rule.
- `mkdocs build --strict`, backend and frontend CI checks pass.
