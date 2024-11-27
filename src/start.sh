#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

if [ -d "/runpod-volume/inputs" ]; then
    cp -r /runpod-volume/inputs/* /app/ComfyUI/input/
else
    echo "Source directory /runpod-volume/inputs does not exist."
fi

# Serve the API and don't shutdown the container
if [ "$SERVE_API_LOCALLY" == "true" ]; then
    echo "runpod-worker-comfy: Starting ComfyUI"
    python3 app/ComfyUI/main.py --disable-auto-launch --disable-metadata --highvram --disable-smart-memory --listen &

    echo "runpod-worker-comfy: Starting RunPod Handler"
    python3 -u /rp_handler.py --rp_serve_api --rp_api_host=0.0.0.0
else
    echo "runpod-worker-comfy: Starting ComfyUI"
    python3 app/ComfyUI/main.py --disable-auto-launch --disable-metadata --highvram --disable-smart-memory &

    echo "runpod-worker-comfy: Starting RunPod Handler"
    python3 -u /rp_handler.py
fi
