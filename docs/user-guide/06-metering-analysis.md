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

### Raw Readings Table

Below or alongside the chart, a **Raw Metering Data** table shows the daily
summary, expandable down to day-level readings with their timestamps (on the UTC
timeline) and values. Use it to spot individual anomalous readings that the
aggregated chart may hide.

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
- Timestamp mismatch during import (wrong format interpretation)

**Fixes:**
1. Ask participants to verify meter status
2. Review the import protocol for parse errors
3. Re-import the affected readings with the correct timestamp format

### Sudden spikes or drops

OpenZEV does not currently run automated anomaly detection on the raw readings.
To investigate a suspected spike or drop, review the raw readings on the chart
and confirm the value with the metering source.

## Billing Impact of Data Quality Issues

OpenZEV generates invoices even if some metering data is incomplete. The period
overview reports data quality with a severity indicator (green / yellow / red)
and coverage percentage, so you can see which metering points were incomplete
for the period.

Participants affected by incomplete data should be informed which meters were
affected and how billing was handled for those readings.

## Next Steps

- **Fix import issues:** [Metering Data Import](05-metering-import.md)
- **Set metering point details:** [Metering Points](04-metering-points.md)
- **Configure tariffs:** [Tariff Configuration](07-tariff-configuration.md)
- **Generate invoices:** [Invoice Management](09-invoice-management.md)
