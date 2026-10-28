#!/bin/sh
# Reference stack only: the directory the WAL archive command copies segments into.
set -eu
mkdir -p /var/lib/postgresql/wal_archive
