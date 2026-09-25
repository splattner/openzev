# Email Configuration

This guide covers setting up and managing email notifications for invoices.

## Email Overview

OpenZEV sends emails asynchronously for reliable delivery:

- **Invoice notifications:** When invoices are sent to participants
- **Delivery tracking:** System logs all sends and failures via `EmailLog`
- **Retry behavior:** Failed sends are retried automatically (up to 3 retries)
- **Customization:** Email subject and body can be tailored per ZEV

## SMTP Configuration (Environment Variables)

Email delivery is configured entirely through environment variables in your `.env` file (or Docker environment). There is no admin UI for SMTP settings.

### Required Variables

| Variable | Purpose | Example |
| --- | --- | --- |
| `EMAIL_BACKEND` | Django email backend class | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `EMAIL_PORT` | SMTP server port | `587` |
| `EMAIL_USE_TLS` | Enable TLS encryption | `True` |
| `EMAIL_HOST_USER` | SMTP authentication username | `your-email@gmail.com` |
| `EMAIL_HOST_PASSWORD` | SMTP authentication password or app token | `app-specific-password` |
| `DEFAULT_FROM_EMAIL` | Sender address for all outgoing emails | `openzev@example.com` |
| `EMAIL_TIMEOUT` | Seconds to wait for the SMTP server (optional) | `20` |

### Development vs. Production

| Environment | `EMAIL_BACKEND` value | Effect |
| --- | --- | --- |
| Development | `django.core.mail.backends.console.EmailBackend` | Prints emails to console/logs (no actual delivery) |
| Production | `django.core.mail.backends.smtp.EmailBackend` | Sends emails via configured SMTP server |

Example `.env` for production:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=openzev@example.com
```

When `DEBUG=False`, `manage.py check` rejects the console backend and an SMTP
configuration without `EMAIL_HOST` or `DEFAULT_FROM_EMAIL`. The production
template includes these variables so mail delivery cannot silently fall back to
container logs.

After changing email settings, restart the backend and Celery worker:

```bash
docker compose restart backend worker
```

## Email Templates

**ZEV Owners** customize email templates in **ZEV Settings → Documents & emails**.

The sections below describe the **invoice** email, which is the one ZEV owners
customize per ZEV. Three further templates are system-wide and edited by admins
in **Platform → Templates → Email templates**: onboarding, address verification, and
the **sign-in link** email sent when a participant requests
one from the QR code on their invoice. See
[Platform Administration → Email Templates](14-admin-console.md#email-templates) for those,
including their placeholders.

### Template Fields

| Field | Purpose | Default |
| --- | --- | --- |
| **Subject** | Email subject line | `Invoice {invoice_number} – {zev_name}` |
| **Body** | Email message body | See default template below |

### Template Variables

Use placeholders to personalize emails:

| Placeholder | Replaced With | Example |
| --- | --- | --- |
| `{invoice_number}` | Invoice number | `INV-2026-001` |
| `{zev_name}` | ZEV community name | `Solar Cooperative` |
| `{participant_name}` | Participant full name | `Alice Mueller` |
| `{period_start}` | Billing period start date (formatted per regional settings) | `01.01.2026` |
| `{period_end}` | Billing period end date (formatted per regional settings) | `31.01.2026` |
| `{due_date}` | Payment due date (formatted per regional settings; empty when unset) | `14.02.2026` |
| `{total_chf}` | Invoice total in CHF | `123.45` |

### Default Template

**Subject:**
```
Invoice {invoice_number} – {zev_name}
```

**Body:**
```
Dear {participant_name},

Please find your energy invoice for the period {period_start} to {period_end} attached.

Total: CHF {total_chf}

