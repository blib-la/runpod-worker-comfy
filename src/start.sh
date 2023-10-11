#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

echo "runpod-worker-comfy: Starting ComfyUI"
python3 /ComfyUI/main.py --disable-auto-launch --disable-metadata &

echo "runpod-worker-comfy: Starting RunPod Handler"
python3 -u /rp_handler.py