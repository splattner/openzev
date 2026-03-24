# Metering Data Import

This guide covers importing metering (consumption and production) readings into OpenZEV.

## Import Overview

OpenZEV supports three import pathways:

1. **CSV/Excel Files** — Column-mapped spreadsheets
2. **SDAT-CH Format** — Swiss standard metering data exchange
3. **Manual Entry** — For small datasets or testing

All imports use a **preview-first validation** approach:
1. Upload file
2. Review mapping and preview (no data written yet)
3. Confirm import
4. System writes and shows protocol

![Imports page](screenshots/09-imports.png)

## CSV/Excel Import

### File Format

Prepare your data as CSV or Excel with columns:

| Column | Required | Format | Example |
| --- | --- | --- | --- |
| `metering_point_id` | ✓ | String (MSID/ID) | `CH123456789012345678` |
| `timestamp` | ✓ | ISO 8601 or configurable | `2026-01-15 14:00:00` |
| `value` | ✓ | Decimal (kWh) | `1.250` |
| `unit` | ✗ | `kWh` or `MWh` | `kWh` |

### Step-by-Step Import

1. **Go to Metering Import**
   - Navigate: **Metering Data → Import** (or **Imports** on home page)

2. **Upload File**
   - Click **Choose File**
   - Select your CSV or Excel file
   - Click **Upload**

3. **Configure Mapping**
   - Assign columns in your file to OpenZEV fields:
     - `Metering Point ID` → which column?
     - `Timestamp` → which column?
     - `Value` → which column?
   - Set **Timestamp Format** (e.g., `YYYY-MM-DD HH:00:00`)
   - Select **Timezone** (critical for accuracy!)
   - Set **Unit** (default: `kWh`)

4. **Preview**
   - View first 10-20 rows parsed correctly
   - Check **Metering point exists** and **Participant is active**
   - Verify **Timestamp parsing** looks correct
   - Review **Warnings** (inactive participants, missing meters, etc.)

5. **Review Import Options**
   - **Merge with existing data:** Append to existing readings ✓ (default, safe)
   - **Replace data in range:** Overwrite readings in a date range (careful!)
   - **Continue on errors:** Skip invalid rows, keep valid ones

6. **Confirm Import**
   - Click **Import**
   - System writes data and shows **Import Protocol**

### Import Protocol

After import completes, you'll see a report:

```
Import Protocol — 2026-03-24 14:35

File: solar_2026-q1.csv
Rows processed: 8,760
Rows successful: 8,755
Rows failed: 5
Warnings: 12

Details:
✓ CH12345: 2,920 readings imported
✓ CH12346: 2,920 readings imported
✓ CH12347: 2,915 readings (5 row parse errors)
⚠ CH12348: Meter is not active in period 2026-01-01 to 2026-03-31

Failed rows:
- Row 142: Timestamp format mismatch
- Row 1,205: Value not numeric (null?)
- ...
```

**Save the protocol** for audit trail. You can re-run imports to fix issues without losing previous data (use merge mode).

## SDAT-CH Format

OpenZEV supports the Swiss **SDAT-CH** metering data standard (used by utility providers).

1. Go to **Metering Import → SDAT-CH**
2. Upload your SDAT-CH file
3. OpenZEV automatically parses:
   - Metering point IDs
   - Timestamps
   - Values (kWh)
   - Quality flags
4. Preview and confirm (same as CSV workflow above)

> **Note:** SDAT-CH metadata (meter type, interval) is extracted; timestamp resolution is auto-detected.

## Timezone Handling

**Timezone is critical** for accurate billing.

When importing:
- Specify **Timezone** of the timestamp column (e.g., `Europe/Zurich`)
- OpenZEV stores all readings in UTC internally
- Invoice generation uses the ZEV's [configured timezone](02-zev-setup.md#regional-settings)

### Example

If your CSV timestamps are in Swiss time (`Europe/Zurich`):
- Raw data: `2026-01-15 22:00:00` (CET = UTC+1)
- Stored as: `2026-01-15 21:00:00` (UTC)
- Invoice timezone: `Europe/Zurich` → displayed as `2026-01-15 22:00:00`

Mixing timezones can cause off-by-one-hour billing errors!

## Common Import Scenarios

### Scenario 1: Hourly Solar + Consumption

**File:** `readings_2026-01.csv`

```
metering_point_id,timestamp,value
CH12345-solar,2026-01-15 00:00:00,0.000
CH12345-solar,2026-01-15 01:00:00,0.000
CH12345-solar,2026-01-15 12:00:00,2.150
CH12346-load,2026-01-15 00:00:00,0.750
CH12346-load,2026-01-15 01:00:00,0.630
```

1. Upload file
2. Map columns (metering_point_id, timestamp, value)
3. Set timezone to `Europe/Zurich`
4. Preview: Should show 2 meters, ~720 rows per meter
5. Import

### Scenario 2: Utility SDAT-CH Export

Utility provides file: `20260315_metering.sdat`

1. Upload to **SDAT-CH Import**
2. OpenZEV auto-parses metadata
3. Preview shows all metering points detected
4. Confirm import

## Handling Import Errors

### "Metering point not found"

The CSV references a meter ID that doesn't exist. Solutions:
1. Check metering point ID spelling in CSV
2. Create missing metering points in **Metering Points**
3. Re-run import

### "Timestamp outside validity period"

Reading timestamp is outside the active assignment window (`valid_from`/`valid_to`) for the participant-meter relation.

Solutions:
1. Check assignment validity period: [Metering Points](04-metering-points.md#assignment-validity-periods)
2. Adjust assignment `Valid From/To` if the participant mapping started earlier/later
3. Re-run import

### "Value parse error"

Reading value is not numeric (e.g., "N/A" or blank).

Solutions:
1. Clean CSV: Replace non-numeric empty/error values with `0.000`
2. Use **Continue on Errors** during import (skips bad rows)
3. Re-run import

### "Participant is no longer active"

⚠ Metering point is assigned to an inactive participant.

Impact: Invoice won't include this meter unless participant is re-activated.

Solution: Update [Participant Validity](03-participant-management.md#updating-validity-periods)

## Re-importing (Corrections & Updates)

If you find errors in imported data:

1. Prepare corrected CSV
2. Go to **Metering Import**
3. Choose **Merge mode** (default, safe) or **Replace range** (careful!)
   - **Merge:** New readings are added; existing unchanged
   - **Replace range:** Delete all readings in date range, then add new ones

4. Upload and preview
5. Confirm

> **Best practice:** Use **Replace range** only if you know the exact period to fix. Otherwise merge new data and manually delete duplicates.

## Data Quality Checks

After import, review **Metering Data → Data Quality** to see:
- Coverage per metering point
- Missing readings
- Anomalies (sudden spikes/drops)
- Gaps vs. assignment/participant validity windows

See [Metering Analysis](06-metering-analysis.md) for details.

## Next Steps

- **Check data quality:** [Metering Analysis](06-metering-analysis.md)
- **Set up tariffs:** [Tariff Configuration](07-tariff-configuration.md)
- **Generate invoices:** [Invoice Management](09-invoice-management.md)
