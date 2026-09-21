# Backups

Back up the whole instance, or a single community, to a local directory or to
S3-compatible storage. Administrators manage backups under **Platform
administration → System Settings → Backup**.

> **Two kinds of restore.** One **community** can be brought back to the state of a
> backup from this page — see [Restoring one community](#restoring-one-community).
> A **whole instance** is restored from the server's command line — see
> [Restoring an instance](#restoring-an-instance). Either way, check your backups
> regularly (see [Verifying a backup](#verifying-a-backup)), and let them run by
> themselves (see [Scheduling and keeping backups](#scheduling-and-keeping-backups)).

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
  backup records a fingerprint of the keys it needs, and restoring tells you before
  it changes anything if they do not match (see
  [Restoring an instance](#restoring-an-instance)).

## Destinations

A destination is where finished backups are written. Add one with **Add
destination**.

**Local directory** — an absolute path on the server. It must be outside the
media directory (archives contain private data and the media directory is served
to browsers), and it is created if it does not exist. Files are readable by the
server's user only. In a container, mount a volume there or the backups vanish
with the container. The background worker writes the archive and later reads it
back to restore from it, and the web process serves the download, so the directory
must be the **same storage for the worker and the web process** — a shared volume,
not two containers each with their own copy of the path. If a restore fails with
*the backup file is no longer available*, this is the first thing to check.

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

**From the app:** press **Check** on a backup. It reads the stored file again — from
the local directory, or by downloading it from S3 — and records the result on the
backup: *Intact* with the date, or *Check failed* with the reason. It checks that the
bytes are the ones written (against the checksum recorded at the time, which catches
a file that decayed on disk or was tampered with even if you cannot decrypt it),
then decrypts it and checks every part, that nothing has been added or removed, and
that every section a backup must contain is there. It changes nothing.

**From the command line**, for a copy of a file:

```bash
python manage.py openzev_backup_verify /var/backups/openzev/openzev-backup-….zip.enc
```

Run it on a copy that has been through the same path you would use in an emergency
(downloaded from the bucket, copied off the server) to catch problems in transit as
well as at rest.

## Scheduling and keeping backups

### The schedule

**Backup → Schedule** turns on automatic backups: every day or every week, at a time
of day in the server's time zone (shown next to the field). Each run backs up the
**whole instance to every enabled destination**; a destination that is still busy with
the previous backup is skipped, not queued up behind it.

Two things have to be true for it to run at all, and the page says both:

- **The scheduler (beat) has to be running** next to the worker. Without it the
  schedule is saved but nothing fires. The backup page and the *System health* tab go
  red if it stops working — see below.
- **Set `BACKUP_ENCRYPTION_KEYS` first.** A schedule without a key writes unencrypted
  archives, unattended, every time. The page warns while a schedule is on with no key,
  and `python manage.py check --database default` reports it as `backups.W001`.

Changes take effect without a restart.

### Retention: how many to keep

Every destination has **Keep the latest**. Set it to `7` and, after each new backup
finishes, the destination keeps the seven newest backups of each kind — the whole
instance, and each community separately — and deletes the files of older ones.

- **The default is `0`: keep everything.** Nothing is ever deleted unless you turn
  this on.
- Deletion happens *after* a new backup has finished, never before, so a destination
  set to keep one backup is never left with none.
- The newest backup of each kind is never deleted, and neither is one that a restore
  or a check is reading right now.
- A deleted backup **stays in the list** as history ("File removed: beyond
  retention"), but can no longer be restored, downloaded or checked.
- Backups written with `--path` (no saved destination) are yours to manage: OpenZEV
  does not know that directory's bounds, so it never deletes from it.

To see what a setting *would* delete before trusting it:

```bash
python manage.py openzev_backup_sweep --dry-run
```

The same clean-up runs every hour on its own, and at the start and end of each backup.
Run `openzev_backup_sweep` from cron if you have no scheduler.

**Safety backups** — the backup of a community taken just before restoring it — are
not routine backups, so retention never counts them. They **expire after 30 days**
(`BACKUP_SAFETY_RETENTION_DAYS`; `0` keeps them). Until then, restoring from one
undoes the restore.

### Deleting a file yourself

**Delete file** on a backup removes its file from the destination (after asking) and
keeps the entry. It refuses while a restore or a check is using the backup. A
destination that still holds backup files cannot be deleted — delete their files
first, or just disable it.

### Is it working? Staleness

The backup page and **Overview → System health** show whether the instance is
actually protected. With a schedule on, backups are **stale** when the last finished
whole-instance backup is older than **twice the schedule's interval** — one missed
run is tolerated, two are a problem — or when none has ever finished. The health card
is also red when the last run failed after the last success, or when a destination is
enabled but nothing has ever succeeded; it is grey ("not set up") when no destination
is enabled at all.

Only whole-instance backups count. A backup of one community does not protect the
instance, and a safety backup is the way back from a restore, so neither can make the
instance look freshly backed up.

## Restoring an instance

Restoring a whole instance rebuilds everything a backup holds — accounts, settings,
templates, price series, every community with its readings, invoices **and their
PDF files**, issued contracts, and the audit trail — with every identifier
unchanged. It is meant for two situations: **setting up a new installation from a
backup**, and **replacing an installation with an earlier state of itself**.

It is a command on the server, not a button, on purpose: it replaces every
account, including the administrator who would be pressing the button.

### On a fresh installation

1. **Install OpenZEV and create an empty database.** Use the version that made the
   backup if you can: a backup restores only into the database structure it was
   taken from. `openzev_backup_verify` prints that version, and the restore
   command tells you exactly what to do if the two differ.
2. **Set the keys the backup needs** in the new installation's environment:
   - `BACKUP_ENCRYPTION_KEYS` — the key the backup was encrypted with, if it was.
   - `MFA_ENCRYPTION_KEYS` — the old instance's, or its members' two-factor
     secrets cannot be read. (Recovery codes and an administrator's reset still
     work, and the restore warns you if the key is missing.)
3. **Create the database structure**, and nothing else:

   ```bash
   python manage.py migrate
   ```

   Do not create users or communities. A superuser created for setup is fine; it
   is replaced by the backup's accounts.
4. **Get the archive onto the server** — copy the file, or read it straight from
   S3-compatible storage (next step).
5. **Check it first.** A dry run does everything except write:

   ```bash
   python manage.py openzev_restore --mode instance \
       --from /var/backups/openzev/openzev-backup-….zip.enc --dry-run
   ```

   It verifies the archive, checks it fits this installation, reads every record,
   and lists what would be restored. If anything is wrong it stops here and says
   what.
6. **Restore.** Stop the web and worker processes first, then run the same
   command without `--dry-run`:

   ```bash
   python manage.py openzev_restore --mode instance \
       --from /var/backups/openzev/openzev-backup-….zip.enc
   ```

   From S3-compatible storage, give the object's address; credentials come from
   `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY`, or from the server's
   role:

   ```bash
   python manage.py openzev_restore --mode instance \
       --from s3://my-bucket/openzev/openzev-backup-….zip.enc \
       --region eu-central-1 [--endpoint-url https://s3.example.com]
   ```
7. **Start the web and worker processes** and sign in with an account from the
   backup.

The restore happens in a single step: if anything fails, nothing is changed, and
the invoice PDFs it had already written are removed again. When it finishes it
prints how many records of each kind it restored, and adds an entry to the audit
log recording that the instance was restored.

### What to expect

- **Everything is as it was when the backup was taken** — including the audit
  trail, so a restored instance carries its whole history. Anything created after
  that moment is not in the backup.
- **Invoice PDFs come back under the same names.** A PDF that was already missing
  when the backup was made cannot be restored; the command tells you how many, and
  regenerating the invoice recreates it.
- **New records after a restore work normally.** The restore moves the database's
  counters past the restored records so the next new user or rate does not clash
  with an old one.
- **Destinations and schedules are not restored.** Backup destinations are
  instance configuration (they may hold credentials that belong to the old
  environment); add them again under **Backup**.

### Replacing an installation that already has data

By default the command refuses to touch an installation that has communities or
accounts — a whole-instance restore replaces **everything**, and doing it to the
wrong server would be a very bad day. To do it on purpose, add `--force`. Use
`--dry-run --force` first: it reports how many existing records would be deleted.

Take a backup of the current state first if there is any chance you want it.

### When the command refuses

| Message says | What it means | What to do |
|---|---|---|
| *not a backup* | It is a community transfer archive, not a backup | Import it from the community's settings instead |
| *single community* | It is a backup of one community | Whole-instance restore needs an instance backup; restore that community from **Backup → Restore a community** instead |
| *newer version of OpenZEV* | The backup was taken by a newer release than this one | Upgrade OpenZEV, then restore |
| *has not applied migrations* | The database structure is older than the backup's | Run `python manage.py migrate` |
| *schema is newer than the backup* | The database structure is newer than the backup's | It names the `migrate <app> <migration>` steps that bring the structure back; restore; then run `python manage.py migrate` |
| *already has data* | The installation is not empty | Restore into a fresh one, or add `--force` deliberately |
| *encrypted under a key this instance does not have* | `BACKUP_ENCRYPTION_KEYS` lacks the key | Add the key (its fingerprint is in the message) |
| *failed verification* | The file is damaged or incomplete | Use another copy; the problems are listed |

### Practise it

Restore a recent backup into a throwaway installation once, before you need to.
Time it, and write down which keys you needed and where they were. A restore
drill on a quiet afternoon is how you find out that the key was only ever on the
server that is now gone.

## Restoring one community

Use this when one community has gone wrong — a bad import, a wrong bulk edit, a
deleted community — and everything else is fine. It puts **that community** back
to the state of a backup and leaves alone:

- every **other community**,
- every **account** — no user is created, changed or deleted, not a password, not
  a two-factor device,
- the **audit trail** — it is never rewritten; the restore itself is added to it.

It works from **Platform administration → System Settings → Backup → Restore a
community**, and from the command line (below). You need a finished backup that
holds the community: an instance backup holds all of them, a single-community
backup one.

### Step by step

1. Choose the **backup** and the **community** in it, and press **Preview
   restore**. Nothing is changed. The preview is computed against the live data
   and shows, for each kind of data, how many records the backup has and how many
   there are now. The audit trail is listed as *never restored, only added to*.
2. **Read the problems.** They come in two kinds:
   - *needs your confirmation* — issued records the restore would lose: a **sent or
     paid invoice** it would delete or roll back to an earlier status, or an
     **issued contract** it would delete. You can go ahead, on purpose, with the
     switch that appears.
   - *cannot be overridden* — going ahead would damage something else: a **meter
     id** in the backup that now belongs to another community, a price source the
     backup refers to that no longer exists, an **owner** with no matching account
     (when the community has to be recreated), or an **export or another restore**
     running for that community. Resolve these first, then preview again.
3. **Choose where the safety backup goes.** Before anything is changed, the
   community *as it is now* is backed up there. If that backup fails, nothing is
   restored. It is the way back: restore from it to undo the restore.
4. **Type the community's name** and press **Restore now**. The whole restore is
   applied in one step. If anything fails, the community is exactly as it was.

### How accounts are handled

A backup refers to people by an internal number that means nothing elsewhere, so
a restore looks each person up **by email address** (then username) among today's
accounts and links them again. Someone with no matching account is listed in the
preview and left unlinked — a restore **never creates an account**. If the
community's owner has no matching account, an existing community keeps its
current owner; a community that has to be recreated cannot be, until the owner's
account exists.

### What else to know

- **A deleted community is recreated** with everything the backup holds. Its old
  audit events stay in the trail as they are.
- **Invoice PDFs** are restored under their original names. Files for invoices
  that no longer exist are left in storage.
- **Do not run it while invoices are being generated in bulk** for that
  community: there is no job to detect that, so this is on you. A running annual
  export is detected and blocks the restore.
- The restore is recorded in **History** on the same page and in the audit trail
  (`restore.created`, `restore.started`, `zev.restored`, or `restore.failed`).
  A preview is recorded as `restore.previewed`.

### From the command line

```bash
# What would it do? (exits non-zero if it would be refused)
python manage.py openzev_restore --mode zev --from /var/backups/openzev/openzev-backup-….zip.enc \
    --zev "Sonnenhof" --dry-run

# Do it, with the safety backup written to a directory you name
python manage.py openzev_restore --mode zev --from /var/backups/openzev/openzev-backup-….zip.enc \
    --zev "Sonnenhof" --path /var/backups/openzev/safety
```

`--zev` takes the community's name or id; a **deleted** community is named by id
(`openzev_backup_verify` lists the ids in a backup). Use `--destination NAME` for a
saved destination instead of `--path`. `--force` goes ahead past the
*needs your confirmation* problems. `--from` can also be an `s3://` address, as for
[restoring an instance](#restoring-an-instance).

### When it refuses

| Message says | What it means | What to do |
|---|---|---|
| *does not contain that community* | The backup was taken of other communities | Pick another backup |
| *would delete or roll back N issued record(s)* | Sent or paid invoices, or issued contracts, would be lost | Read them in the plan; go ahead only if you mean it |
| *cannot be overridden* | See step 2 above | Resolve it and preview again |
| *safety backup failed* | The safety backup could not be written | Fix the destination (**Test** it under Destinations); nothing was restored |
| *newer version* / *migrations* | The backup was made by a different version | As for [restoring an instance](#when-the-command-refuses) |

## What a backup does not do

- **It is a snapshot, not a log.** Restoring returns things to how they were at the
  moment the backup was taken; anything after that is lost. How often you back up
  sets how much you can lose. If you need finer recovery than that, use your
  database's own point-in-time recovery (WAL archiving with pgBackRest or wal-g) *in
  addition*.
- **It is not a substitute for testing a restore.** *Intact* means the file is
  complete and unchanged, not that you know how to use it. See
  [Practise it](#practise-it).
- **The schedule and retention are instance settings, not part of a backup.** After a
  whole-instance restore, add the destinations and switch the schedule on again.

## Settings reference

| Setting | Purpose |
|---|---|
| `BACKUP_ENCRYPTION_KEYS` | Comma-separated keys, at least 32 characters each. First encrypts, all decrypt. Optional but strongly recommended. |
| `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | S3 credentials from the environment; override any stored on a destination. |
| `BACKUP_WORK_DIR` | Where archives are assembled before being stored. Needs room for one full archive. |
| `BACKUP_RUNNER_TIMEOUT_S` | Time budget for one backup run. Default 10800 (3 hours). A job still `running` well past this is failed by the sweep. |
| `BACKUP_SAFETY_RETENTION_DAYS` | How long a safety backup (taken before restoring a community) is kept. Default 30; `0` keeps them until deleted. |
