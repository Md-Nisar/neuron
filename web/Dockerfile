# The web app for the local stack (`docker compose up`): built here, served as static files by
# unprivileged nginx on port 8080. The defaults in `src/lib/auth/config.ts` and `src/lib/api.ts`
# already point at the local Keycloak (localhost:8180) and API (127.0.0.1:8000).
# node:22.22.0-bookworm-slim
FROM node:26.13.1-bookworm-slim@sha256:5df79989ed685e09f0a98019db4cebfb22fb9df1a53c0161664a011f7ff6b0f1 AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
# Type checks and tests run in CI (`make web`); the image only bundles.
RUN ./node_modules/.bin/vite build

# nginxinc/nginx-unprivileged:1.31-alpine
FROM nginxinc/nginx-unprivileged:1.31-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
