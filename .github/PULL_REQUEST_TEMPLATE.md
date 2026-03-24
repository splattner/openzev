## Summary

Describe what changed and why.

## Linked spec

- Spec: <!-- e.g. docs/specs/2026-03-foo.md -->
- ADR (if architecture decision changed): <!-- e.g. docs/adr/0009-... -->

If this PR is small and does not need a spec, explain why:

<!-- e.g. isolated bugfix, no API or workflow impact -->

## Validation

- Backend tests run: `python -m pytest metering/ accounts/ invoices/ -q`
- Frontend build run: `npm run build`
- Manual checks done:
  - [ ] Role and ZEV scope behavior
  - [ ] Billing/invoice correctness (if applicable)
  - [ ] i18n coverage for user-facing frontend changes

## Checklist

- [ ] I updated or linked a spec for larger/risky/cross-cutting changes
- [ ] I updated or linked ADRs for architecture-level decisions
- [ ] I updated backend and frontend together where API contracts changed
