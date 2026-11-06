# The web app for the local stack (`docker compose up`): built here, served as static files by
# unprivileged nginx on port 8080. The defaults in `src/lib/auth/config.ts` and `src/lib/api.ts`
# already point at the local Keycloak (localhost:8180) and API (127.0.0.1:8000).
# node:22.22.0-bookworm-slim
FROM node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94 AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
# Type checks and tests run in CI (`make web`); the image only bundles.
RUN npx vite build

# nginxinc/nginx-unprivileged:1.29-alpine
FROM nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
