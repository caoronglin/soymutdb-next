# syntax=docker/dockerfile:1.7
# =====================================================================
# SoyMutDB JBrowse standalone app — reproducible multi-stage build
# =====================================================================
FROM node:24.19.0-alpine AS base
RUN corepack enable && corepack prepare pnpm@11.21.0 --activate
WORKDIR /app

# ---- deps stage: install the complete workspace from the root lockfile
FROM base AS deps
COPY package.json pnpm-workspace.yaml turbo.json pnpm-lock.yaml ./
COPY packages/shared/package.json packages/shared/package.json
COPY packages/api-client/package.json packages/api-client/package.json
COPY packages/i18n/package.json packages/i18n/package.json
COPY packages/motion/package.json packages/motion/package.json
COPY apps/web/package.json apps/web/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY apps/jbrowse/package.json apps/jbrowse/package.json
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# ---- build stage: compile the real JBrowse app from source ------------
FROM deps AS build
COPY packages/ packages/
COPY apps/jbrowse/ apps/jbrowse/
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
