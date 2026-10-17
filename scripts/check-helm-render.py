"""Check chart routing, transport values, overrides, and development-default guards."""
import json
import subprocess
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1] / "charts" / "openzev"
RELEASE = "security-check-openzev"
PRODUCTION = {
    "secretKey.existingSecret.name": "openzev-django-secret",
    "database.existingSecret.name": "openzev-db-secret",
    "frontendUrl": "https://openzev.example.com",
}
INLINE_PRODUCTION = {
    "secretKey.value": "real-secret-for-render-check",
    "database.url": "postgres://user:pass@db.example:5432/openzev",
    "frontendUrl": PRODUCTION["frontendUrl"],
}


def value_args(values):
    return [arg for key, value in values.items() for arg in ("--set-json", f"{key}={json.dumps(value)}")]


def render(*options):
    manifest = subprocess.check_output(
        ["helm", "template", "security-check", str(CHART), *options], text=True, timeout=30,
    )
    return [doc for doc in yaml.safe_load_all(manifest) if doc]


def resource(documents, kind, component):
    document, = [doc for doc in documents if doc["kind"] == kind and doc["metadata"]["name"] == f"{RELEASE}-{component}"]
    return document


def backend_environment(documents):
    deployment = resource(documents, "Deployment", "backend")
    backend, = [container for container in deployment["spec"]["template"]["spec"]["containers"] if container["name"] == "backend"]
    names = [entry["name"] for entry in backend["env"]]
    assert len(names) == len(set(names)), "Backend environment names must be unique."
    return {entry["name"]: entry.get("value") for entry in backend["env"]}


def check_public_routes(documents):
    ingress, = [doc for doc in documents if doc["kind"] == "Ingress"]
    paths = [path for rule in ingress["spec"]["rules"] for path in rule["http"]["paths"]]
    assert {(path["path"], path["pathType"], path["backend"]["service"]["name"]) for path in paths} == {
        ("/", "Prefix", f"{RELEASE}-frontend"),
        ("/api", "Prefix", f"{RELEASE}-backend"),
    }, "Public /admin routes must use the frontend; only /api belongs to the backend."
    assert resource(documents, "Service", "backend")["spec"]["type"] == "ClusterIP"
    frontend = resource(documents, "Service", "frontend")
    assert frontend["spec"]["ports"][0]["port"] == 80
    assert frontend["spec"]["ports"][0]["targetPort"] == "http"
    pod = resource(documents, "Deployment", "frontend")["spec"]["template"]["spec"]
    assert pod["containers"][0]["ports"][0]["containerPort"] == 8080


def reject(options, expected):
    result = subprocess.run(
        ["helm", "template", "security-check", str(CHART), *options],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode != 0, f"Expected render failure for {expected}"
    slash = expected.replace(".", "/")
    assert expected in result.stderr or slash in result.stderr, result.stderr


def main():
    for key in INLINE_PRODUCTION:
        other_values = {name: value for name, value in INLINE_PRODUCTION.items() if name != key}
        reject(value_args(other_values), key)
        for empty_value in ("", " "):
            reject(value_args({**INLINE_PRODUCTION, key: empty_value}), key)
    for key in ("debug", "backend.secureSslRedirect"):
        reject(["--set-string", f"{key}=false"], key)
    for key in ("backend.numProxies", "backend.hstsSeconds"):
        reject(value_args({key: -1}), key)
    for key in ("DEBUG", "NUM_PROXIES", "SECURE_SSL_REDIRECT", "SECURE_HSTS_SECONDS"):
        reject(value_args({"debug": True, f"backend.extraEnv.{key}": "false"}), f"backend.extraEnv.{key}")

    for debug, proxies, redirect, hsts in (
        (True, 0, False, 0), (True, 0, True, 31536000),
        (False, 0, True, 31536000), (False, 1, True, 31536000),
        (False, 1, False, 0), (False, 2, True, 1234),
    ):
        documents = render(*value_args({
            **PRODUCTION, "debug": debug, "backend.numProxies": proxies,
            "backend.secureSslRedirect": redirect, "backend.hstsSeconds": hsts,
            "backend.extraEnv.OAUTH_ALLOW_PRIVATE_HOSTS": "True",
            "backend.extraEnv.DJANGO_ADMIN_ENABLED": "True",
        }))
        check_public_routes(documents)
        environment = backend_environment(documents)
        assert environment["DEBUG"] == str(debug).lower()
        assert environment["NUM_PROXIES"] == str(proxies)
        assert environment["SECURE_SSL_REDIRECT"] == str(redirect).lower()
        assert environment["SECURE_HSTS_SECONDS"] == str(hsts)
        assert environment["OAUTH_ALLOW_PRIVATE_HOSTS"] == "True"
        assert environment["DJANGO_ADMIN_ENABLED"] == "True"

    documents = render(*value_args(PRODUCTION))
    for component in ("backend", "worker", "beat", "frontend"):
        pod = resource(documents, "Deployment", component)["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsUser"] == 10001
        assert pod["containers"][0]["securityContext"]["capabilities"]["drop"] == ["ALL"]

    documents = render(*value_args({
        **PRODUCTION, "backend.securityContext.readOnlyRootFilesystem": True,
        "backend.resources": {},
    }))
    pod = resource(documents, "Deployment", "backend")["spec"]["template"]["spec"]
    assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True
    assert pod["containers"][0]["securityContext"]["allowPrivilegeEscalation"] is False
    assert pod["containers"][0]["resources"]["limits"]["memory"] == "1Gi"
    removals = {f"{component}.{key}": None for component in ("backend", "worker", "beat", "frontend")
                for key in ("podSecurityContext", "securityContext", "resources")}
    documents = render(*value_args({**PRODUCTION, **removals}))
    for component in ("backend", "worker", "beat", "frontend"):
        pod = resource(documents, "Deployment", component)["spec"]["template"]["spec"]
        assert "securityContext" not in pod
        assert "securityContext" not in pod["containers"][0]
        assert "resources" not in pod["containers"][0]
    print("Helm routing, transport, guard, and override checks passed.")


if __name__ == "__main__":
    main()
