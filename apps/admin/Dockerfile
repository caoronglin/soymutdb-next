# syntax=docker/dockerfile:1.7
# =====================================================================
# SoyMutDB Admin console — multi-stage build
# =====================================================================
FROM node:24-alpine AS base
RUN corepack enable && corepack prepare pnpm@10.0.0 --activate
WORKDIR /app

# ---- deps stage ----------------------------------------------------
FROM base AS deps
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml* ./
COPY packages/ui/package.json packages/ui/
COPY packages/shared/package.json packages/shared/
COPY packages/api-client/package.json packages/api-client/
COPY packages/i18n/package.json packages/i18n/
COPY apps/admin/package.json apps/admin/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# ---- build stage ---------------------------------------------------
FROM deps AS build
COPY packages/ packages/
COPY apps/admin/ apps/admin/
RUN pnpm --filter @soymutdb/admin build

# ---- runtime stage: nginx -----------------------------------------
FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/apps/admin/dist /usr/share/nginx/html
COPY apps/admin/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --spider -q http://localhost:80/ || exit 1
