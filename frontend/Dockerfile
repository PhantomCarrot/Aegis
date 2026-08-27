# Only used by the local Docker quickstart (see ../docker-compose.yml) — a
# real deployment runs this on Vercel instead (see docs/deployment.md),
# which ignores this file entirely.

FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Runtime stage: only the standalone server output (see "output:
# standalone" in next.config.ts) — no source, no node_modules, no
# dev-only dependencies.
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
