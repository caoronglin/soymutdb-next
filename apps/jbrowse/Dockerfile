# syntax=docker/dockerfile:1.7
# =====================================================================
# SoyMutDB JBrowse standalone app — reproducible multi-stage build
# =====================================================================
FROM node:26.10.0-alpine AS base
RUN corepack enable && corepack prepare pnpm@12.5.1 --activate
WORKDIR /app

# ---- deps stage: install the complete workspace from the root lockfile
FROM base AS deps
COPY package.json pnpm-workspace.yaml turbo.json pnpm-lock.yaml ./
COPY packages/shared/package.json packages/shared/package.json
COPY packages/api-client/package.json packages/api-client/package.json
COPY packages/i18n-core/package.json packages/i18n-core/package.json
COPY packages/i18n/package.json packages/i18n/package.json
COPY packages/ui-react/package.json packages/ui-react/package.json
COPY packages/query-keys/package.json packages/query-keys/package.json
COPY packages/charts/package.json packages/charts/package.json
COPY packages/genome-view-model/package.json packages/genome-view-model/package.json
COPY packages/genome-data/package.json packages/genome-data/package.json
COPY packages/genome-view/package.json packages/genome-view/package.json
COPY apps/web/package.json apps/web/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY apps/jbrowse/package.json apps/jbrowse/package.json
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# ---- build stage: compile the real JBrowse app from source ------------
FROM deps AS build
COPY packages/ packages/
COPY apps/jbrowse/ apps/jbrowse/

# The JBrowse Umi build bakes the API/data/embed origins into the CSP
# and fails closed without them, so the image build must supply them. Defaults
# match the offline CI fixture; override with `--build-arg` for a deployment.
ARG VITE_API_BASE_URL=https://api.soymutdb.test
ARG VITE_JBROWSE_DATA_URL=/jbrowse-data
ARG VITE_BASE_URL=/
ARG SOYMUTDB_PORTAL_ORIGIN=https://portal.soymutdb.test
ARG SOYMUTDB_ADMIN_ORIGIN=https://admin.soymutdb.test
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_JBROWSE_DATA_URL=${VITE_JBROWSE_DATA_URL} \
    VITE_BASE_URL=${VITE_BASE_URL} \
    SOYMUTDB_PORTAL_ORIGIN=${SOYMUTDB_PORTAL_ORIGIN} \
    SOYMUTDB_ADMIN_ORIGIN=${SOYMUTDB_ADMIN_ORIGIN}

RUN pnpm --filter @soymutdb/jbrowse build

# ---- runtime stage: nginx serves the generated static assets ----------
FROM nginx:1.27-alpine AS runtime
RUN apk upgrade --no-cache
COPY --from=build /app/apps/jbrowse/dist /usr/share/nginx/html
COPY apps/jbrowse/nginx.conf /etc/nginx/conf.d/default.conf
# Shared security-header fragment; the config includes it at server and
# location level, so it must be present in the image.
COPY infra/nginx/conf.d/security-headers.inc /etc/nginx/conf.d/security-headers.inc
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --spider -q http://localhost:80/ || exit 1
