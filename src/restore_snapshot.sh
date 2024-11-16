#!/usr/bin/env bash

set -e

SNAPSHOT_FILE=$(ls /snapshot.json /*_snapshot.json 2>/dev/null | head -n 1)

if [ -z "$SNAPSHOT_FILE" ]; then
    echo "runpod-worker-comfy: No snapshot file found. Exiting..."
    exit 0
fi

echo "runpod-worker-comfy: found snapshot file: $SNAPSHOT_FILE"

comfy --workspace /comfyui node restore-snapshot "$SNAPSHOT_FILE"

echo "runpod-worker-comfy: restored snapshot file: $SNAPSHOT_FILE"