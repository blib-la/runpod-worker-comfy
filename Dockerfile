# Stage 1: Base image with common dependencies
FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04

# Prevents prompts from packages asking for user input during installation
ENV DEBIAN_FRONTEND=noninteractive
# Prefer binary wheels over source distributions for faster pip installations
ENV PIP_PREFER_BINARY=1
# Ensures output from python is printed immediately to the terminal without buffering
ENV PYTHONUNBUFFERED=1 
# Speed up some cmake builds
ENV CMAKE_BUILD_PARALLEL_LEVEL=8

# Install Python, git and other necessary tools
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    git \
    wget \
    libsm6 \
    libgl1 \
    libglib2.0-0 \
    libxext6 \
    libxrender1 \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip \
    && apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/*


# Python Evn
RUN pip3 install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121


WORKDIR /app
RUN git clone https://github.com/comfyanonymous/ComfyUI.git
RUN pip3 install -r /app/ComfyUI/requirements.txt

## install custom nodes
WORKDIR /app/ComfyUI/custom_nodes
RUN git clone https://github.com/Acly/comfyui-tooling-nodes.git && pip3 install -r comfyui-tooling-nodes/requirements.txt
RUN git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
RUN git clone https://github.com/MariusKM/ComfyUI-BadmanNodes.git && pip3 install -r ComfyUI-BadmanNodes/requirements.txt
RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git && pip3 install -r ComfyUI-KJNodes/requirements.txt


# Change working directory to ComfyUI
WORKDIR /app/ComfyUI
# Install runpod
RUN pip install runpod requests

# Support for the network volume
ADD src/extra_model_paths.yaml ./

# Go back to the root
WORKDIR /

# Add scripts
ADD src/start.sh src/rp_handler.py test_input.json ./
RUN chmod +x /start.sh

# Start container
CMD ["/start.sh"]