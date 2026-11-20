# =============================================================================
# SoyMutDB — Go gateway (apps/gateway-go)
# =============================================================================
# Serving layer for the admin console: the built admin artifact, the
# reverse-proxied API and the read-only statistics aggregate.
#
# Build (the build context is the module itself, so nothing outside
# apps/gateway-go can reach the image):
#
#   docker build -f apps/gateway-go/Dockerfile -t soymutdb-gateway:local apps/gateway-go
#
# The module's only dependency (github.com/lib/pq) is vendored, so the build is
# offline by construction: GOFLAGS=-mod=vendor plus GOPROXY=off means a missing
# vendored package is a build error, never a silent download.
#
# Release wiring is NOT part of this file: no pipeline builds, scans or signs
# this image yet (not listed in scripts/list-images.sh), so a production
# GATEWAY_IMAGE_REF has to be produced out-of-band. See docs/dev/go-gateway.md.
# =============================================================================

FROM golang:1.24.4-alpine AS build

WORKDIR /src
ENV GOFLAGS=-mod=vendor \
    GOPROXY=off \
    CGO_ENABLED=0

# Only the module description, the vendored tree and the packages the binary
# needs are copied: an accidental new top-level file cannot change the image.
COPY go.mod ./
COPY vendor ./vendor
COPY cmd ./cmd
COPY internal ./internal

# -trimpath keeps the build host's checkout path out of the binary; -s -w drop
# the symbol table and DWARF data the gateway never reads.
RUN go build -trimpath -ldflags="-s -w" -o /out/gateway ./cmd/gateway

FROM alpine:3.21

# ca-certificates is not in the alpine base and the upstream API may be served
# over HTTPS. busybox (also in the base) provides the `wget` the Compose
# healthcheck uses.
RUN apk add --no-cache ca-certificates \
    && adduser -D -H -u 10001 gateway

COPY --from=build /out/gateway /usr/local/bin/gateway

USER 10001:10001

# Matches the SOYMUTDB_GATEWAY_ADDR default (:18020).
EXPOSE 18020

# No HEALTHCHECK in the image: the probe needs the mounted artifact directory
# and the configured upstream, so docker-compose.yml owns it (it calls
# /readyz, which checks both).
ENTRYPOINT ["/usr/local/bin/gateway"]