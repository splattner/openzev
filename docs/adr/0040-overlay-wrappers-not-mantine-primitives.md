# ADR 0040: Share repeated UI behavior when it has real consumers

- Status: Proposed
- Date: 2026-10-16
- Related specs: `2026-10-ui-patterns-and-component-catalog` (reference, §7, §11–§12)
- Related ADRs: 0039 (container choice and tariff pilot), 0032 (one visual language)

## Context

Existing drawers repeat some interaction behavior and tab consumers repeat
application class mappings. That is a reuse opportunity, but a generic overlay
wrapper is not a prerequisite for the proposed in-flow tariff detail pane.
The theme already makes native/Mantine form controls consistent.

## Decision

Reuse existing components and styles first. Extract a wrapper when repeated
behavior or configuration has real consumers and a concrete maintenance payoff.
Validate the tariff pilot before requiring migrations across the application.

- Start the split view in existing tariff feature code and responsive table
  styles. Do not require a new shared `Drawer` or retention helper first.
- `AppTabs` may consolidate repeated class mappings. Preserve Mantine's
  props, refs, compound components, shared classes and keyboard behavior.
- Native disclosures remain valid; share their styling when repetition
  warrants it.
- The editable tariff panel provides a real additional Cancel/Save consumer.
  Reuse existing footer behavior; generalize or rename only as needed for
  that consumer. Do not make a mechanical rename of all dialogs a prerequisite.
- Themed form controls remain directly importable. Direct Mantine usage alone
  is not a defect.
- Enforce landed, accepted contracts with TypeScript and normal lint rules.
  Restrict a library import only when its replacement exists and preserves
  actual consumer behavior. Explain scoped exceptions; no blanket wrapper
  mandate or custom pattern-checking script.

## Consequences

Positive:
- Repeated behavior can still be consolidated without building a UI framework.
- The pilot delivers useful interaction before mechanical migrations.
- Wrappers preserve existing library capabilities and can be checked normally.

Trade-offs:
- Some direct imports and repeated configuration remain until extraction pays.
- Review must assess the actual reuse benefit and explain exceptions.

## Alternatives considered

1. **Immediately ban direct Drawer/Tabs imports and migrate every consumer.**
   Makes abstractions and migration prerequisites before the pilot is proven,
   and risks changing modal behavior merely to share code.
2. **Wrap every Mantine control.** The theme already handles field appearance;
   one wrapper per control has no demonstrated payoff.
3. **Never extract shared behavior.** Leaves real duplication and inconsistent
   interaction ownership where multiple consumers would benefit.
