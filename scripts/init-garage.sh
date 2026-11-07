#!/bin/sh
# Idempotent bootstrap for the Garage S3 service.
#
# Runs as a one-shot init container after `garage` reports healthy.
# Safe to re-run: every step checks state first.
#
#   1. Assign the single node a layout (zone + capacity)
#   2. Create the bucket if missing
#   3. Import a fixed access-key / secret-key pair so the API container
#      can authenticate with values from env (S3_ACCESS_KEY / S3_SECRET_KEY)
#   4. Grant the key read/write/owner access to the bucket

set -eu

GARAGE="garage"

# Wait for the admin API to respond. The depends_on healthcheck should
# cover this, but a short retry absorbs races on cold starts.
i=0
until $GARAGE status >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "garage admin API not reachable" >&2
        exit 1
    fi
    sleep 1
done

# 1. Layout: assign the single node to zone `dc1` with 1G capacity if no
# role has been assigned yet.
if $GARAGE layout show 2>&1 | grep -q "No nodes currently have a role"; then
    NODE_ID=$($GARAGE status | awk '/HEALTHY/ {print $1; exit}')
    if [ -z "$NODE_ID" ]; then
        echo "could not resolve garage node id" >&2
        exit 1
    fi
    $GARAGE layout assign -z dc1 -c 1G "$NODE_ID"
    LAYOUT_VERSION=$($GARAGE layout show | awk '/Staged/ {print $NF; exit}')
    $GARAGE layout apply --version "${LAYOUT_VERSION:-1}"
fi

# 2. Bucket.
if ! $GARAGE bucket info "$S3_BUCKET" >/dev/null 2>&1; then
    $GARAGE bucket create "$S3_BUCKET"
fi

# 3. Access key. `key import` seeds a key with a known id/secret so the
# app can authenticate with env-provided credentials (same UX as MinIO's
# root user/password envs).
if ! $GARAGE key info "$S3_ACCESS_KEY" >/dev/null 2>&1; then
    $GARAGE key import --yes "$S3_ACCESS_KEY" "$S3_SECRET_KEY" -n "ontokit-app"
fi

# 4. Grant the key access to the bucket.
$GARAGE bucket allow \
    --read --write --owner \
    --key "$S3_ACCESS_KEY" \
    "$S3_BUCKET"

echo "garage init complete: bucket=$S3_BUCKET key=$S3_ACCESS_KEY"
