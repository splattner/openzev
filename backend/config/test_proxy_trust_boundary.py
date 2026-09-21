"""Pin the proxy trust boundary across delivery modes.

The shipped protection is the combination of: backend reachable only through
an overwriting proxy + matching NUM_PROXIES. A future change from
``$remote_addr`` back to ``$proxy_add_x_forwarded_for``, or republishing the
backend port, would silently reintroduce spoofing.
"""

from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]


def read(name):
    return (REPO_ROOT / name).read_text()


class ProxyTrustBoundaryTests(SimpleTestCase):
    def test_default_compose_backend_unexposed_with_one_trusted_hop(self):
        compose = read("docker-compose.yml")
        backend_block = compose.split("worker:")[0]
        self.assertIn("NUM_PROXIES: 1", backend_block)
        self.assertNotIn("8001:8000", backend_block)
        self.assertNotIn("ports:", backend_block.split("depends_on:")[0])

    def test_compose_nginx_overwrites_xff(self):
        nginx = read("frontend/nginx.compose.conf")
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", nginx)
        self.assertNotIn("$proxy_add_x_forwarded_for", nginx)

    def test_dev_compose_keeps_zero_trusted_hops(self):
        compose = read("docker-compose.dev.yml")
        self.assertIn("NUM_PROXIES: 0", compose)
        self.assertIn("8001:8000", compose)

    def test_fullstack_matches_overwrite_with_one_hop(self):
        compose = read("docker-compose.fullstack.yml")
        self.assertIn("NUM_PROXIES: 1", compose)
        nginx = read("docker/fullstack-nginx.conf")
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", nginx)
        self.assertNotIn("$proxy_add_x_forwarded_for", nginx)

    def test_helm_defaults_safe_and_worker_has_no_num_proxies(self):
        values = read("charts/openzev/values.yaml")
        self.assertIn("numProxies: 0", values)
        worker = read("charts/openzev/templates/worker-deployment.yaml")
        self.assertNotIn("NUM_PROXIES", worker)
        backend = read("charts/openzev/templates/backend-deployment.yaml")
        self.assertIn("NUM_PROXIES", backend)

    def test_helm_schema_rejects_invalid_num_proxies(self):
        import json

        schema = json.loads(read("charts/openzev/values.schema.json"))
        num_proxies = schema["properties"]["backend"]["properties"]["numProxies"]
        self.assertEqual(num_proxies.get("type"), "integer")
        self.assertEqual(num_proxies.get("minimum"), 0)