Kind regards,
{zev_name}
```

If a template contains an invalid placeholder (typo or unsupported variable), the system logs a warning and falls back to the default template above.

## Sending Invoices

When you [send approved invoices](09-invoice-management.md#sending-invoices-by-email):

1. OpenZEV generates the PDF (if not already generated)
2. Email is created using the ZEV template, then the global admin invoice-email override, then the shipped default
3. A Celery task is queued for asynchronous delivery
4. The PDF is attached as `invoice_<number>.pdf`
5. On success, invoice status changes to `Sent` and `sent_at` is recorded

### Delivery Process

Behind the scenes:

1. **Email task queued** — `EmailLog` created with status `pending`
2. **Celery worker processes** the task
3. **Email sent** via configured SMTP — `EmailLog` status becomes `sent`, `sent_at` recorded
4. **Invoice updated** — status transitions from `Approved` to `Sent`

If email fails:
- **EmailLog status:** `failed`, error message recorded
- **Automatic retry:** retried after ~60 seconds, up to 3 retries (4 attempts in total); each attempt gets its own log entry
- **After the last failure:** no more automatic retries; use **Retry** in **Billing → Emails**

## Email Delivery Status

Each invoice tracks email delivery via `EmailLog` entries:

| Status | Meaning | Action |
| --- | --- | --- |
| **pending** | Queued, not yet processed | Wait a few seconds, refresh page |
| **sent** | Successfully delivered to SMTP server | Complete |
| **failed** | Delivery error occurred | Check error, retry or fix recipient email |

### Email History

The invoice list shows only the latest delivery status. Open **Billing →
Emails** (`/billing/emails`) for every invoice's delivery state, and
**View history** on a row for all attempts:

- **Recipient** email address
- **Subject** line
- **Status** with color indicator (amber/green/red)
- **Timestamp** of each attempt
- **Error message** (for failed attempts)
- **Retry** — shown when the latest attempt failed; queues a new delivery attempt

## Handling Email Failures

### Email Failed or Not Received

**Step 1: Check email history**
1. Open **Billing → Emails**
2. Click **View history** on the invoice's row
3. Review the error message

**Step 2: Verify recipient email**
1. Go to [Participants](03-participant-management.md)
2. Find participant
3. Check email address is correct
4. Correct if needed

**Step 3: Retry delivery**
1. In **Billing → Emails**, find the invoice
2. Click **Retry**
3. A new delivery attempt is queued
4. Check status after a few seconds

**Step 4: Manual delivery (if retries fail)**
1. Download the invoice PDF from OpenZEV
2. Send to participant manually via your own email
3. Mark the invoice as sent with **More → Mark as Sent** (only while it is still `Approved`)

### Common Issues

| Problem | Likely Cause | Fix |
| --- | --- | --- |
| All emails stuck on `pending` | Celery worker not running | `docker compose restart worker` |
| All emails failing | SMTP misconfigured or credentials wrong | Check `.env` email variables, restart backend + worker |
| Emails failing for specific participant | Invalid email address | Update email in [Participants](03-participant-management.md) |
| Emails failing for a whole domain | Provider blocking/rate-limiting | Contact provider, check SPF/DKIM/DMARC records |

## Retry Behavior

Failed emails are automatically retried by Celery:

- **Max retries:** 3 (4 attempts in total)
- **Retry delay:** ~60 seconds between attempts
- **After the last failure:** no more automatic retries; use **Retry** in **Billing → Emails**

## Archiving and Compliance

Email delivery logs are kept for compliance and audit:

- All email attempts (successful and failed) are recorded in `EmailLog`
- Timestamps, recipients, subjects, and error messages preserved
- Linked to invoices via foreign key for traceability
- Logs are ordered by most recent first

## Best Practices

**Personalize templates:** Use `{participant_name}` and `{zev_name}` for a personal touch.

**Test with console backend:** During setup, use `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` to verify email content in logs before enabling real SMTP delivery.

**Monitor delivery:** Check **Billing → Emails** regularly for persistent failures; failed deliveries also appear on **Overview**.

**Use app-specific passwords:** For Gmail and similar providers, generate an app-specific password instead of using your main account password.

**Keep contact info current:** Ensure participant email addresses are up to date in [Participants](03-participant-management.md).

## Next Steps

- **Send invoices:** [Invoice Management](09-invoice-management.md#sending-invoices-by-email)
- **Manage participants:** [Participant Management](03-participant-management.md)
- **ZEV setup:** [ZEV Setup](02-zev-setup.md)
