"""Pin the proxy trust boundary across delivery modes.

The shipped protection is the combination of a backend reachable only through
an overwriting proxy, loopback-bound production Compose entry points, and a
matching ``NUM_PROXIES`` value.
"""

import json
from pathlib import Path

import yaml
from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]


def read(name):
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def load_yaml(name):
    return yaml.safe_load(read(name))


class ProxyTrustBoundaryTests(SimpleTestCase):
    def test_production_compose_ports_are_loopback_only(self):
        standard = load_yaml("docker-compose.yml")
        fullstack = load_yaml("docker-compose.fullstack.yml")

        self.assertEqual(standard["services"]["frontend"]["ports"], ["127.0.0.1:8080:8080"])
        self.assertEqual(fullstack["services"]["app"]["ports"], ["127.0.0.1:8080:8080"])
        self.assertNotIn("ports", standard["services"]["backend"])

    def test_production_compose_keeps_one_trusted_hop(self):
        standard = load_yaml("docker-compose.yml")
        fullstack = load_yaml("docker-compose.fullstack.yml")

        self.assertEqual(standard["services"]["backend"]["environment"]["NUM_PROXIES"], 1)
        self.assertEqual(fullstack["services"]["app"]["environment"]["NUM_PROXIES"], 1)

    def test_fullstack_does_not_override_operator_cors(self):
        fullstack = load_yaml("docker-compose.fullstack.yml")

        self.assertNotIn("CORS_ALLOWED_ORIGINS", fullstack["services"]["app"]["environment"])

    def test_nginx_configs_overwrite_xff(self):
        for name in ("frontend/nginx.compose.conf", "docker/fullstack-nginx.conf"):
            nginx = read(name)
            with self.subTest(config=name):
                self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", nginx)
                self.assertNotIn("$proxy_add_x_forwarded_for", nginx)

    def test_dev_compose_keeps_zero_trusted_hops(self):
        compose = load_yaml("docker-compose.dev.yml")

        self.assertEqual(compose["services"]["backend"]["environment"]["NUM_PROXIES"], 0)
        self.assertIn("8001:8000", compose["services"]["backend"]["ports"])

    def test_release_compose_matches_fullstack_trust_boundary(self):
        services = load_yaml("deploy/docker-compose.yml")["services"]
        self.assertEqual(services["app"]["ports"], ["127.0.0.1:8080:8080"])
        self.assertEqual(services["app"]["environment"]["NUM_PROXIES"], 1)
        for name, service in services.items():
            if name != "app":
                self.assertNotIn("ports", service)

    def test_helm_defaults_safe_and_worker_has_no_num_proxies(self):
        values = load_yaml("charts/openzev/values.yaml")
        worker = read("charts/openzev/templates/worker-deployment.yaml")
        backend = read("charts/openzev/templates/backend-deployment.yaml")

        self.assertEqual(values["backend"]["numProxies"], 0)
        self.assertNotIn("NUM_PROXIES", worker)
        self.assertIn("NUM_PROXIES", backend)

    def test_helm_schema_rejects_invalid_num_proxies(self):
        schema = json.loads(read("charts/openzev/values.schema.json"))
        num_proxies = schema["properties"]["backend"]["properties"]["numProxies"]
        self.assertEqual(num_proxies.get("type"), "integer")
        self.assertEqual(num_proxies.get("minimum"), 0)
