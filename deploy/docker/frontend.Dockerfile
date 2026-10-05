# Local/self-hosted image for the Next.js dashboard (frontend/). Not used by
# the Render+Vercel deploy. Build context = repo root:
#   docker build -f deploy/docker/frontend.Dockerfile -t dw-ui .

FROM node:20-slim AS builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG NEXT_PUBLIC_MONITOR_API_URL
ENV NEXT_PUBLIC_MONITOR_API_URL=${NEXT_PUBLIC_MONITOR_API_URL}
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL}
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY}
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
