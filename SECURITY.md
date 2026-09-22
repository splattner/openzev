# Security Policy

## Supported versions

Only the latest minor release receives security fixes.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report privately by email to [security@openzev.ch](mailto:security@openzev.ch).
GitHub private vulnerability reporting will also be available once it is enabled
for this repository.

No bounty; best-effort response. Coordinated disclosure, 90-day window.

## Scope

In scope:

- Backend API (`backend/`)
- Frontend (`frontend/`)
- Helm chart (`charts/openzev`)
- Container images and compose setups

Out of scope:

- Demo instance
- Third-party identity providers (external OIDC/IdP)
- Already-compromised host, database, or Redis
- Feature requests (roadmap items)

## Dependency management

- Renovate keeps dependencies up to date.
- Dependabot alerts require enabling the repository setting; Renovate handles updates.
- CI audits dependencies weekly (see `dependency-audit` in `.github/workflows/pr-quality.yml`).
