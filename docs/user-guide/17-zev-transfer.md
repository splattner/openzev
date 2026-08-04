# ZEV Export and Import

Export a whole community as a single archive file and import it into the same or
another OpenZEV instance. This replaces the old tariff-only JSON transfer: an
export with just the Tariffs section selected does what that used to do.

## What it is for

- **Moving a community between instances** — from a trial installation to a
  production one, or between hosting providers.
- **Taking a copy off the instance** — an archive is a complete, readable record
  of a community's structure, readings and billing history.
- **Starting a new community from an existing one** — export the tariffs and the
  metering-point layout, import them, then add participants by hand.

**It is not a disaster-recovery restore.** An import always creates a *new* ZEV
with new internal identifiers, so anything referring to the old ones — audit log
entries, bookmarked links, references held by other systems — does not follow.
The archive records the original identifiers so a true in-place restore can be
added later, but today an import is a copy.

## Exporting

1. Open **(v)ZEV verwalten → Einstellungen** for the community.
2. Scroll to **Export ZEV** and click **Export ZEV**.
3. Tick the sections you want.
4. Click **Download archive**.

You get a file named `openzev-export-<community>-<date>.zip`.

> **An export is a personal-data extract.** It contains participants' names,
> addresses, email addresses and their full consumption profiles in one file.
> Treat it the way you would treat the participant list itself: encrypt it in
> transit, and delete it once the transfer is done. Every export is recorded in
> the audit log with the sections that left the instance.

### Sections

| Section | What travels |
|---|---|
| **ZEV settings** | Name, type, grid operator, billing interval, invoice prefix and language, payment term, bank details, VAT number, notes, the invoice email template, and the contract-PDF notes |
| **Participants** | Names, addresses, contact details and validity windows |
| **Metering points & assignments** | Meters and which participant held each one over which period |
| **Tariffs** | Every tariff, all its versions, and their price bands |
| **Meter readings** | Every reading, as one CSV per meter |
| **Invoices** | Invoices and their line items |

Some sections need others. Assignments point at participants, readings point at
metering points, and invoices point at participants — so the dialog greys out a
section whose prerequisite is unticked and tells you what it needs. You cannot
build an archive that could not be imported.

Tariffs and invoices are deliberately **independent** of one another: an invoice
records what was charged rather than pointing at a live tariff, so billing
history can travel without the pricing structure and vice versa.

### What deliberately does not travel

- **User accounts.** Participants are exported without any link to a login, so an
  archive can never grant anybody access to anything.
- **Generated invoice PDFs.** They are regenerable from the invoice data. Note
  that a regenerated PDF uses *today's* template, so it will not be byte-identical
  to the document the participant received — if you have a retention obligation
  for the original documents, keep them separately.
- **Email and PDF templates** stored in the admin console. These are
  instance-wide customisations rather than ZEV data. The per-ZEV invoice email
  template and contract notes *do* travel, in the ZEV settings section.
- **Audit events, import logs and system settings.** Instance-scoped.

## Importing

Importing is **admin-only**, because it creates a ZEV and only admins create
ZEVs on an OpenZEV instance.

1. Open **Admin Console → ZEVs**.
2. Click **Import ZEV**.
3. Choose the `.zip` archive. OpenZEV reads its manifest and shows what is inside,
   with a row count per section.
4. Optionally rename the new community.
5. Untick anything you do not want.
6. Click **Import**.

The importing admin becomes the owner of the new ZEV.

> **Importing twice creates two communities.** There is no "have I already
> imported this?" check, so if you are unsure whether an import went through,
> look at the ZEV list rather than clicking again.

### Participants arrive unlinked

Even when an account with the same email address already exists on the instance,
imported participants are **not** connected to it. Matching on an email address
found inside an uploaded file would let anyone who can edit that file hand an
existing account access to a community's data. Link accounts by hand afterwards —
see [Participant Management](03-participant-management.md).

### Invoice numbering

If the archive carries invoices, the new ZEV's invoice counter is set above the
highest number imported, so the next billing run cannot mint a number the
community already has. Importing without the invoice section starts numbering at
1.

## When an import is rejected

Nothing is created unless **everything** validates. If any entry fails, the whole
import is rolled back and the dialog lists every problem it found at once — by
section, entry and reason — so an archive with several issues takes one pass to
diagnose rather than one per issue.

### Meter IDs are unique across the whole instance

This is the most common rejection. A meter ID identifies a physical meter, and
OpenZEV allows it to exist only once per instance — so a community cannot be
imported alongside one that already holds the same meters:

```
Metering point 'CH-DEMO-CONS-0001' already exists on this instance.
Meter ids are unique instance-wide, so this ZEV cannot be imported
alongside the one that already holds this meter.
```

Every colliding meter is named. This is what you will hit trying to import a ZEV
back into the instance you exported it from. Either delete the original first, or
import into a different instance — which is what the feature is for.

### Format versions

Every archive records the format version it was written with. An archive from a
newer OpenZEV than the one you are importing into is **refused outright** rather
than partially understood:

```
Unsupported archive format version 2. This instance reads version(s): 1.
```

Upgrade the target instance and try again.

## Archive contents

The archive is an ordinary ZIP; you can open it to check what you are about to
move.

```
openzev-export-demo-community-2026-08-04.zip
  manifest.json          format version, export time, sections, row counts
  zev.json               community settings
  participants.json
  metering_points.json   including assignments
  tariffs.json           versions and price bands
  invoices.json          invoices and line items
  readings/<meter>.csv   one file per meter
```

Readings use the same column layout the
[metering import](05-metering-import.md) reads — `meter_id`, `timestamp`,
`energy_kwh`, `direction` — plus `resolution` and `import_source` so nothing is
lost in a round trip. An individual CSV can therefore be fed to the normal
metering import if you only want one meter's data.

## Size and timing

Archives compress well, because meter readings are highly repetitive. As a
reference point, a three-meter community with four months of 15-minute data —
34,848 readings — produces a 180 KB archive in about a second, and imports in
about seven.

A large community with several years of data will take proportionally longer, and
the export runs while your browser waits. If you are moving something very large
and the request times out, export in sections — structure first, then readings —
and import them as separate steps.

## Related

- [ZEV Setup](02-zev-setup.md) — creating a community from scratch
- [Participant Management](03-participant-management.md) — linking accounts after an import
- [Metering Import](05-metering-import.md) — loading readings on their own
- [Admin Console](14-admin-console.md) — where the import lives
