FROM node:22-bookworm-slim AS dependencies

WORKDIR /workspace

COPY package.json package-lock.json ./
COPY apps/admin-portal/package.json apps/admin-portal/package.json

RUN npm ci --workspace apps/admin-portal --include-workspace-root


FROM node:22-bookworm-slim AS build

WORKDIR /workspace

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=dependencies /workspace/node_modules ./node_modules
COPY . .

RUN npm run build:portal


FROM node:22-bookworm-slim AS runtime

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

RUN addgroup --system --gid 10001 platform \
    && adduser --system --uid 10001 --ingroup platform platform

COPY --from=build --chown=platform:platform /workspace/apps/admin-portal/.next/standalone ./
COPY --from=build --chown=platform:platform /workspace/apps/admin-portal/.next/static ./apps/admin-portal/.next/static

USER platform

EXPOSE 3000

CMD ["node", "apps/admin-portal/server.js"]
