# Credential provenance upgrade

The upgrade containing `accounts.0028_participant_link_provenance` and
`accounts.0029_mark_legacy_participant_credentials` requires a maintenance window.
Old and new authentication code must not run together after the backfill.

1. Take a database backup and put the application behind a maintenance response.
2. Stop accepting requests and drain in-flight requests, including OAuth callbacks.
   Stop all old web, worker and scheduler processes; none may restart automatically.
3. With the new application image/code, run `python manage.py migrate` once.
4. Start only the new application processes. Check login and participant-link access,
   then remove the maintenance response.

For the published release stack (`deploy/docker-compose.yml`, downloaded as
`docker-compose.yml`), set the new image version in `.env`, then use these commands
while maintenance traffic blocking remains in place:

```bash
docker compose pull
docker compose stop app worker beat
docker compose up -d db valkey
docker compose run --rm --no-deps app python manage.py migrate
docker compose up -d app worker beat
```

The fullstack image's normal startup runs migrations again; that is idempotent.
For source builds, build the updated images first. The fullstack file also uses
`app`; pass `-f docker-compose.fullstack.yml` to its Compose commands. The
two-container `docker-compose.yml` uses `backend` instead of `app` and requires
stopping/starting `frontend` too. Keep database/broker services running. On Kubernetes, drain
and scale old web/worker/scheduler deployments to zero before the migration job;
start only new replicas afterwards. The chart's backend image migrates at startup;
an ordinary Helm rolling upgrade does not enforce this drain sequence.

Do not use a rolling deployment with old workers still serving traffic: old code
can issue sessions and credentials without recording their participant origin.
Do not roll application code back across this boundary while serving traffic.

The backfill signs existing participant-only accounts out once and marks local
credentials whose origin is unknown. Those credentials remain usable for participant
access but cannot establish manager/viewer or issuer/representative access. An
access invitation is needed unless an independent identity qualifies. Existing
protected accounts keep their credentials. The backfill also discards pending OAuth
exchange codes for affected accounts and expires all pending OAuth account-linking
requests, including protected accounts. Users can start linking again after signing in.
Ordinary OAuth login states are preserved.

Reversing the data migration does not undo these trust decisions or restore sessions.
For account recovery after verifying the person's identity, use the documented
[`recover_password` operation](user-guide/11-roles-and-permissions.md#user-cannot-login).
