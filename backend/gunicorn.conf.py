import os

# Django owns forwarded-scheme trust through NUM_PROXIES; keep Gunicorn neutral.
secure_scheme_headers = {}
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")
control_socket = "/tmp/gunicorn.ctl"
accesslog = "-"
access_log_format = (
    '%({x-forwarded-for}i)s %(l)s %(u)s %(t)s '
    '"%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s"'
)
