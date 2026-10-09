# Your Own Energy Data

If your PV system sits **behind** your grid connection meter, the meter only
sees the surplus you feed in and the power you still draw from the grid (see
[Generation behind the meter](04-metering-points.md#generation-behind-the-meter)).
What you produce and use yourself never reaches it, so OpenZEV cannot tell how
self-sufficient you really are.

**Energy data** closes that gap. You connect the system that does measure it —
Solar Manager today, or any system that can send or export a file — and OpenZEV
adds your real production, consumption, self-consumption and self-sufficiency to
the statistics.

!!! note "Statistics only, never billing"
    This data is **never** used for invoices. Billing keeps using the grid
    operator's meter data alone, exactly as before. A wrong or missing value in
    your own system can at worst make a statistic wrong or empty; it cannot change
    an amount.

The feature is switched on by an administrator (**Platform → Settings →
Functions → Supplementary energy data**). Until then none of what follows is
visible.

## Who can connect what

Only the **participant who personally holds** the metering point can connect a
source for it. It is their account and their household, so a ZEV manager cannot
connect it for them, cannot see the key and cannot change it. The metering point
must be marked **Generation behind the meter**, and you must hold it yourself
(not through a shared community allocation).

| | You (holder) | ZEV manager | ZEV viewer | Other participants |
|---|---|---|---|---|
| Connect, test, sync, replace the key, import | yes | no | no | no |
| See the status and your figures | yes | yes | yes (read-only) | no |
| Switch off, disconnect, delete data, remove | yes | yes | no | no |

When you no longer hold the metering point (the assignment ends), the connection
is switched off by itself, the key is deleted, and nothing new is collected. The
data already collected is kept until you or a manager deletes it.

## Connect Solar Manager

![Account Energy data tab](screenshots/24-energy-data-account.png)

1. Create an **API key** in your Solar Manager account.
2. In OpenZEV open **Account → Energy data**. The tab appears when you hold a
   metering point with generation behind it.
3. Choose **Connect** next to the metering point.
4. Pick **Solar Manager**, enter your **Solar Manager ID** (3 to 24 letters or
   digits) and the **API key**, and read what you agree to.
5. Tick the consent box and choose **Connect**.

OpenZEV checks the key with Solar Manager **before** anything is saved, so a
wrong key never leaves a half-connected source behind. The key is stored
encrypted, only used to fetch your data, and never shown again. The first data
arrives within a few minutes; after that OpenZEV fetches new data every hour and
re-reads the last two days to pick up late corrections.

Solar Manager replaces your key with a fresh one every time it is used, and
OpenZEV keeps the fresh one. If the connection ever shows **Reconnect needed**,
the key no longer works (for example because you revoked it): choose
**Reconnect** and enter a new key.

### What is stored

Four values per quarter hour: **consumption**, **production**, **grid import**
and **grid export**, in kWh. Nothing else from your Solar Manager account is
read. Only the time you held the metering point is stored.

## Send the data yourself (push or file)

If you do not use Solar Manager — for instance with Home Assistant, n8n or a
script — choose **Push / file** when you connect. You get a **push token**
shown **once**; copy it right away. OpenZEV stores only a hash, so if you lose
it you issue a new one (**New push token**), which stops the old one at once.

Send readings with an HTTP `POST`:

```bash
curl -X POST "https://your-openzev.example.com/api/v1/metering/supplementary/ingest/" \
  -H "Authorization: Bearer ozs_abcd1234_yourtoken" \
  -H "Content-Type: application/json" \
  -d '{"readings": [
        {"timestamp": "2026-07-01T10:00:00+02:00",
         "consumption_kwh": 0.42, "production_kwh": 1.31,
         "import_kwh": 0.05, "export_kwh": 0.94}
      ]}'
```

The rules, so that nothing is silently wrong:

- **One reading per quarter hour**, with the timestamp of the interval's
  **start** (`10:00` means 10:00 to 10:15) on a quarter-hour boundary
  (`:00`, `:15`, `:30`, `:45`) and a UTC offset.
- **kWh used in that quarter hour**, not a running total and not watts. If your
  system reports a meter reading that only ever grows, send the difference.
- No negative values, no future timestamps, at most 2000 readings per request
  and about 120 requests per hour.
- Sending the same timestamp again replaces the earlier value, so a retry is
  harmless.
- A bad reading is rejected on its own, with its position and the reason; the
  good ones in the same request are still stored.

### Home Assistant example

With a `utility_meter` per value (cycle `quarter-hourly`), an automation can send
the previous quarter hour shortly after each boundary. The entity names below are
placeholders for your own sensors:

```yaml
rest_command:
  openzev_push:
    url: "https://your-openzev.example.com/api/v1/metering/supplementary/ingest/"
    method: POST
    headers:
      Authorization: "Bearer ozs_abcd1234_yourtoken"
      Content-Type: "application/json"
    payload: >
      {"readings": [{
        "timestamp": "{{ timestamp }}",
        "consumption_kwh": {{ consumption }}, "production_kwh": {{ production }},
        "import_kwh": {{ import_kwh }}, "export_kwh": {{ export }}
      }]}

automation:
  - alias: Send energy data to OpenZEV
    trigger:
      - platform: time_pattern
        minutes: "/15"
        seconds: 30
    action:
      - service: rest_command.openzev_push
        data:
          timestamp: >
            {{ (now().replace(second=0, microsecond=0, minute=(now().minute // 15) * 15) - timedelta(minutes=15)).isoformat() }}
          consumption: "{{ state_attr('sensor.house_consumption_quarter_hour', 'last_period') | float(0) }}"
          production: "{{ state_attr('sensor.pv_production_quarter_hour', 'last_period') | float(0) }}"
          import_kwh: "{{ state_attr('sensor.grid_import_quarter_hour', 'last_period') | float(0) }}"
          export: "{{ state_attr('sensor.grid_export_quarter_hour', 'last_period') | float(0) }}"
```

### Upload a CSV file

For a one-off import or to fill a gap, choose **Import CSV** on the source. The
columns are:

```text
timestamp,consumption_kwh,production_kwh,import_kwh,export_kwh
2026-07-01T10:00:00+02:00,0.42,1.31,0.05,0.94
```

Semicolons and decimal commas (as in a Swiss Excel export) are accepted. Choose
**Check file** first: it reports the problems row by row and imports nothing.
**Import** stores the file only if **every** row is valid.

## What you see

### Your dashboard

![Participant dashboard with own-system figures](screenshots/24-energy-data-dashboard.png)

With a connected source, your dashboard shows a card **Your own system** with
production, consumption, self-consumption, grid import and export, your
**self-sufficiency** and **self-consumption** rates, and a chart. It always says
the figures are **reported by your own system**, not read from the meter, and
which period they cover.

- **Self-sufficiency** — the share of what you consume that did not come from the
  grid: one minus grid import divided by consumption.
- **Self-consumption** — the share of what you produce that you used directly.

Both are computed from your own system's numbers alone, so numerator and
denominator are measured the same way. The meter is only used to *check* them.

The **24-hour consumption profile** below the cards adds a dashed line,
**Consumption (own system)**, with your own system's average consumption per hour
of the day, next to the bars measured at the meter. A note under the chart says the
line is reported by your own system. Like the rates, it only appears when there is
enough data in the period.

The **surplus metering** badge explains where the figures come from: without a
connected source it says no rate can be shown, with one it says the meter only
measures surplus and grid draw, and consumption, production and rate come from
your own system.

### Gaps are shown as dashes, not as low rates

A rate is only shown when at least **95 %** of the quarter hours in the period
are present. With less, the rate is **—** and a short reason says so
("not enough data in this period"). A missing hour never turns into a low
self-sufficiency. The energy sums are still shown.

### Owners, reports and statements

- The ZEV manager's **Energy balance** shows the same rate in the participant
  table, marked with an info icon. The **Consumption** and **Production/Export**
  columns keep the meter value and add the own system's figure under it
  (**Own system: x kWh**, also marked with an info icon, and only with enough data).
  Selecting a participant shows the full card and draws their own-system line in the
  24-hour profile. A manager who is also a participant with a connected source sees their own
  **Your own system** card there while nobody, or they themselves, are selected
  (not while another participant is); their own row is marked **You**. Without a source, the same place offers to connect one.
  Selecting a row in the table again clears the selection.
- The **annual report** shows it per participant.
- The **annual statement** PDF shows your self-sufficiency for every month with
  enough data, **—** for the others, and a note saying the figures come from your
  own system.
- The [AI assistant tools](19-ai-assistants.md) report it as
  `gross_self_sufficiency_pct` and `gross_self_consumption_pct`.

## Does it match the meter?

![Source status with the meter comparison](screenshots/24-energy-data-status.png)

After every sync OpenZEV compares your export and import with the grid
operator's meter for the newest days present in both. This is only a check — the
meter always wins and nothing is corrected. The result shows on the source:

- **Matches the meter** — the difference is below 10 %.
- **Differs from the meter** — more than that. A typical cause is the wrong unit
  (Wh sent as kWh) in a push client.
- **The timestamps look shifted** — your values fit the meter better one or two
  quarter hours earlier or later, which usually means the interval start and end
  were mixed up.
- **Not enough to compare** — there are fewer than two days present in both, for
  example because the meter data has not been imported yet.

## Disconnect, delete, remove

| Action | Stops new data | Deletes data | Keeps the connection |
|---|---|---|---|
| **Disconnect** | yes | no (and it is still used for statistics) | no (key and token are deleted) |
| **Delete data** | no | yes, all readings | yes |
| **Remove source** | yes | yes, all readings | no |

A ZEV manager sees the same buttons for a participant's source, except for the
ones that touch the key. Deleting a participant or a metering point deletes their
sources and readings with them.

## Troubleshooting

**The Energy data tab is missing.** The feature is off, or you do not personally
hold a metering point marked *Generation behind the meter*. Ask your ZEV manager.

**"Not accepted" when connecting.** The key or the Solar Manager ID is wrong. The
ID is the one of your installation, not your login name.

**The server says the key cannot be stored.** The platform administrator has not
set up the encryption key for integrations (`INTEGRATION_ENCRYPTION_KEYS`). Push
and file import still work without it.

**The rate stays a dash.** Less than 95 % of the period is covered. Look at
*Data covers* on the source, and use **Sync now** or **Import CSV** to fill a gap.

**Sync now says to wait.** One manual sync every five minutes is allowed; the
hourly one runs anyway.

## Next Steps

- [Metering points](04-metering-points.md) — mark generation behind the meter
- [Metering analysis](06-metering-analysis.md) — the charts and the data quality view
- [Roles and permissions](11-roles-and-permissions.md)
