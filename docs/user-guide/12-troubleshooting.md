# Troubleshooting

Common issues and solutions for OpenZEV.

## General Issues

### Application Won't Start

**Problem:** OpenZEV services don't start or crash on startup.

**Diagnosis:**
```bash
docker compose logs
```

**Common causes:**

| Symptom | Cause | Fix |
| --- | --- | --- |
| Port already in use | Another app on 8080 (dev stack: 5173, 8001, 5432, 6379) | `lsof -i :8080` and stop the conflicting process, or change the port mapping in the compose file |
| Backend exits right after starting, log names `accounts.E0xx` or `SECRET_KEY` | A required production setting in `backend/.env` is missing or wrong | Fix the named setting — see [Production with Docker Compose](01-getting-started.md#2-configure-backendenv) |
| Database connection error | PostgreSQL not running | `docker compose ps` to check db service |
| "permission denied" | File permissions issue | `docker compose down && docker compose up --build` |

### Can't Access Frontend

**Problem:** http://localhost:8080 doesn't load.

**Checks:**
1. Is frontend container running? `docker compose ps`
2. Try restarting: `docker compose restart frontend`
3. Check logs: `docker compose logs frontend`
4. Port conflict? Is port 8080 in use? `lsof -i :8080`

### Can't Access API

**Problem:** http://localhost:8080/api/docs/ returns error or no connection.

Development stack (`docker-compose.dev.yml`) uses port 8001 instead.

**Checks:**
1. Backend running? `docker compose ps`
2. Check logs: `docker compose logs backend`
3. Database connected? `docker compose logs db`
4. More troubleshooting: Check Redis for celery

## Authentication & Access

### Can't Login

| Symptom | Likely Cause | Solution |
| --- | --- | --- |
| "Invalid credentials" | Wrong username/password | Sign in with the email address, not the username. Check the [demo accounts](01-getting-started.md#demo-accounts); on a new production instance, [create the first admin account](01-getting-started.md#creating-the-first-admin-account) |
| Participant never set a password | The onboarding link was not used, or has expired | The community owner sends a new onboarding link from the participant's card |
| "Permission denied" | User role is too restrictive | Ask admin to update your role |
| Signed out on every device without logging out | Your password or email was changed, your two-factor was reset, or someone chose **Sign out everywhere** for your account | Sign in again; if you did not expect it, change your password and check with your administrator |
| Email-change link says it "does not work" | The link was already used, is older than 24 hours, or your password or address changed after you asked | Request the change again under **My Account → Profile** |
| "429 Too many requests" | Login/registration attempts exceeded the per-IP rate limit | Wait a while (check the `Retry-After` header) before trying again |

### Forgot Password

There is no "forgot password" link on the login page.

- **Participants:** ask the community owner to send the onboarding link again
  (**Participants → More → Send onboarding link**). It signs you in, and you
  choose a new password. If your invoice has a participant QR code, you can
  also request a sign-in link from the page it opens.
- **Owners and admins:** someone with server access sets a new password — see
  [Roles and Permissions → "User cannot login"](11-roles-and-permissions.md#user-cannot-login).

### "Unauthorized" / "403 Forbidden" Errors

**Problem:** Accessing feature you shouldn't see (permission issue).

**Cause:** Your role or ZEV scope doesn't grant access.

**Fix:**
1. Ask an admin to check your role under **Platform → Accounts → Users**
2. Ask for additional access if you need it
3. Ensure you're in correct ZEV (use ZEV selector if available)

### Can't See Other ZEVs

**Expected behavior:** ZEV Owners only see assigned ZEVs.

**If you need access:** Ask an admin to assign you to the ZEV.

## Data Import & Metering

### "Metering point not found" on import

Import fails because a metering point ID in the file doesn't exist. See
[Metering Imports → Handling Import Errors](05-metering-import.md#handling-import-errors).

### Readings imported but not billed

Imports do not check assignment windows: a reading on a day when the meter has
no assignment holder is stored, but billed to nobody. **Metering → Data
Quality** shows an **Unassigned readings** warning for such meters. Fix the
assignment's validity dates — see
[Metering Points → Assignment Validity](04-metering-points.md#assignment-validity-periods) —
and regenerate affected draft invoices.

### Import hangs or times out

**Problem:** Large file upload gets stuck.

**Causes:**
- File too large (the limit is 50 MB per file)
- Network timeout
- Backend processing slow

**Fix:**
1. Break large files into monthly chunks
2. Ensure stable internet connection
3. Check backend logs: `docker compose logs backend`
4. Restart service: `docker compose restart backend`

### Data quality shows mostly "Missing"

Many meters show "Missing". Diagnose the gaps with
[Metering Analysis](06-metering-analysis.md) before re-importing.

## Billing & Invoices

### "Cannot generate invoices"

**Problem:** The generate action is missing or returns an error.

**Checks:**
1. Metering data imported? Check **Metering → Chart**
2. Tariffs configured? Check **Tariffs**
3. Participants active? Check **Participants**
4. Data quality OK? Check **Metering → Data Quality**
5. Does the row say an existing invoice covers or overlaps the period? Invoices
   from an earlier billing interval block generation — follow its link to the
   blocking invoice

### Invoice totals seem wrong

**Troubleshooting:**
1. Check [billing allocation model](08-billing-allocation-explained.md) to understand calculation
2. Verify tariff prices in **Tariffs**
3. Check data quality for gaps
4. Manually verify example row:
   - Energy (kWh) × Price (CHF/kWh) = Line total (CHF)
   - Compare with invoice

**If still wrong:**
- Share the invoice **number and billing period** with support or the developer for review
- Provide the raw readings and tariff configuration used for that period

### "Cannot send invoice" / Email failed

**Problem:** Invoice marked **Sent** but email delivery failed.

**Fix:**
1. Check participant email in **Participants** — is it correct?
2. Open **Billing → Emails** → **View history** — see the error message
3. Correct email address if wrong
4. Click **Retry** there, or **More → Resend Email** on the invoice

### Invoice appears but participant hasn't received email

**Problem:** Status shows **Sent** but participant hasn't received email.

**Check:**
1. Ask participant to check spam/junk folder
2. Verify email address is correct in **Participants**
3. Check **Billing → Emails** for the delivery status
4. If status = **Failed**, resend manually or correct email + resend

## Performance

### Application is slow

**Problem:** Pages load slowly or create operations time out.

**Checks:**
1. Database size too large? Check storage: `docker compose exec db du -sh /var/lib/postgresql/data`
2. Memory usage? `docker stats`
3. Restart services: `docker compose restart`

### Chart rendering is slow

**Problem:** Metering Data chart takes long time to render.

**Fix:**
1. Narrow date range (select 7 days instead of year)
2. Use a coarser resolution (daily instead of hourly)
3. Select a specific metering point instead of the whole-ZEV total

## Database

### Database won't start

```bash
docker compose logs db
```

Common errors:
- **Permission denied:** Database volume ownership issue
  ```bash
  docker compose down
  docker compose up -d  # Fresh start
  ```
- **Disk full:** Clean up old data or expand volume
- **Corruption:** May need to restore from backup ([how](18-backups.md#restoring-an-instance))

### Database backup

Use the built-in backups: they cover the database **and** the invoice PDF files,
can be encrypted, and can be verified. See [Backups](18-backups.md). To recover
from one — on a fresh installation, over an existing one, or for one community
only — see [Restoring an instance](18-backups.md#restoring-an-instance) and
[Restoring one community](18-backups.md#restoring-one-community).

If the backup page says **backups have fallen behind**, check in this order: is the
Celery **worker** running (Overview → System health)? Is the **scheduler (beat)**
running? Did the last run fail (the reason is on the failed row)? Is the destination
reachable (**Test** it)? If a backup or restore fails with *the backup file is no
longer available*, the worker and the web process are not looking at the same local
directory: use a shared volume, or an S3 destination. See
[Scheduling and keeping backups](18-backups.md#scheduling-and-keeping-backups).

A plain database dump is still useful as an additional safety net, but **it does
not include the invoice PDFs**, which are files in the media volume
(`backend_media`), not database rows. Back that volume up as well, or a restore
leaves every invoice pointing at a document that is not there.

```bash
docker compose exec db pg_dump -U openzev openzev > backup_$(date +%Y%m%d).sql
```

To restore a dump:

```bash
docker compose exec -T db psql -U openzev openzev < backup_YYYYMMDD.sql
```

## Email & Async Jobs

### Email not being sent

Invoices stuck on **Pending** or **Failed** email delivery. See
[Email Configuration → Handling Email Failures](10-email-configuration.md#handling-email-failures).
A common cause is the Celery worker not running — check `docker compose logs worker`.

### Background jobs stuck

**Problem:** Import or invoice generation never completes.

**Fix:**
1. Restart worker service: `docker compose restart worker`
2. Check Redis: `docker compose logs redis`
3. Check worker and scheduler status under **Platform → Overview → System health**

## Getting Help

### Logs

Most issues can be diagnosed from logs:

```bash
# All services
docker compose logs

# Specific service
docker compose logs backend
docker compose logs frontend
docker compose logs worker
docker compose logs db

# With timestamps
docker compose logs -t

# Follow live (tail)
docker compose logs -f backend
```

### Export Logs for Support

```bash
docker compose logs > openzev_logs.txt
```

### System Information

When reporting issues, include:
- Docker version: `docker --version`
- Docker compose version: `docker compose --version`
- OS: Linux, Mac, Windows
- Amount of data: # of participants, invoices, metering points
- Issue reproducibility: Always? Sometimes? After import?

## Next Steps

- Review specific guide for your issue (e.g., [Metering Imports](05-metering-import.md))
- Check [Email Configuration](10-email-configuration.md) for email issues
- Visit [GitHub Issues](https://github.com/splattner/openzev/issues) to search for your issue or report new ones
