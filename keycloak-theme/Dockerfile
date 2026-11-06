# Keycloak with Neuron's login theme, for the local stack (`docker compose up`). The theme JAR
# is built here, so the host needs neither Node, Maven nor a JDK.
# node:22.22.0-bookworm-slim
FROM node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94 AS node

# keycloakify packages the theme with Maven, so the build runs on a Maven and JDK image with
# Node copied in (no package install).
# maven:3.9.16-eclipse-temurin-21
FROM maven:3.9.16-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS build
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
FROM quay.io/keycloak/keycloak:26.0.7@sha256:4388e2379b7e870a447adbe7b80bd61f5fbf04e925832b19669fda4957f05a81
COPY --from=build /theme/dist_keycloak/neuron-theme.jar /opt/keycloak/providers/
