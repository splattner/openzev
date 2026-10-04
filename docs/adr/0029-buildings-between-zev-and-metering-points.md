# ADR 0029: Buildings sit between a ZEV and its metering points

- Status: Accepted
- Date: 2026-10-04
- Related: ADR 0028 (parties and dated roles, `landowner`), ADR 0001 (dated validity windows)

## Context

A participant's address is where its invoice goes. A metering point's location is where the
energy is used. OpenZEV only records the first
([#890](https://github.com/splattner/openzev/issues/890), #761 phase 3):

- `MeteringPoint` has a free-text `location_description` and nothing else.
- A ZEV has no address, only `Zev.postal_code`: the postal code of its grid connection, read
  only to suggest a grid operator.

The two addresses differ in ordinary cases: a landlord billed for an empty flat or the common
areas, a holiday home, a company with its head office elsewhere, a PV owner living elsewhere, a
vZEV participant with meters in two buildings. Registering a vZEV with the grid operator lists
metering points by location, and a vZEV spanning several plots records several landowners
(ADR 0028) without saying which owns what.

## Decision

**1. A building is a site of one ZEV.** A new `zev.Building` holds a name, a street address
and optionally the federal building ID (EGID). A ZEV has one or more. Buildings are not dated:
a metering point's own assignments already carry time, and a building does not stop existing
when its owner changes.

**2. Every metering point belongs to one building.** `MeteringPoint.building` is required.
`location_description` stays and now means the unit within the building (flat, floor,
"Allgemein"). A building that still has metering points cannot be deleted.

**3. `Zev.postal_code` stays the ZEV's own field.** It is the grid connection's postal code;
a ZEV has one connection whatever its number of buildings, and the grid-operator suggestion
keeps reading it. It is not derived from the buildings.

**4. The landowner link is on the role row.** `ZevPartyRole.building` (optional, landowner rows
only) says which building or plot that landowner owns. On the row, not on the party, because a
sale is dated: the seller's row ends and the buyer's starts for that one building. A party owning
two buildings holds two landowner rows. No building means "not specified", as today.

**5. The simple case stays one step.** The wizard, self-setup, admin create and a transfer
import without buildings create one building, with the address taken from the issuer's when the
issuer lives at the grid connection's postal code. Nobody sees the building level in a ZEV with
one building: the metering-point form hides the field and the list hides the column.

**6. The migration follows the ZEV type.**

- A **ZEV** (one property) gets one building, and every metering point goes into it.
- A **vZEV** joins several properties, typically one per participant, so it gets one building
  per distinct participant address (participants at the same address share one). Each metering
  point goes to the building of the participant(s) of its latest assignment; a metering point
  with no assignment, or whose latest assignees live in different buildings, goes to the ZEV's
  default building.
- The default building is the issuer's building when it has one, else a building with only
  `Zev.postal_code`, named after the ZEV.

The address guess is a starting point to be checked, not a fact: the migration cannot know
whether a participant's billing address is where its meter is. The cases this ADR exists for
(a landlord, a holiday home) are exactly the ones it guesses wrong, and the user guide says so.

**7. Buildings are managed in ZEV settings.** A new **Buildings** tab sits next to People &
access. The metering-point form picks a building, and the participant form can copy a building's
address as the billing address.

**8. The transfer archive carries buildings (format 6).** `buildings.json` travels in the
`metering_points` section, and metering points and landowner roles point at an archive building
id. Archives of format 5 and older import with the migration's rule (decision 6).

## Consequences

- Metering points can be listed by location, as the grid operator's registration of a vZEV
  needs, and a vZEV can say which landowner owns which building.
- A participant can be billed at an address other than where its meters are, with both recorded.
- Every metering-point creation path must supply a building. `MeteringPoint.save()` falls back to
  the ZEV's default building (creating it if needed), so internal paths, fixtures and the demo seed
  keep working; the API requires a choice only when the ZEV has several buildings.
- Migrated vZEVs may have more buildings than they really do (participants who live elsewhere).
  They are merged by moving the metering points and deleting the empty building.
- LEG (#515) is not ruled out: a building is not tied to a grid connection.

## Alternatives considered

- **One building per ZEV in every migration** (as first proposed in #890). Mechanical, but wrong
  for a vZEV, whose point is several properties: every metering point would claim to be in one
  place, and the operator would fix every vZEV by hand.
- **Building as a property of the participant.** Wrong for the cases this exists for: a
  landlord's empty flat and common areas, and a participant with meters in two buildings.
- **Deriving `Zev.postal_code` from the buildings.** A vZEV's buildings may span postal codes
  while its grid connection has one; the field means the connection, not a building.
- **Landowner link per party (many-to-many).** Simpler, but cannot record that a building was
  sold on a date while the seller keeps another.
- **Dated buildings.** Adds windows to every location question for no case that needs them;
  the metering-point assignments already carry time.

## Notes

- Spec: `docs/specs/2026-10-buildings-and-sites.md`.
- Issue: [#890](https://github.com/splattner/openzev/issues/890).
