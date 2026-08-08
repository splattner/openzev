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
| Port already in use | Another app on 8080 or 8000 | `lsof -i :8080` and kill conflicting process, or change docker-compose ports |
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

**Problem:** http://localhost:8000 returns error or no connection.

**Checks:**
1. Backend running? `docker compose ps`
2. Check logs: `docker compose logs backend`
3. Database connected? `docker compose logs db`
4. More troubleshooting: Check Redis for celery

## Authentication & Access

### Can't Login

| Symptom | Likely Cause | Solution |
| --- | --- | --- |
| "Invalid credentials" | Wrong username/password | Check [demo accounts](01-getting-started.md#demo-accounts) |
| "Account not activated" | User never received invitation | Reset password via login page |
| "Permission denied" | User role is too restrictive | Ask admin to update your role |

### Forgot Password

1. Go to login page
2. Click **Forgot Password?**
3. Enter email address
4. Check email for reset link (may be in spam)
5. Follow link to set new password

### "Unauthorized" / "403 Forbidden" Errors

**Problem:** Accessing feature you shouldn't see (permission issue).

**Cause:** Your role or ZEV scope doesn't grant access.

**Fix:**
1. Check your role: Click profile → **My Account**
2. Ask admin if you need additional access
3. Ensure you're in correct ZEV (use ZEV selector if available)

### Can't See Other ZEVs

**Expected behavior:** ZEV Owners only see assigned ZEVs.

**If you need access:** Ask an admin to assign you to the ZEV.

## Data Import & Metering

### "Metering point not found" on import

Import fails because a metering point ID in the file doesn't exist. See
[Metering Data Import → Handling Import Errors](05-metering-import.md#handling-import-errors).

### "Timestamp outside validity period"

Readings are rejected because the timestamp falls outside the meter's assignment
validity window. See [Metering Data Import](05-metering-import.md) and
[Metering Points → Assignment Validity](04-metering-points.md#assignment-validity-periods).

### Import hangs or times out

**Problem:** Large file upload gets stuck.

**Causes:**
- File too large (>1GB)
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

**Problem:** Generate invoices button disabled or returns error.

**Checks:**
1. Metering data imported? Check **Metering Data → Charting**
2. Tariffs configured? Check **Tariffs**
3. Participants active? Check **Participants**
4. Data quality OK? Check **Metering Data → Data Quality**

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
2. Open invoice → **Email History** — see error message
3. Correct email address if wrong
4. Click **Resend** on invoice

### Invoice appears but participant hasn't received email

**Problem:** Status shows **Sent** but participant hasn't received email.

**Check:**
1. Ask participant to check spam/junk folder
2. Verify email address is correct in **Participants**
3. Check **Email History** on invoice for delivery status
4. If status = **Failed**, resend manually or correct email + resend

## Performance

### Application is slow

**Problem:** Pages load slowly or create operations time out.

**Checks:**
1. Database size too large? Check storage: `docker compose exec db du -sh /var/lib/postgresql/data`
2. Many invoices? Archive old invoices to separate database
3. Memory usage? `docker stats`
4. Restart services: `docker compose restart`

### Chart rendering is slow

**Problem:** Metering Data chart takes long time to render.

**Fix:**
1. Narrow date range (select 7 days instead of year)
2. Increase resolution (daily instead of hourly)
3. Select specific metering point instead of all

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
- **Corruption:** May need to restore from backup

### Database backup

To backup PostgreSQL:

```bash
docker compose exec db pg_dump -U openzev openzev > backup_$(date +%Y%m%d).sql
```

To restore:

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
3. Monitor tasks: Check admin dashboard for queued jobs

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

- Review specific guide for your issue (e.g., [Metering Import](05-metering-import.md))
- Check [Email Configuration](10-email-configuration.md) for email issues
- Visit [GitHub Issues](https://github.com/splattner/openzev/issues) to search for your issue or report new ones
