# Builds and runs the Next.js dashboard (frontend/) for Hugging Face
# Spaces' Docker SDK. Build context must be the repo root so this can
# COPY frontend/. See README.md in this directory for setup.

FROM node:20-slim AS builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG NEXT_PUBLIC_MONITOR_API_URL
ENV NEXT_PUBLIC_MONITOR_API_URL=${NEXT_PUBLIC_MONITOR_API_URL}
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-p", "3000"]
