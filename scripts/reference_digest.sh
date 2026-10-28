#!/bin/sh
# Print the image ID and repo digest of every running reference-stack API replica (ADR 0012).
# A locally built image has no registry digest; its ID (a content hash) is printed instead.
set -eu
for service in api1 api2; do
    container=$(docker compose -f docker-compose.reference.yml ps -q "$service")
    docker inspect --format "$service {{.Config.Image}} {{.Image}}" "$container"
done
