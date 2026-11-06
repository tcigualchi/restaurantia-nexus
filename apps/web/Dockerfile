# syntax=docker/dockerfile:1.7
# Build context: repository root.
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
RUN npm run build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN groupadd --system nexus && useradd --system --gid nexus --uid 10001 nexus
COPY --from=build --chown=nexus:nexus /app/.next/standalone ./
COPY --from=build --chown=nexus:nexus /app/.next/static ./.next/static
COPY --from=build --chown=nexus:nexus /app/public ./public
USER nexus
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
