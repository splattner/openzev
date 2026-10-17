"""Smoke-test the three locally built openzev-smoke-* images with Docker."""
import json
import subprocess
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
CANARY = "OPENZEV_LOG_SECRET_6b22f11d"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


HTTP = build_opener(NoRedirect)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=90).strip()


def logs(container):
    return subprocess.check_output(["docker", "logs", container], stderr=subprocess.STDOUT, text=True, timeout=30)


def request(container, path="/", body=None, https=True, referer=False):
    port = docker("port", container, "8000" if container.endswith("backend") else "8080").rsplit(":", 1)[1]
    headers = {"Host": "localhost"}
    if referer:
        headers["Referer"] = f"https://localhost/signin/{CANARY}"
    if https:
        headers["X-Forwarded-Proto"] = "https"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers)
    try:
        response = HTTP.open(req, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def main():
    prefix = f"openzev-smoke-{uuid.uuid4().hex[:10]}"
    with ExitStack() as cleanup:
        network = docker("network", "create", prefix)
        cleanup.callback(docker, "network", "rm", network)
        cache = f"{prefix}-valkey"
        docker("run", "-d", "--name", cache, "--network", network,
               "--network-alias", "valkey", "valkey/valkey:9-alpine")
        cleanup.callback(docker, "rm", "-f", cache)
        containers = []
        for component in ("backend", "fullstack", "frontend", "compose"):
            name = f"{prefix}-{component}"
            image = f"openzev-smoke-{'frontend' if component == 'compose' else component}"
            options = ["--network", network, "-p", f"127.0.0.1::{'8000' if component == 'backend' else '8080'}"]
            if component == "backend":
                options += ["--network-alias", "backend"]
            if component in ("backend", "fullstack"):
                volume = docker("volume", "create", name)
                cleanup.callback(docker, "volume", "rm", volume)
                options += ["-v", f"{volume}:/app/media"]
                if component == "fullstack":
                    docker("run", "--rm", "--user", "root", "-v", f"{volume}:/app/media", "--entrypoint", "sh", image,
                           "-c", "chown 0:0 /app/media; echo existing > /app/media/existing.txt")
                    docker("run", "--rm", "-v", f"{volume}:/app/media", "--entrypoint", "sh", image,
                           "-c", "test ! -w /app/media")
                    docker("run", "--rm", "--user", "root", "-v", f"{volume}:/app/media", "--entrypoint", "chown", image,
                           "-R", "10001:10001", "/app/media")
                environment = {
                    "DJANGO_SETTINGS_MODULE": "config.settings", "DEBUG": "True", "DATABASE_URL": "sqlite:////app/media/smoke.sqlite3",
                    "NUM_PROXIES": "1", "SECURE_SSL_REDIRECT": "True", "SECURE_HSTS_SECONDS": "31536000",
                    "GUNICORN_WORKERS": "1", "ALLOWED_HOSTS": "localhost,127.0.0.1",
                    "GUNICORN_CMD_ARGS": "--pid=/tmp/smoke-gunicorn.pid",
                    "CACHE_URL": "redis://valkey:6379/1",
                    "CELERY_BROKER_URL": "redis://valkey:6379/0",
                }
                env_args = [arg for key, value in environment.items() for arg in ("-e", f"{key}={value}")]
                options += env_args
                if component == "backend":
                    celery_options = ["--network", network, "-v", f"{volume}:/app/media", *env_args]
            if component == "compose":
                options += ["-v", f"{ROOT / 'frontend/nginx.compose.conf'}:/etc/nginx/conf.d/default.conf:ro"]
            docker("run", "-d", "--name", name, *options, image)
            cleanup.callback(docker, "rm", "-f", name)
            containers.append(name)
            deadline = time.monotonic() + 90
            while True:
                try:
                    status, _, _ = request(name, "/" if component == "frontend" else "/api/v1/auth/token/")
                    if status in (200, 405):
                        break
                except (URLError, TimeoutError, ConnectionError):
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError(f"{name} did not start:\n{logs(name)}")
                time.sleep(0.2)
            assert docker("exec", name, "id", "-u") == "10001"
            assert docker("exec", name, "id", "-g") == "10001"
            immutable = "/app/config/settings.py" if component in ("backend", "fullstack") else "/usr/share/nginx/html/index.html"
            docker("exec", name, "sh", "-c", f"test ! -w {immutable}")
            if component != "backend":
                docker("exec", name, "sh", "-c", "test ! -w /etc/nginx/conf.d/default.conf")
                token_paths = [
                    f"/signin/{CANARY}", f"/SIGNIN/{CANARY}", f"/SiGnIn/{CANARY}",
                    f"/i/invoice?s={CANARY}", f"/I/invoice?s={CANARY}", f"/JoIn/participant?token={CANARY}",
                    f"/VeRiFy-EmAiL?token={CANARY}", f"/reset-password?token={CANARY}",
                    f"/ReSeT-PaSsWoRd?token={CANARY}", f"/CoNfIrM-EmAiL-ChAnGe?token={CANARY}",
                    f"/OaUtH/CaLlBaCk?code={CANARY}",
                ]
                for path in token_paths:
                    status, headers, _ = request(name, path)
                    assert status == 200
                    assert headers["Referrer-Policy"] == "no-referrer"
                docker("exec", "--user", "root", name, "mv", "/usr/share/nginx/html/index.html", "/tmp/smoke-index.html")
                try:
                    for path in token_paths:
                        status, headers, _ = request(name, path)
                        assert status == 404, (name, path, status)
                        assert headers["Referrer-Policy"] == "no-referrer"
                finally:
                    docker("exec", "--user", "root", name, "mv", "/tmp/smoke-index.html", "/usr/share/nginx/html/index.html")
            if component in ("backend", "fullstack", "compose"):
                assert request(name, "/api/v1/auth/token/", https=False)[0] == 301
                status, headers, _ = request(name, f"/api/v1/auth/token/?token={CANARY}", referer=True)
                assert status == 405
                assert headers["Strict-Transport-Security"] == "max-age=31536000"
                body = json.dumps({"unused": "x" * 65536}).encode()
                assert request(name, "/api/v1/public/magic-link/consume/", body=body)[0] == 400
            if component in ("backend", "fullstack"):
                docker("exec", name, "test", "-S", "/tmp/gunicorn.ctl")
                docker("exec", name, "python", "-c",
                       "import django; django.setup(); from invoices.pdf_render import render_pdf; "
                       "from django.core.files.storage import default_storage; "
                       "from django.core.files.base import ContentFile; "
                       "default_storage.save('smoke.pdf', ContentFile(render_pdf('<p>Smoke</p>')))")
                if component == "fullstack":
                    assert docker("exec", name, "cat", "/app/media/existing.txt") == "existing"

        for image in ("backend", "fullstack"):
            worker = f"{prefix}-{image}-worker"
            for role in ("worker", "beat"):
                name = f"{prefix}-{image}-{role}"
                command = ["celery", "-A", "config", role, "-l", "debug" if role == "beat" else "info"]
                command += (["--concurrency=1", f"--hostname={worker}"] if role == "worker" else
                            ["--scheduler", "django_celery_beat.schedulers:DatabaseScheduler"])
                docker("run", "-d", "--name", name, *celery_options, f"openzev-smoke-{image}", *command)
                cleanup.callback(docker, "rm", "-f", name)
                deadline = time.monotonic() + 60
                marker = " ready." if role == "worker" else "beat: Waking up"
                while marker not in logs(name):
                    assert docker("inspect", "-f", "{{.State.Running}}", name) == "true", logs(name)
                    assert time.monotonic() < deadline, f"{name} did not start:\n{logs(name)}"
                    time.sleep(0.5)
                assert docker("exec", name, "id", "-u") == "10001"
                assert docker("exec", name, "id", "-g") == "10001"
                docker("exec", name, "sh", "-c", "test ! -w /app/config/settings.py")
            docker("exec", worker, "python", "-c",
                   "import django; django.setup(); "
                   "from accounts.tasks import cleanup_expired_oauth_tokens; "
                   "cleanup_expired_oauth_tokens.delay().get(timeout=20)")
            for role in ("beat", "worker"):
                docker("stop", f"{prefix}-{image}-{role}")

        # Keep nginx running while its upstream fails; ordinary errors must remain visible.
        backend = containers[0]
        docker("stop", backend)
        fullstack = containers[1]
        docker("exec", fullstack, "sh", "-c", 'kill -TERM "$(cat /tmp/smoke-gunicorn.pid)"')
        for proxy in (fullstack, containers[-1]):
            deadline = time.monotonic() + 60
            while True:
                try:
                    status = request(proxy, f"/api/v1/public/invoices/prefix/?s={CANARY}", referer=True)[0]
                except (URLError, TimeoutError, ConnectionError):
                    status = None
                if status == 502:
                    break
                assert time.monotonic() < deadline, "Upstream did not stop."
                time.sleep(0.5)
            assert request(proxy, "/api/v1/auth/token/")[0] == 502
        for name in containers:
            output = logs(name)
            assert CANARY not in output, f"Secret leaked by {name}"
            if name in (fullstack, containers[-1]):
                assert "connect() failed" in output and "502" in output, "Ordinary upstream diagnostics disappeared."
    print("Non-root HTTP/worker/beat startup, task execution, media migration/PDF writes, transport, uploads, and logging checks passed.")


if __name__ == "__main__":
    main()
