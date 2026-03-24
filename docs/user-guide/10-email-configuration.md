# Email Configuration

This guide covers setting up and managing email notifications for invoices.

## Email Overview

OpenZEV sends emails asynchronously for reliable delivery:

- **Invoice notifications:** When invoices are sent to participants
- **Delivery tracking:** System logs all sends and failures via `EmailLog`
- **Retry behavior:** Failed sends are retried automatically (up to 3 times)
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

After changing email settings, restart the backend and Celery worker:

```bash
docker compose restart backend worker
```

## Email Templates

**ZEV Owners** customize email templates in **ZEV Settings → Email Templates**.

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

When you [send approved invoices](09-invoice-management.md#sending-invoices):

1. OpenZEV generates the PDF (if not already generated)
2. Email is created using the ZEV's template (or the default)
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
- **Automatic retry:** Celery retries after ~60 seconds, up to 3 attempts total
- **After 3 failures:** Task stops retrying; use manual retry from the UI

## Email Delivery Status

Each invoice tracks email delivery via `EmailLog` entries:

| Status | Meaning | Action |
| --- | --- | --- |
| **pending** | Queued, not yet processed | Wait a few seconds, refresh page |
| **sent** | Successfully delivered to SMTP server | Complete |
| **failed** | Delivery error occurred | Check error, retry or fix recipient email |

### Email History

On the invoice list, click the **email status indicator** to open the **Email History** modal. This shows all email attempts for that invoice:

- **Recipient** email address
- **Subject** line
- **Status** with color indicator (amber/green/red)
- **Timestamp** of each attempt
- **Error message** (for failed attempts)
- **Retry button** — for failed emails, click to queue a new delivery attempt

## Handling Email Failures

### Email Failed or Not Received

**Step 1: Check email history**
1. Open invoice list
2. Click the email status indicator for the invoice
3. Review the error message in the Email History modal

**Step 2: Verify recipient email**
1. Go to [Participants](03-participant-management.md)
2. Find participant
3. Check email address is correct
4. Correct if needed

**Step 3: Retry delivery**
1. Open Email History modal for the invoice
2. Click **Retry** on the failed email log entry
3. A new delivery attempt is queued
4. Check status after a few seconds

**Step 4: Manual delivery (if retries fail)**
1. Download the invoice PDF from OpenZEV
2. Send to participant manually via your own email
3. Mark the invoice as sent using the **Mark Sent** action

### Common Issues

| Problem | Likely Cause | Fix |
| --- | --- | --- |
| All emails stuck on `pending` | Celery worker not running | `docker compose restart worker` |
| All emails failing | SMTP misconfigured or credentials wrong | Check `.env` email variables, restart backend + worker |
| Emails failing for specific participant | Invalid email address | Update email in [Participants](03-participant-management.md) |
| Emails failing for a whole domain | Provider blocking/rate-limiting | Contact provider, check SPF/DKIM/DMARC records |

## Retry Behavior

Failed emails are automatically retried by Celery:

- **Max retries:** 3 attempts total
- **Retry delay:** ~60 seconds between attempts
- **After 3 failures:** Task stops; use manual retry from Email History modal

You can also manually retry at any time via the Email History modal without waiting for automatic retries.

## Archiving and Compliance

Email delivery logs are kept for compliance and audit:

- All email attempts (successful and failed) are recorded in `EmailLog`
- Timestamps, recipients, subjects, and error messages preserved
- Linked to invoices via foreign key for traceability
- Logs are ordered by most recent first

## Best Practices

**Personalize templates:** Use `{participant_name}` and `{zev_name}` for a personal touch.

**Test with console backend:** During setup, use `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` to verify email content in logs before enabling real SMTP delivery.

**Monitor delivery:** Check Email History regularly for persistent failures.

**Use app-specific passwords:** For Gmail and similar providers, generate an app-specific password instead of using your main account password.

**Keep contact info current:** Ensure participant email addresses are up to date in [Participants](03-participant-management.md).

## Next Steps

- **Send invoices:** [Invoice Management](09-invoice-management.md#sending-invoices)
- **Manage participants:** [Participant Management](03-participant-management.md)
- **ZEV setup:** [ZEV Setup](02-zev-setup.md)
