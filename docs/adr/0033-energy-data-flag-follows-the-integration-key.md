# ADR 0033: The energy data flag defaults to on once the integration key is configured

- Status: Accepted
- Date: 2026-10-11

## Context

[SPEC-2026-supplementary-energy-data](../specs/2026-10-supplementary-energy-data.md) shipped behind
`FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED`, off by default. Getting one meter's data in meant
an admin finding the switch under Platform → Settings → Functions, even after they had already
generated and configured `INTEGRATION_ENCRYPTION_KEYS` ([ADR 0031](0031-integration-credentials-encrypted-under-a-dedicated-key.md)),
which is the real opt-in: the key is only ever set by someone who intends to use the feature.
Nothing led from the one step to the other ([#944](https://github.com/splattner/openzev/issues/944)).

The flag still has a job. The instance makes outbound calls to Solar Manager once a source is
connected, and an operator may want the feature off regardless of the key.

`FeatureFlag` stores a boolean per flag, seeded from the code default the first time the admin
list is read. A stored `False` therefore does not say whether an admin switched the flag off or
nobody has looked at it yet, which is exactly the distinction a default that depends on
configuration needs.

## Decision

- **The default is computed, not fixed.** `FeatureFlag.register(..., dynamic_default=fn)` registers
  a function evaluated on every read for as long as no admin has chosen a value. The energy data
  flag's function is "`INTEGRATION_ENCRYPTION_KEYS` is configured". Flags without one are untouched.
- **A new `FeatureFlag.follows_default` column records "not chosen yet".** It is set when the row is
  seeded for a flag with a computed default and cleared by the admin update endpoint as soon as a
  request carries `enabled`. `is_enabled` resolves: environment override, then the stored value
  unless the row follows its default, then the default. An explicit "off" therefore stays off with
  the key configured, and an explicit "on" stays on without it (push and file sources need no key).
- **The admin API reports the effective value.** `GET /auth/feature-flags/` returns `enabled` as
  what the flag currently resolves to, for every row and including an environment override, and adds
  read-only `follows_default` and `controlled_by_env`, so the toggle shows the truth and the page can
  say "on because the key is configured" or "set by the environment". The audit diff of an update
  covers the effective value and `follows_default`.
- **Existing rows.** A stored "off" for this flag is migrated to `follows_default = true`: the flag
  has only ever shipped off, and an existing "off" cannot be told from the seeded default. A stored
  "on" is kept as a choice. An admin who had deliberately switched it off and has a key configured
  must switch it off once more.
- **While the flag is off nothing about the feature is shown to participants**, as before: no
  entry point and no "ask your admin" hint (the endpoints answer `404`).

## Consequences

Positive:
- An admin who configured the key has nothing left to discover.
- The kill switch survives: it is a stored choice that no configuration change overrides.
- The mechanism is general (any later flag whose sensible default depends on configuration).

Negative / risks:
- One more state to explain: a flag can be on without anyone having switched it on. The Functions
  tab shows that it follows its default.
- The one-time migration may turn the feature on for an instance whose admin had switched it off
  and has the key configured. Called out in the release notes.
- There is no "reset to default" control; clearing the choice needs a database edit.

## Alternatives considered

1. **Seed `enabled` from the key when the row is created.** Cannot follow a key configured later,
   and an existing `False` row would still hide the feature.
2. **Treat `False` as "follow the default".** Makes an explicit off impossible.
3. **Drop the flag; key presence is the only switch.** Loses the operator kill switch and the
   ability to run the feature on push and file sources only.
