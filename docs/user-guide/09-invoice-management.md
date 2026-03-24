# Invoice Management

This guide covers generating, reviewing, and managing invoices for participants.

## Invoice Lifecycle

Invoices progress through a controlled workflow:

```
Draft → Approved → Sent → Paid
          ↓
        Cancelled
```

Each state has specific actions and permissions.

## Creating/Generating Invoices

**ZEV Owners** generate invoices in **Invoices**.

### Generate New Invoices

1. Click **Generate Invoices**
2. Select **Billing Period:**
   - Start date (e.g., 2026-01-01)
   - End date (e.g., 2026-01-31)
   - Pre-filled presets: This month, Last month, This quarter, etc.

3. Click **Preview**
   - Shows all participants in period
   - Highlights data quality issues (missing meters, incomplete readings)
   - Shows estimated line items (not finalized yet)

4. Click **Generate**
   - System calculates energy allocation and applies tariffs
   - Creates draft invoices for all participants with readings in period
   - Takes you to invoices list

### Invoice Status After Generation

- **Status:** `Draft` (not yet approved)
- **Can edit:** Yes (change tariffs, correct errors before approval)
- **Can send:** No (must approve first)
- **Can pay:** No

## Reviewing Draft Invoices

Before approval, review each invoice:

1. Go to **Invoices**
2. Filter by status: **Draft**
3. Click on an invoice to view details

### Invoice Details View

Shows:
- **Participant:** Name and email
- **Billing Period:** Start/end dates
- **Line Items:** Each tariff/charge applied
  - Energy reading (kWh)
  - Unit price
  - Total CHF
- **Subtotal** (before VAT)
- **VAT** (if applicable)
- **Total** (CHF)
- **Data Quality:** Warnings if incomplete metering

### Editing a Draft Invoice

If you find an error (wrong tariff, data quality issue), you can:

1. Open draft invoice
2. Click **Edit**
3. Update line item prices (if tariff was corrected)
4. Regenerate allocation (if metering data was re-imported)
5. Click **Save**

> **Careful:** Only edit if you're sure of the correction. Document changes for audit trail.

### Exporting Draft Invoices

Before approval, export for review:
- **CSV** — All line items and totals
- **PDF** — Single invoice preview

Use this to verify calculations or share with finance team.

## Approving Invoices

Once satisfied with draft invoices, approve them:

1. Go to **Invoices**
2. Filter by status: **Draft**
3. Select invoices (or **Select All**)
4. Click **Approve Selected**
5. Confirm in dialog

After approval:
- **Status changes to:** `Approved`
- **Cannot edit** line items (locked)
- **Can send** to participants
- All changes must create a new invoice version

> **Approval is governance:** Approval marks "we reviewed this and it's correct."

## Sending Invoices

Once approved, send to participants:

1. Go to **Invoices**
2. Filter by status: **Approved**
3. Select invoices to send
4. Click **Send**
5. Confirm in dialog

### What Happens on Send

- **Status changes to:** `Sent`
- **Email notification** sent to participant (includes PDF attachment)
- **Timestamp recorded:** When invoice was sent
- **Delivery status** tracked

### Email Template

