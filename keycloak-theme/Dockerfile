# Keycloak with Neuron's login theme, for the local stack (`docker compose up`). The theme JAR
# is built here, so the host needs neither Node, Maven nor a JDK.
# node:22.22.0-bookworm-slim
FROM node:26.12.1-bookworm-slim@sha256:88e480776c6149ff1d098cd304f44bf18057fb5d284a3329b78162d29821e28c AS node

# keycloakify packages the theme with Maven, so the build runs on a Maven and JDK image with
# Node copied in (no package install).
# maven:3.9.16-eclipse-temurin-21
FROM maven:3.9-eclipse-temurin-26@sha256:b2c1ad85954592f9928e84327c65201f308ad9b5d8ed7d5b823717c97bf23fbb AS build
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
WORKDIR /theme
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build-keycloak-theme

# quay.io/keycloak/keycloak:26.0.7
FROM quay.io/keycloak/keycloak:26.8.2@sha256:3879c623248408de29a5303178b5816c77e8dfef3890c361f8c0bbeaa979ba3b
COPY --from=build /theme/dist_keycloak/neuron-theme.jar /opt/keycloak/providers/
USER 1000
