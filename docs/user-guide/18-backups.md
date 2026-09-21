# Backups

Back up the whole instance, or a single community, to a local directory or to
S3-compatible storage. Administrators manage backups under **Platform
administration → System Settings → Backup**.

> **Restoring from a backup is not available in the app yet.** This release takes
> and verifies backups; restoring them is the next step of the same feature. Keep
> your backups, and check them (see [Verifying a backup](#verifying-a-backup)) so
> that they are ready when restore ships.

## What a backup contains

A backup holds everything needed to rebuild what it covers:

| Whole instance | One community |
|---|---|
| Accounts, API keys, passkeys and two-factor devices | The community's settings |
| Regional settings, feature flags, VAT rates, OAuth providers | Participants and onboarding links |
| PDF and email templates | Metering points and assignments |
| Dynamic price series and their sources | Tariffs and their periods |
| Every community, in full | Meter readings, import history |
| Audit events that belong to no community | Invoices, their items, **their PDF files**, access links and email log |
| Issued contracts whose community was deleted | Issued contracts |
| | The community's audit trail |

Invoice PDFs are **files on disk**, not database rows. A plain database dump
(`pg_dump`) does not include them, so a restore from a dump alone leaves every
invoice pointing at a document that is not there. OpenZEV backups copy them in.

Not included, on purpose: short-lived login and verification tokens, sessions,
generated annual-statement downloads (they expire after a day), and the
encryption keys themselves.

## Encrypt your backups

**A backup is the most sensitive file OpenZEV can produce.** Unencrypted, it holds
password hashes, participants' names, addresses and consumption profiles, every
invoice, and the OAuth client secret in readable form.

Encryption is switched on by setting `BACKUP_ENCRYPTION_KEYS` on the server. Generate
a key with:

```bash
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

- The backup page shows a warning until a key is set, and every backup records
  whether it was encrypted.
- Backups are encrypted with AES-256-GCM. Several keys can be listed, comma
  separated: the first encrypts, every one can decrypt. To rotate, add the new
  key **in front**, take fresh backups, and drop the old key only once no backup
  you still need was made with it.
- **Keep a copy of the key somewhere other than the server.** Without it an
  encrypted backup cannot be opened — by anyone, including us. It is a separate
  secret from `MFA_ENCRYPTION_KEYS` and `SECRET_KEY`, and it is not stored in the
  backup.
- To restore a backup made on another instance you will also need that instance's
  `MFA_ENCRYPTION_KEYS`, or every two-factor secret in it is unreadable. Each
  backup records a fingerprint of the keys it needs so this can be checked before
  anything is restored.

## Destinations

A destination is where finished backups are written. Add one with **Add
destination**.

**Local directory** — an absolute path on the server. It must be outside the
media directory (archives contain private data and the media directory is served
to browsers), and it is created if it does not exist. Files are readable by the
server's user only. In a container, mount a volume there or the backups vanish
with the container.

**S3-compatible storage** — Amazon S3, MinIO, Garage, Wasabi, Backblaze B2 and
similar. Give a bucket, an optional key prefix and region, and, for anything other
than Amazon S3, the endpoint URL.

S3 credentials are taken from the first of these that applies:

1. **The server's environment** — `BACKUP_S3_ACCESS_KEY_ID` and
   `BACKUP_S3_SECRET_ACCESS_KEY`. These override everything, and keep the secret out
   of the database entirely.
2. **Stored on the destination** — the secret is encrypted with
   `BACKUP_ENCRYPTION_KEYS` and is never shown again. A secret can only be stored
   once that key is set.
3. **An instance role** — leave both credential fields empty (for example IAM roles
   for service accounts on Kubernetes).

Use **Test** on a destination to write and delete a small probe object before
relying on it. Deleting a destination never deletes the archives already written
there.

## Taking a backup

**From the app:** choose *Whole instance* or *One community*, pick a destination and
click **Back up now**. The backup runs in the background and the list updates as it
progresses. **Details** shows what a finished backup contains, including any invoice
PDFs that were referenced but missing from storage. **Download** is offered for
archives in a local directory; archives in S3 are fetched from the bucket.

**From the command line** — this needs no background worker, so it also works from
cron:

```bash
python manage.py openzev_backup --destination nightly
python manage.py openzev_backup --path /var/backups/openzev
python manage.py openzev_backup --destination nightly --zev "Sonnenhof"
```

The command warns on standard error when the archive will not be encrypted, prints
the location, size and SHA-256 of the result, and exits non-zero on failure.

A backup reads the database inside a single consistent snapshot, so it never
contains a state that did not exist. It only takes a few minutes for large
instances (millions of readings), and needs free disk space for one archive in the
server's temporary directory — set `BACKUP_WORK_DIR` to put it elsewhere.

## Verifying a backup

A backup you have never checked is a hope, not a backup.

```bash
python manage.py openzev_backup_verify /var/backups/openzev/openzev-backup-….zip.enc
```

This re-reads the whole file — decrypting it if needed — and checks every part
against the checksums recorded when it was made, that nothing has been added or
removed, and that record counts match. It changes nothing. Run it on a copy that
has been through the same path you would use in an emergency (downloaded from the
bucket, copied off the server) to catch problems in transit as well as at rest.

## What a backup does not do

- **It is a snapshot, not a log.** Restoring returns things to how they were at the
  moment the backup was taken; anything after that is lost. How often you back up
  sets how much you can lose. If you need finer recovery than that, use your
  database's own point-in-time recovery (WAL archiving with pgBackRest or wal-g) *in
  addition*.
- **Scheduling and automatic clean-up are not built in yet.** Run
  `openzev_backup` from cron for now, and delete old archives yourself.

## Settings reference

| Setting | Purpose |
|---|---|
| `BACKUP_ENCRYPTION_KEYS` | Comma-separated keys, at least 32 characters each. First encrypts, all decrypt. Optional but strongly recommended. |
| `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | S3 credentials from the environment; override any stored on a destination. |
| `BACKUP_WORK_DIR` | Where archives are assembled before being stored. Needs room for one full archive. |
| `BACKUP_RUNNER_TIMEOUT_S` | Time budget for one backup run. Default 10800 (3 hours). |