Participants receive email with:
- **Subject:** From your [email template](02-zev-setup.md#email-templates)
- **Body:** Custom message saying invoice is attached
- **Attachment:** Invoice PDF

You can customize subject/body in **ZEV Settings → Email Templates**.

## Invoice Status Tracking

### Sent Invoices

Once `Sent`, track delivery:

1. Open invoice
2. View **Email History** section:
   - Send timestamp
   - Delivery status (delivered, bounced, etc.)
   - Retry attempts (if sent failed)

### Email Delivery Failures

If **Email Status = Failed**:

**Possible causes:**
- Participant email is invalid/blocked
- Network issue during send
- Email service error

**Recovery options:**
1. Verify participant email is correct (check [Participants](03-participant-management.md))
2. Click **Resend** on the invoice
3. Contact participant with PDF manually if email continues to fail

## Payment Tracking

### Marking as Paid

When participant pays:

1. Open invoice (status `Sent`)
2. Click **Mark as Paid**
3. Optionally enter:
   - **Payment Date** (when received)
   - **Payment Method** (e.g., bank transfer, cash)
4. Click **Confirm**

**Status changes to:** `Paid`

### Tracking Partial Payments

If participant pays in installments:
1. Create one `Paid` invoice for the full invoice (captures it was sent)
2. Add notes with payment schedule
3. Or contact support for installment tracking features

## Cancelling Invoices

If an invoice is wrong and needs to be regenerated:

1. Open invoice (status `Approved` or `Sent`)
2. Click **Cancel**
3. Confirm in dialog

**Result:**
- Status changes to: `Cancelled`
- Invoice remains in history (for audit)
- You can regenerate a corrected invoice

> **When to cancel:** Error in tariff, metering data re-imported, or participant dispute.

## Regenerating Invoices

If metering data changes after invoice is sent:

1. Re-import corrected metering data (see [Metering Import](05-metering-import.md))
2. Go to **Invoices**
3. Filter for invoices needing regeneration
4. Click **Regenerate**
5. Select period and participants
6. Review and re-approve
7. Send updated invoice (system may note "Updated revision")

> **Locking:** Sent/Paid invoices cannot be directly edited—always regenerate/cancel to create corrected version.

## Bulk Invoice Actions

### Approve Multiple Invoices

1. Go to **Invoices**
2. Filter by **Draft**
3. Click checkbox for "Select All" or individual invoices
4. Click **Approve Selected**
5. Confirm

### Send Multiple Invoices

1. Go to **Invoices**
2. Filter by **Approved**
3. Select invoices
4. Click **Send Selected**
5. Confirm

### Export Invoice Report

Export all invoices in a period:

1. Go to **Invoices**
2. Set date range filters
3. Click **Export → CSV** or **Export → PDF**
4. System generates report with all line items and totals

## Invoice PDF Generation

OpenZEV automatically generates professional invoices:

- **Format:** Swiss-compliant (QR bill, ISO 20022 format)
- **Content:**
  - ZEV name and address
  - Participant name and address (from profile)
  - Billing period
  - Detailed line items
  - Subtotal and VAT
  - QR code for payment (if configured)
  - Contact information

**Template:** Can be customized in **Admin → PDF Templates**.

## Troubleshooting

### "Cannot generate invoices" / "No participants with data"

**Causes:**
- No metering data imported for period
- No active participants in period
- Tariffs not configured

**Fix:**
1. Check [Metering Data](06-metering-analysis.md) — is there data for the period?
2. Check [Participants](03-participant-management.md) — are members active?
3. Check [Tariffs](07-tariff-configuration.md) — are prices set?

### Invoice totals look wrong

**Steps to verify:**
1. Check energy allocation manually (see [Billing Explained](08-billing-allocation-explained.md))
2. Check tariff prices (see [Tariff Configuration](07-tariff-configuration.md))
3. Check data quality (see [Metering Analysis](06-metering-analysis.md))

If unsure, [regenerate after fixing data](5-metering-import.md#re-importing-corrections--updates).

### Email not received by participant

**Troubleshooting:**
1. Check participant email in [Participants](03-participant-management.md) — is it correct?
2. Check email status in invoice **Email History**
3. Click **Resend** to retry
4. Review [Email Configuration](10-email-configuration.md)

## Best Practices

**Review before approval:**
- Check data quality scores
- Verify tariffs are correct for period
- Export and spot-check a few invoices

**Batch send:** Send all invoices at once to avoid duplicate sends

**Archive:** Export invoices monthly for backup

**Privacy:** Remember invoices contain sensitive data—secure PDFs and archive appropriately

## Next Steps

- **Configure email:** [Email Configuration](10-email-configuration.md)
- **Track payments:** Payment methods depend on your ZEV setup
- **Reports:** Review invoices by period and participant

---

**See also:** [Invoice Data Quality Issues](06-metering-analysis.md#billing-impact-of-data-quality-issues)
