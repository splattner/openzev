# ZEV Setup and Configuration

This guide covers creating and configuring a Zev energy community in OpenZEV.

## What is a ZEV?

A ZEV (or vZEV) is a virtual energy community:
- Members (participants) share local energy production
- Energy is allocated fairly using a timestamp-level allocation model
- Billing is transparent and community-auditable

OpenZEV supports operating one or many ZEVs, each with independent:
- Participants
- Metering points
- Tariffs
- Invoicing schedules

## Creating a ZEV

Only **admins** can create new ZEVs.

1. Go to **Admin → ZEV Management**
2. Click **Create New ZEV**
3. Enter:
   - **ZEV Name** — Community identifier (e.g., "Solar Cooperative 2026")
   - **Description** (optional)
4. Click **Create**

Once created, you can assign **ZEV owners** who will manage day-to-day operations.

## ZEV Settings

**ZEV owners** configure their community in **ZEV Settings**.

### Basic Settings

| Setting | Purpose | Default |
| --- | --- | --- |
| **ZEV Name** | Community identifier | Required |
| **Description** | Long-form community info | Optional |
| **Billing Interval** | Invoice frequency | Monthly |
| **VAT Number** | Swiss business ID (UID) | Optional |

### Billing Interval

Choose how often invoices are generated:

- **Monthly** — One invoice per month
- **Quarterly** — One invoice per 3 months
- **Semi-Annual** — One invoice every 6 months
- **Annual** — One invoice per year

> **Tip:** Monthly is most common for community billing; annual works for smaller communities or cooperatives with annual settlements.

### VAT Configuration

If your ZEV is VAT-registered:

1. Enter your **VAT Number** (UID format for Switzerland)
2. Open **Admin → VAT Settings** to configure VAT rates
3. VAT rates are validity-window based — admins can set rates for specific periods
4. The system automatically applies the correct rate based on invoice period end date

If no VAT rate is active for an invoice period, VAT defaults to **0%**.

## Regional Settings

**Admins** configure regional defaults in **Admin → Regional Settings**:

- **Default Timezone** — Used for timestamp interpretation in metering imports
- **Date Format** — Display format for invoices and exports
- **Currency** — Default billing currency (currently CHF)

> **Note:** Timezone alignment is critical for accurate billing. See [Metering Data Import](05-metering-import.md) for details.

## Template Configuration

OpenZEV supports customizing invoice and email appearance.

### Invoice PDF Template

**Admins** can manage PDF invoice templates in **Admin → PDF Templates**:

- Choose or upload custom invoice layouts
- Preview generated PDFs before live use
- Template changes apply to newly generated invoices only

### Email Templates

**ZEV Owners** can customize invoice email templates in **ZEV Settings → Email Templates**:

- **Subject line** — Invoice notification subject
- **Email body** — Message sent with invoice attachment
- **Signature** — Community contact or footer

Templates support variable placeholders:
- `{participant_name}` — Recipient name
- `{invoice_period}` — Billing period
- `{invoice_total}` — Total CHF amount
- `{zev_name}` — Community name

## Access Control

ZEV access is controlled via **role assignments**:

- **ZEV Owner:** Full operational management of the ZEV
- **Participant:** Read-only access to own data

Assign roles in **Admin → Accounts** (admin-only).

Participants automatically see only their own metering data and invoices regardless of role settings (ZEV-scoped access).

## Data Ownership and Privacy

- All metering data is scoped to the ZEV — participants cannot see other participants' readings
- Invoices are private to their recipient and ZEV owners
- Admins have global read access for monitoring and compliance

## Multi-ZEV Operations

If running multiple ZEVs:

1. **Global navigation:** Use the ZEV selector in the top navigation bar
2. **Each ZEV is independent:** Tariffs, participants, and invoices are isolated
3. **Owners can manage one or more ZEVs:** Request admin assignment if needed

## Next Steps

- **Add participants:** [Managing Participants](03-participant-management.md)
- **Configure metering points:** [Metering Points](04-metering-points.md)
- **Import readings:** [Metering Data Import](05-metering-import.md)
- **Set up tariffs:** [Tariff Configuration](07-tariff-configuration.md)
