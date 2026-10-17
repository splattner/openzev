# Analytics Data and Grafana

OpenZEV can hand your metering data to tools that draw charts better than a fixed
dashboard can — Grafana, a spreadsheet, a script. It does so through one read-only
endpoint, the **analytics series**, that returns the same numbers your invoices and
dashboards use, split into local energy, grid energy and feed-in.

The endpoint only ever returns what you may already see in OpenZEV. Nobody gets
access to the database, which is also why this is the only supported way to connect
Grafana (see [Grafana on the database](#grafana-on-the-database-not-supported)).

## What the data looks like

One row per time bucket, per metering point or participant, per direction:

| Column | Meaning |
| --- | --- |
| `bucket_start` | Start of the bucket, Swiss time with offset (`2026-06-10T12:00:00+02:00`) |
| `metering_point` | Meter id (only when grouped by metering point) |
| `participant`, `participant_id` | Who the energy is attributed to |
| `direction` | `in` is consumption, `out` is production |
| `total_kwh` | Energy in the bucket |
| `local_kwh` | `in`: covered by the community's own production. `out`: used inside the community |
| `grid_kwh` | `in` only: drawn from the grid |
| `feed_in_kwh` | `out` only: exported to the grid |
| `source` | `metering` |

Days, weeks, months and years follow the Swiss calendar, so the days the clocks
change are 23 or 25 hours long. A meter shared by the whole community (a common-area
meter allocated by weight) is split across the participants by weight, exactly as on
the invoices.

## Who sees what

- **Administrators, managers and viewers** of a ZEV see every row of that ZEV.
- **Participants** see only their own rows. A share of a meter that belongs to a
  neighbour is included in their consumption, but the meter is not named.
- **ZEV-wide totals** (`group_by=zev`) are shown to participants only when at least
  five participants shared the ZEV on every day of the range. In a smaller community
  "the ZEV total minus mine" would be somebody else's load profile. Managers always
  see the totals. An administrator can change the number under **Platform → Settings →
  Security → Analytics privacy** (never below 3); left empty it follows the platform
  default, which is 5 unless `ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE` says otherwise.

Data from your own system behind the meter (see [Your Own Energy Data](20-energy-data.md))
is not part of the dataset.

## Limits

Numbers are computed when you ask, so a request is bounded:

| Granularity | Longest range |
| --- | --- |
| 15 minutes | 14 days |
| hour | 100 days |
| day | 400 days |
| week, month, year | 10 years |

A request is also refused when the ZEV holds more than 300,000 readings in the range
(about four months for a ZEV with 25 meters), or would return more than 200,000 rows.
The answer says what to narrow. Month and year charts over long periods of a large ZEV
may therefore need a shorter range until a precomputed table exists.

## Reading the data with your account or an API key

Use your normal sign-in or an [API key](16-api-keys.md) (a read-only one is enough):

```bash
curl -H "Authorization: Api-Key ozv_3f9a1c04b7e2_kR8vN2pQ..." \
  "https://your-openzev.example.com/api/v1/analytics/series/?zev=<zev-id>&from=2026-01-01&to=2026-12-31&granularity=month&group_by=zev&direction=in"
```

Add `&format=csv` for a CSV file, for example to open in a spreadsheet.

| Parameter | Values |
| --- | --- |
| `zev` | the ZEV id (see `GET /api/v1/zev/zevs/`) |
| `from`, `to` | first and last day, `YYYY-MM-DD` |
| `granularity` | `15min`, `hour`, `day` (default), `week`, `month`, `year` |
| `group_by` | `metering_point` (default), `participant`, `zev` |
| `direction` | `in` or `out`; both when omitted |
| `participant`, `metering_point` | only these rows (ids) |

## Analytics tokens

An API key carries your whole account. For a tool that only needs to draw charts,
create an **analytics token** instead. It can read this one endpoint for one ZEV (or
one participant of it) and nothing else, expires, and can be revoked on its own.

An administrator first switches on **Platform → Settings → Functions → analytics
tokens**, because a token lets data leave OpenZEV for wherever the tool runs.

Create one under **Account → Tokens & keys → New analytics token**: give it a name,
choose what it may read (a whole community you can view, or only your own data in it)
and an expiry. Administrators can choose any community. The token is shown **once**:

```text
oza_3f9a1c04b7e2_kR8vN2pQ...
```

Copy it now; OpenZEV keeps only a hash. Use it as a bearer token:

```bash
curl -H "Authorization: Bearer oza_3f9a1c04b7e2_kR8vN2pQ..." \
  "https://your-openzev.example.com/api/v1/analytics/series/?from=2026-06-01&to=2026-06-30"
```

A token that is scoped to a ZEV needs no `zev` parameter. The tab lists your tokens and
revokes one at once; the same is available as `GET /api/v1/analytics/tokens/` and
`DELETE /api/v1/analytics/tokens/<id>/`. A token is private to the account that created
it: a manager does not see a participant's tokens (an administrator can list and revoke
every credential on the platform). Creating and revoking are in the audit log.

A token is only as strong as the account behind it: if its creator loses access to the
ZEV (or a participant leaves), the token stops working.

## Grafana

1. Install the [Infinity datasource](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/)
   (`GF_INSTALL_PLUGINS=yesoreyeram-infinity-datasource`).
2. Create an analytics token as above.
3. Add the datasource. Either provision it from
   [`deploy/grafana/provisioning/datasources/openzev.yaml`](https://github.com/splattner/openzev/blob/main/deploy/grafana/provisioning/datasources/openzev.yaml)
   (set `OPENZEV_URL` and `OPENZEV_ANALYTICS_TOKEN` in Grafana's environment), or in the
   UI: authentication **Bearer token**, and your OpenZEV address under **Allowed hosts**.
4. Import the example dashboard
   [`deploy/grafana/dashboards/openzev-analytics.json`](https://github.com/splattner/openzev/blob/main/deploy/grafana/dashboards/openzev-analytics.json)
   and set its `baseUrl` variable to your address, or provision the whole
   `deploy/grafana/` folder.

The example shows self-sufficiency per month, consumption per participant and month,
and local versus grid energy per hour. For your own panels use a query of type **JSON**,
source **URL**, **Root selector** `results`, the URL
`https://your-openzev.example.com/api/v1/analytics/series/` and these parameters:
`from` = `${__from:date:YYYY-MM-DD}`, `to` = `${__to:date:YYYY-MM-DD}`, plus
`granularity`, `group_by` and `direction`. Map `bucket_start` as a **Timestamp** column
and the kWh columns as **Number** columns. To draw one line per participant, add the
*Partition by values* transformation on `participant`.

### Grafana on the database (not supported)

Pointing Grafana straight at PostgreSQL bypasses the access rules (the database user
sees every ZEV), cannot show the local/grid split (it is computed, not stored) and
ignores the Swiss calendar. It is only an option for a self-hoster who accepts all
three, with an administrator-only account, at their own risk.

## Privacy

Every chart request sends your data to the tool that asks. For Grafana that is your own
server or Grafana Cloud — check where yours runs before connecting a ZEV with other
people's consumption in it.
