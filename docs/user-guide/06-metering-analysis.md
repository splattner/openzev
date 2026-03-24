# Metering Analysis

This guide covers analyzing metering data through charts and data quality views.

## Data Visualization

OpenZEV provides real-time charts of consumption and production.

![Metering data charts](screenshots/05-metering-data.png)

### Accessing Metering Charts

Navigate to **Metering Data** to see charts.

### Filtering Your View

Use the selectors above the chart:

| Selector | Purpose | Default |
| --- | --- | --- |
| **Metering Point** | Single meter (optional; all if blank) | All points |
| **Date Range** | Period to display | Last 7 days |
| **Resolution** | Aggregation level (`hourly`, `daily`, `monthly`) | Hourly |

#### Date Range Presets

Quick shortcuts:
- **Last 7 days** — Most recent week
- **Last 30 days** — Most recent month
- **This month** — Calendar month to date
- **This year** — Calendar year to date
- **Custom** — Pick start/end dates

#### Resolution Levels

- **Hourly:** Each bar = 1 hour of data (detailed view)
- **Daily:** Each bar = 24 hours (weekly view, less detail)
- **Monthly:** Each bar = 1 month (yearly view, highest level)

Choose hourly for troubleshooting; daily/monthly for trend analysis.

### Chart Display

The chart shows:

- **X-axis:** Time periods
- **Y-axis:** Energy (kWh)
- **Stacked bars:**
  - 🔵 **Blue:** Consumption (IN)
  - 🟡 **Yellow:** Production (OUT)
- **Tooltips:** Hover to see exact values

### Export Charts

Charts can be exported as:
- **PNG image** — For reports or presentations
- **CSV data** — Underlying readings for analysis
- **PDF** — Multi-page chart booklet

## Data Quality View

Use **Data Quality** tab to assess completeness and health of metering data.

### Summary Cards

At top, four cards summarize the selected period:

| Card | Meaning | Ideal |
| --- | --- | --- |
| 🟢 Complete | Metering points with full coverage for period | High |
| 🟡 Partial | Points with some gaps or missing readings | Medium |
| 🔴 Missing | Points with no readings in period | Zero |

**Coverage is strict daily completeness**: A metering point is marked complete only if it has readings for every day in the date range.

### Status Table

Below summary cards, a table shows per-metering-point details:

| Column | Shows |
| --- | --- |
| **Metering Point ID** | Equipment identifier |
| **Participant** | Owner name |
| **Coverage %** | Percent of expected readings received |
| **Status** | 🟢 Complete, 🟡 Partial, 🔴 Missing |
| **Gaps/Issues** | List of date ranges with missing data |

### How Gaps Are Detected

OpenZEV flags a gap when:
- Expected reading is missing (e.g., hourly meter, but hour has no reading)
- Metering point has an **active assignment window** for that date
- Metering point was assigned to an active participant

Example:

| Date | Status | Reason |
| --- | --- | --- |
| Jan 1-5 | ✓ Complete | All hourly readings present |
| Jan 6-6 | ⚠ Partial | 3 hours missing (data quality issue?) |
| Jan 7-31 | ✓ Complete | All hours present |

**Investigation needed:** Why were 3 hours missing on Jan 6?

## Data Quality Troubleshooting

### High percentage of "Missing" meters

**Causes:**
- Metering data not yet imported
- Assignment validity period doesn't overlap billing period
- Participant marked as inactive

**Fixes:**
1. Check **Metering Points** — is meter defined and active?
2. Check [import status](05-metering-import.md) — were readings imported?
3. Review participant [validity dates](03-participant-management.md) — is member active?

### Partial coverage with gaps

**Causes:**
- Meter malfunction or power outage
- File upload incomplete
- Timestamp mismatch during import (timezone issue)

**Fixes:**
1. Ask participants to verify meter status
2. Re-import data with correct timezone setting
3. Review import protocol for parse errors
4. Fill gaps manually if readings are recoverable

### Sudden spikes or drops

**Possible issues:**
- Meter miscalibration
- Demand-side event (equipment switched on/off)
- Data entry error
- Timezone interpretation error

**Diagnosis:**
1. Check if spike is in consumption (IN) or production (OUT)
2. Ask participant if they changed usage (e.g., heating, EV charging)
3. Check if meter was replaced near spike date
4. Review raw readings in chart tooltip (may help spot outliers)

## Billing Impact of Data Quality Issues

OpenZEV generates invoices even if some data is incomplete. The system:

1. ✓ Bills all complete periods normally
2. ⚠ Warns if any metering point is incomplete
3. 📄 Includes note in invoice about missing data
4. 📋 Stores quality report with invoice

Participants should be informed of:
- Which meters had incomplete data
- How billing was handled (estimated vs. actual)
- Next steps for correction

## Next Steps

- **Fix import issues:** [Metering Data Import](05-metering-import.md)
- **Set metering point details:** [Metering Points](04-metering-points.md)
- **Configure tariffs:** [Tariff Configuration](07-tariff-configuration.md)
- **Generate invoices:** [Invoice Management](09-invoice-management.md)
