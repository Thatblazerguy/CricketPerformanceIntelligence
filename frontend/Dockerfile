# ── CPI Frontend ─────────────────────────────────────────────────────────────
# Stage 1: build the Vite/React app
FROM node:20-slim AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci --prefer-offline

COPY . .

# Point the built app at the Docker backend.
# The nginx reverse-proxy routes /api → backend:8000, so the frontend
# just needs to call /api (same origin) — no absolute host needed.
ENV VITE_API_BASE_URL=""

RUN npm run build

# Stage 2: serve the built assets with nginx
FROM nginx:1.27-alpine AS runtime

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
