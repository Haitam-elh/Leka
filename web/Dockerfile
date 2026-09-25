# The LEKA web app, as one image.
#
# NEXT_PUBLIC_API_URL IS DECIDED HERE, AT BUILD TIME. Next.js writes every
# NEXT_PUBLIC_* value into the JavaScript it sends to browsers when it
# builds; setting it on the running container changes nothing. So the image
# is built for one API address, passed as a build argument by CD — and the
# build refuses to start without it rather than quietly calling localhost.
#
# STANDALONE. next.config.ts sets `output: "standalone"`: the build traces
# the server and only the dependencies it uses into .next/standalone, and
# that is all the runtime stage copies. No npm, no dev dependencies, no
# source.
#
# NON-ROOT. The official image ships an unprivileged `node` user.

# ── dependencies ─────────────────────────────────────────────────────────────
# Pinned to the major CI uses. The lock file is generated on Linux (see
# `npm run lock`), which is what this stage is.
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ── build ────────────────────────────────────────────────────────────────────
FROM node:22-slim AS build
WORKDIR /app

ARG NEXT_PUBLIC_API_URL
RUN test -n "$NEXT_PUBLIC_API_URL" \
    || (echo "NEXT_PUBLIC_API_URL is required at build time, e.g. https://api.leka-core.com" >&2 && exit 1)
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
# public/ is optional in a Next app; the runtime stage copies it either way.
RUN mkdir -p public && npm run build

# ── runtime ──────────────────────────────────────────────────────────────────
FROM node:22-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public

USER node
EXPOSE 3000

# /login renders without a session: a 200 means the server is up and
# serving this build. Node's own fetch — no curl to install.
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]

CMD ["node", "server.js"]
