FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend .
RUN npm run build

FROM nginx:1.29-alpine
ARG OCI_TITLE="OpenZEV Frontend"
ARG OCI_DESCRIPTION="OpenZEV frontend web application"
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

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
