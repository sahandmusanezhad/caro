# syntax=docker/dockerfile:1.7
#
# The site's own image (docs/REARCHITECTURE.md, phases 1 and 6): the
# standalone server Next.js writes, as the uid that owns nothing. Built from
# webapp/web:
#
#   docker build -t caro-site webapp/web
#
# What the site reads at BUILD time is a build argument, because Next.js
# writes it into the bundle: where /api/* goes (CARO_API, the API's container
# by default), the error reports' DSN and the seller listings' flag. Unset,
# reports are off and the seller links are out of the nav, as on Vercel.

FROM node:22-bookworm-slim AS deps
WORKDIR /web
COPY package.json package-lock.json ./
# extra_ca: an optional certificate for a build behind a proxy that re-signs
# TLS; a build without it reads none.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund

FROM node:22-bookworm-slim AS build
WORKDIR /web
COPY --from=deps /web/node_modules node_modules
COPY . .
ARG CARO_API=http://api:8000
ARG NEXT_PUBLIC_SENTRY_DSN=
ARG NEXT_PUBLIC_SELLER_LISTINGS=
ENV CARO_API=${CARO_API} \
    NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN} \
    NEXT_PUBLIC_SELLER_LISTINGS=${NEXT_PUBLIC_SELLER_LISTINGS} \
    CARO_SITE_STANDALONE=1 \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /web/.next/standalone ./
COPY --from=build --chown=node:node /web/.next/static .next/static
COPY --from=build --chown=node:node /web/public public
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:' + (process.env.PORT || 3000) + '/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]
CMD ["node", "server.js"]
