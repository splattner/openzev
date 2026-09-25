# vZEV Feasibility Calculator

The Feasibility Calculator estimates whether forming a vZEV is financially worthwhile — before you have any metering data — and how the benefit splits between the solar producer(s) and the consumers. It is a planning tool: it reads no live data unless you ask it to, and it never changes anything in your ZEV.

## Who can use it and how to open it

- Available to the **admin** and **ZEV owner** roles.
- Open **Feasibility Calculator** in the sidebar. It works standalone — you do not need an existing ZEV to use it.
- It is **off by default**. If the sidebar has no entry, an admin turns it on
  under **Platform → System Settings → Functions**
  (`feasibility_calculator_enabled`).

## What it compares against (the baseline)

The calculator answers the *incremental* question: is forming a vZEV better than the status quo, where the PV system sells everything to the grid at the feed-in tariff and every participant buys all their electricity from the grid at the retail price?

Everything it reports — savings, payback, ROI, NPV — is measured against that baseline.

## Entering your scenario

On wide screens, inputs sit to the left of the results. On narrow screens,
results follow the inputs. The three input sections are described below, and
results update live as you type.

### System & energy

A toggle at the top switches between **Aggregate** and **Participants**.

- **Aggregate** — one total for the whole community:
  - **Annual PV production** — enter kWh directly, or switch to **from kWp** and enter the system size and a specific yield (roughly 850–1050 kWh/kWp/year in Switzerland, depending on orientation and location).
  - **Annual consumption** — the total across all participants.
- **Participants** — add each producer, consumer, or prosumer (a member with both) as a row. The totals are summed automatically, and a per-participant breakdown appears in the results.
- **Self-consumption rate** — the share of production consumed on-site at the same time it is produced. This is the single biggest driver of the result; a typical range is 30–70%. Prefill can measure it from real data — see below.

### Tariffs

All prices are in CHF/kWh.

| Field | Meaning |
| --- | --- |
| **Retail price, all-in** | What a consumer pays the grid: energy + grid fees + levies |
| **Feed-in tariff** | What the grid pays for exported surplus energy |
| **Internal energy price** | What consumers pay the producer for local energy inside the vZEV |

The internal energy price can be entered as **CHF/kWh** or as a **% of retail** ("local = 60% of Netzstrom"). Switching between the two modes keeps the effective price the same. Within a vZEV, local energy is priced as energy only — there is no separate internal grid fee.

### Costs & assumptions

- **Annual operating cost** — metering service, administration, platform.
- **Setup cost** — the one-time metering/admin cost to form the vZEV.
- **Horizon (years)** and **Discount rate (%)** — used to compute the NPV.

## Prefill from a real ZEV

If you already run a ZEV in OpenZEV, select it under **Prefill from a real ZEV** and click **Load**. This is a best-effort starting point to review and adjust — not a substitute for entering your own numbers. It fills in:

- **Participants** — one row per active member, with production and consumption extrapolated from whatever metering history exists. Members with no readings yet are flagged and get a rough default.
- **Self-consumption rate** — measured from the actual metering time series where possible. When it can be measured, a confirmation of the measured value is shown.
- **Tariffs** — from the ZEV's currently active tariffs: retail as the full all-in price (energy + grid fees + levies, including percentage-based levies), the feed-in tariff, and the internal price (including local prices configured as a percentage of the grid price).

Anything it cannot determine keeps the calculator's own default, so you can fill it in yourself.

## Reading the results

### Headline figures

| Figure | Meaning |
| --- | --- |
| **Annual net benefit** | The yearly value the vZEV creates, after operating costs |
| **Payback** | Years for the net benefit to recover the setup cost |
| **ROI** | Annual net benefit ÷ setup cost |
| **NPV** | Discounted value over the horizon, net of the setup cost |
| **Self-consumed** | kWh produced and used locally |
| **Autarky** | Share of consumption covered by local energy |

### Who benefits

Splits the annual value between **consumers** (what they save versus buying from the grid) and the **producer** (what they earn extra versus feeding surplus into the grid). In Participants mode, a per-participant table breaks this down by member.

### Energy flow

A Sankey diagram showing where the energy goes: producers → total local production → self-consumed versus exported, and grid import → consumers. Shown in Participants mode.

### Charts

- **Self-consumption sensitivity** — how the annual net benefit changes if the self-consumption rate turns out higher or lower than assumed, with your scenario and the break-even point marked. Because self-consumption is the hardest input to know in advance, this shows how sensitive the whole case is to it.
- **Internal price fairness** — how the value splits between producer and consumers as the internal energy price moves, with a recommended range and an "equal split" marker. The equal split is not necessarily fair: the producer alone carries the setup cost and operating responsibility, so the recommended range ensures the producer's gain also covers their share of the running costs.
- **Cumulative cashflow** — the running balance over the horizon, starting negative from the setup cost and crossing zero at payback.

## Good to know

- Everything here is a **planning estimate**, not a billed figure. The calculator changes nothing in your ZEV.
- The internal energy price only *redistributes* the benefit between producer and consumers — it does not change the total value the vZEV creates.
- The NPV assumes a constant annual benefit across the horizon (it does not model PV degradation or tariff escalation).
- Prefill approximates high/low (HT/NT) tariffs with a representative rate and treats the internal price as energy-only, so review the prefilled values before relying on them.

## Related

- [Tariff Configuration](07-tariff-configuration.md) — the tariffs prefill reads from
- [How Energy Allocation and Billing Works](08-billing-allocation-explained.md) — the self-consumption model the calculator mirrors
- [Glossary](15-glossary.md) — terms such as vZEV, self-consumption, and autarky
