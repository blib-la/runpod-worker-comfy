#!/usr/bin/env bash

echo "runpod-worker-comfy: Starting ComfyUI"

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

python /ComfyUI/main.py --disable-auto-launch --disable-metadata > /workspace/logs/comfy.log 2>&1 &

echo "runpod-worker-comfy: Starting RunPod Handler"
python3 -u /rp_handler.py