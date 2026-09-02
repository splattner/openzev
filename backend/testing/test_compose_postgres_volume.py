"""The compose files must agree on where the Postgres cluster lives.

All three stacks share the named volume ``postgres_data``. When they mount it
at different paths, each gets a cluster the others cannot see: starting one,
then another, looks like the database was silently wiped, with nothing in the
logs pointing at the cause (#492).

The mount path alone is not enough. ``postgres:18-alpine`` defaults ``PGDATA``
to ``/var/lib/postgresql/$PG_MAJOR/docker``, so the major version is baked into
the path — if the cluster location is left implicit, the next major bump points
at an empty directory and initdb builds a fresh cluster over a volume that
still holds the old one. So ``PGDATA`` is pinned, and it has to sit *inside*
the mount or the data is not on the volume at all.
"""

from pathlib import Path

import yaml
from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.dev.yml",
    "docker-compose.fullstack.yml",
)
VOLUME_NAME = "postgres_data"


def _db_service(filename: str) -> dict:
    with (REPO_ROOT / filename).open() as handle:
        return yaml.safe_load(handle)["services"]["db"]


def _postgres_mount(service: dict) -> str:
    """The container path the shared volume is mounted at."""
    for entry in service.get("volumes", []):
        # Short syntax ("name:/path") is what these files use; long syntax is
        # accepted so a later reformat does not quietly skip the assertion.
        if isinstance(entry, str):
            source, _, target = entry.partition(":")
            if source == VOLUME_NAME:
                return target.split(":")[0]
        elif entry.get("source") == VOLUME_NAME:
            return entry["target"]
    raise AssertionError(f"no {VOLUME_NAME} mount found in {service.get('volumes')!r}")


class ComposePostgresVolumeTests(SimpleTestCase):
    def test_every_compose_file_mounts_the_volume_at_the_same_path(self):
        mounts = {name: _postgres_mount(_db_service(name)) for name in COMPOSE_FILES}
        self.assertEqual(
            len(set(mounts.values())),
            1,
            f"compose files disagree on the {VOLUME_NAME} mount path: {mounts}",
        )

    def test_every_compose_file_pins_the_same_pgdata(self):
        pgdata = {
            name: _db_service(name).get("environment", {}).get("PGDATA")
            for name in COMPOSE_FILES
        }
        self.assertNotIn(
            None,
            pgdata.values(),
            f"PGDATA must be pinned, not inherited from the image: {pgdata}",
        )
        self.assertEqual(len(set(pgdata.values())), 1, f"PGDATA differs: {pgdata}")

    def test_pgdata_lives_inside_the_mounted_volume(self):
        for name in COMPOSE_FILES:
            service = _db_service(name)
            mount = _postgres_mount(service)
            pgdata = service.get("environment", {}).get("PGDATA")
            with self.subTest(compose_file=name):
                self.assertIsNotNone(pgdata, f"{name} does not pin PGDATA")
                self.assertTrue(
                    pgdata.startswith(f"{mount}/"),
                    f"PGDATA {pgdata!r} is not inside the volume mounted at {mount!r}, "
                    "so the cluster would live in the container's writable layer "
                    "and vanish when the container is recreated",
                )
