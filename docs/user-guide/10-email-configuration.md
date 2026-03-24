# Email Configuration

This guide covers setting up and managing email notifications for invoices.

## Email Overview

OpenZEV sends emails asynchronously for reliable delivery:

- **Invoice notifications:** When invoices are sent to participants
- **Delivery tracking:** System logs all sends and failures
- **Retry behavior:** Failed sends are retried automatically
- **Customization:** Email subject and body can be tailored per ZEV

## Email Templates

**ZEV Owners** customize email templates in **ZEV Settings → Email Templates**.

### Template Fields

| Field | Purpose | Example |
| --- | --- | --- |
| **Subject** | Email subject line | Invoice for {zev_name} - {invoice_period} |
| **Body** | Email message | Dear {participant_name}, your invoice is attached. |
| **Signature** | Footer/sign-off | Best regards, ZEV Operations Team |

### Template Variables

Use placeholders to personalize emails:

| Placeholder | Replaced With |
| --- | --- |
| `{participant_name}` | Recipient first and last name |
| `{participant_email}` | Recipient email address |
| `{zev_name}` | ZEV community name |
| `{invoice_period}` | Billing period (e.g., "January 2026") |
| `{invoice_total}` | Invoice total in CHF |
| `{invoice_link}` | Link to view invoice in portal (participant self-service) |

### Example Template

**Subject:**
```
Invoice for {zev_name} — {invoice_period}
```

**Body:**
```
Dear {participant_name},

Your invoice for {invoice_period} is attached.

Invoice Total: CHF {invoice_total}

You can also view your invoice anytime in your participant portal:
{invoice_link}

If you have questions, please contact us.

Best regards,
ZEV Operations Team
Contact: contact@zev.local
```

## Sending Invoices

When you [send approved invoices](09-invoice-management.md#sending-invoices):

1. OpenZEV generates PDF
2. Email is created using your template
3. Email is queued for delivery (via Celery worker)
4. Invoice status changes to `Sent`

### Delivery Process

Behind the scenes:

1. **Email task queued** (status: `Pending`)
2. **Background worker processes** task
3. **Email sent** to participant email address (status: `Sent`)
4. **Tracker records** delivery timestamp and status

If email fails (bounced, rejected):
- **Status: `Failed`**
- **Retry scheduled** (default: up to 3 retries)
- **You are notified** to resend manually

## Email Delivery Status

Each invoice shows **Email Status**:

| Status | Meaning | Action |
| --- | --- | --- |
| **Pending** | Not yet sent | Wait a few seconds, refresh page |
| **Sent** | Delivered to email service | Complete |
| **Failed** | Delivery error | Resend or verify email address |
| **Bounced** | Recipient rejected | Check participant email in [Participants](03-participant-management.md) |

### Email History

Click **Email History** on an invoice to see:

```
Email History

Sent: 2026-02-15 14:35 UTC
To: alice@example.local
Status: Sent
Subject: Invoice for Solar Cooperative — January 2026
```

If multiple sends:

```
Attempt 1: 2026-02-15 14:35 — Failed (network timeout)
Attempt 2: 2026-02-15 15:05 — Failed (mailbox full)
Attempt 3: 2026-02-15 15:35 — Sent ✓
```

## Handling Email Failures

### Email Bounced or Not Received

**Step 1: Verify recipient email**
1. Go to [Participants](03-participant-management.md)
2. Find participant
3. Check email address is correct
4. Correct if needed

**Step 2: Resend invoice**
1. Open invoice
2. Click **Resend**
3. System retries delivery
4. Check email history after a few seconds

**Step 3: Manual delivery (if retries fail)**
1. Export invoice as PDF from OpenZEV
2. Send to participant manually (email or download link)
3. Note in invoice comments: "Manually delivered on [date]"

### Mailbox Issues

If many participants have email failures:

- Check with your email provider (office 365, Gmail, etc.)
- Verify SMTP settings in Admin configuration
- Ensure no firewall/network blocks outgoing mail

### Disable Email Notifications (for testing)

To test invoice generation without sending emails:

1. Go to **Admin → Email Settings**
2. Toggle **Send Invoice Emails:** OFF
3. Generate and send invoices—they'll be marked sent without sending emails
4. Turn back ON before production use

## Archiving and Compliance

Email delivery logs are kept for compliance and audit:

- All email sends (successful and failed) are recorded
- Timestamps and delivery status preserved
- Linked to invoice for traceability

**Data Retention:** Follow your local data protection laws for email log retention (typically 90 days—1 year).

## Retry Behavior

Failed emails are automatically retried:

- **Retry 1:** ~30 minutes after failure
- **Retry 2:** ~2 hours later
- **Retry 3:** ~24 hours later
- **After 3 retries:** Marked as `Failed`, requires manual action

You can manually resend anytime without waiting for automatic retries.

## Advanced: Direct SMTP Configuration

If you use a custom email provider:

1. Go to **Admin → Email Settings**
2. Configure SMTP:
   - **SMTP Host:** (e.g., `smtp.gmail.com`)
   - **SMTP Port:** (e.g., `587` for TLS)
   - **Username:** Your email account
   - **Password:** Account password or app-specific token

3. Click **Test SMTP Connection**
4. Save

OpenZEV will use your SMTP for all invoice emails.

## Troubleshooting

### "Email Status: Pending" (stuck for hours)

**Cause:** Background worker not running

**Fix:**
1. Check that Celery worker is running: `docker compose logs worker`
2. Restart if needed: `docker compose restart worker`

### "Cannot send invoice email" (error message)

**Causes:**
- Participant email invalid or empty
- SMTP not configured
- Network/firewall blocks outgoing mail

**Fix:**
1. Verify participant email ([Participants](03-participant-management.md))
2. Check SMTP settings ([Admin Email Settings](#advanced-direct-smtp-configuration))
3. Test network connection to mail server

### Many failed sends on specific domain

**Cause:** Email provider blocking/rate-limiting

**Solution:**
- Contact email provider to whitelist your SMTP server
- Ask participants to check spam folder and add sender to contacts
- Consider domain reputation (SPF, DKIM, DMARC records)

## Best Practices

**Personalize templates:** Use {participant_name} for human touch

**Test templates:** Send a test email before production use

**Monitor delivery:** Check **Email History** regularly for failures

**Archive invoices:** Keep backup of sent invoices outside email system

**Update contact info:** Keep ZEV contact information current in signature

## Next Steps

- **Send invoices:** [Invoice Management](09-invoice-management.md#sending-invoices)
- **Track payments:** Payment notification workflow depends on your ZEV process
- **Admin setup:** [ZEV Setup](02-zev-setup.md)
