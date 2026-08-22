"""
OpenZEV Django settings.
All sensitive values are read from environment variables (or a .env file).
"""
from pathlib import Path
import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="change-me-in-production-use-a-long-random-string")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Fail fast if the insecure placeholder reaches a DEBUG=False deployment.
_INSECURE_SECRET_KEY = "change-me-in-production-use-a-long-random-string"  # default above, .env.example & Helm
if not DEBUG and SECRET_KEY == _INSECURE_SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY is an insecure placeholder; generate a long random key "
        '(e.g. python -c "import secrets; print(secrets.token_urlsafe(64))") '
        "and set it in the environment when DEBUG=False."
    )

# ── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "django_celery_beat",
    # OpenZEV apps
    "accounts",
    "zev",
    "tariffs",
    "metering",
    "invoices",
    "audit",
    "feasibility",
    "allocation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    # API CSRF is in CookieJWTAuthentication; this middleware stays for admin and Django views.
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "audit.middleware.AuditRequestContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
    {
        # Validation-only engine for the admin PDF-template editor: unknown
        # template variables render as a sentinel (instead of Django's default
        # silent empty string) so PATCH can reject typo'd variables. Loaders
        # mirror the default engine so {% include %} resolves identically.
        "NAME": "strict-validation",
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "string_if_invalid": "__INVALID_TPL_VAR__:%s",
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ── Database ──────────────────────────────────────────────────────────────────
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=env("DATABASE_URL", default=f"sqlite:///{BASE_DIR}/db.sqlite3"),
        conn_max_age=600,
    )
}

# ── Custom user model ─────────────────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"

# ── Password validation ───────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Zurich"
USE_I18N = True
USE_TZ = True

# ── Static & media files ──────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))

# Named in transfer-archive manifests so an imported archive says which
# instance it came from. Empty on a single-instance deployment.
INSTANCE_NAME = env("INSTANCE_NAME", default="")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Django REST Framework ─────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.CookieJWTAuthentication",
        "accounts.authentication.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "accounts.throttling.ApiKeyRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Only applies to key-authenticated requests; cookie sessions return a
        # null cache key and are not throttled.
        "api_key": env("API_KEY_THROTTLE_RATE", default="600/hour"),
        # Per-IP budgets for the public auth endpoints (accounts.throttling).
        "auth_login": env("AUTH_LOGIN_THROTTLE_RATE", default="40/hour"),
        "auth_refresh": env("AUTH_REFRESH_THROTTLE_RATE", default="60/hour"),
        "auth_register": env("AUTH_REGISTER_THROTTLE_RATE", default="10/hour"),
        "auth_verify": env("AUTH_VERIFY_THROTTLE_RATE", default="30/hour"),
        "auth_oauth_initiate": env("AUTH_OAUTH_INITIATE_THROTTLE_RATE", default="60/hour"),
        "auth_oauth_exchange": env("AUTH_OAUTH_EXCHANGE_THROTTLE_RATE", default="40/hour"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
}

# ── API keys ──────────────────────────────────────────────────────────────────
# Applied when a key is created without an explicit expiry. Set to 0 for keys
# that never expire by default (not recommended).
API_KEY_DEFAULT_EXPIRY_DAYS = env.int("API_KEY_DEFAULT_EXPIRY_DAYS", default=365)
# How stale ``last_used_at`` may be before it is rewritten. Bounds the write
# amplification of key authentication; see ApiKeyAuthentication._touch.
API_KEY_LAST_USED_RESOLUTION = timedelta(
    minutes=env.int("API_KEY_LAST_USED_RESOLUTION_MINUTES", default=5)
)

# ── CORS ──────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://localhost:3000"],
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=CORS_ALLOWED_ORIGINS)

# ── DRF Spectacular (OpenAPI) ─────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "OpenZEV API",
    "DESCRIPTION": "REST API for the OpenZEV (v)ZEV billing platform",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="openzev@example.com")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

# ── Cache ─────────────────────────────────────────────────────────────────────
# Separate logical Redis DB from the Celery broker (db 0) so cache keys never
# collide with Celery's own bookkeeping keys.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://localhost:6379/1"),
    }
}

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "cleanup-expired-oauth-tokens": {
        "task": "accounts.tasks.cleanup_expired_oauth_tokens",
        "schedule": 300.0,
    },
}
