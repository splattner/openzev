FROM python:3.14-slim

ARG OCI_TITLE="OpenZEV Backend"
ARG OCI_DESCRIPTION="OpenZEV backend API service"
ARG OCI_URL="https://github.com/splattner/openzev"
ARG OCI_SOURCE="https://github.com/splattner/openzev"
ARG OCI_VENDOR="OpenZEV"
ARG OCI_LICENSES="AGPL-3.0"
ARG OCI_AUTHORS="OpenZEV Contributors"
ARG OCI_VERSION="dev"
ARG OCI_REVISION="unknown"
ARG OCI_CREATED="unknown"

LABEL org.opencontainers.image.title="$OCI_TITLE" \
    org.opencontainers.image.description="$OCI_DESCRIPTION" \
    org.opencontainers.image.url="$OCI_URL" \
    org.opencontainers.image.source="$OCI_SOURCE" \
    org.opencontainers.image.vendor="$OCI_VENDOR" \
    org.opencontainers.image.licenses="$OCI_LICENSES" \
    org.opencontainers.image.authors="$OCI_AUTHORS" \
    org.opencontainers.image.version="$OCI_VERSION" \
    org.opencontainers.image.revision="$OCI_REVISION" \
    org.opencontainers.image.created="$OCI_CREATED"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/openzev-cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    pkg-config \
    default-libmysqlclient-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libffi-dev \
    shared-mime-info \
    fonts-inter \
    fonts-liberation \
    fonts-noto \
    && rm -rf /var/lib/apt/lists/*

# The PDFs are set in Inter; without it fontconfig falls back to another face
# silently, so fail the build instead.
RUN test "$(fc-match -f '%{family[0]}' Inter)" = Inter \
    || { echo "fonts-inter is not installed: the PDFs would not render in Inter" >&2; exit 1; }

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    pip install --no-cache-dir mysqlclient

RUN groupadd --system --gid 10001 openzev \
    && useradd --system --uid 10001 --gid openzev --home /app openzev
COPY backend /app
RUN mkdir -p /app/media && chown 10001:10001 /app/media
USER 10001:10001

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate && exec gunicorn config.wsgi:application --config /app/gunicorn.conf.py --bind 0.0.0.0:8000"]
