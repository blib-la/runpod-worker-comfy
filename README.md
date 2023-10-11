# RunPod Worker Comfy

> ComfyUI via API on [RunPod](https://www.runpod.io/) serverless

<!-- toc -->

- [What](#what)

<!-- tocstop -->

---

This worker is using Ubuntu with CUDA drivers as it's base. It setups ComfyUI and makes it available via an runpod-compatible handler. The worker waits until the image was generated in ComfyUI, uploads the image to AWS S3 and provides the URL to the image as a reponse.
This repository houses a Docker setup built on an Ubuntu base with CUDA drivers for enhanced performance.

## Config

### Upload image to AWS S3

| Environment Variable       | Description                                             | Example                                    |
| -------------------------- | ------------------------------------------------------- | ------------------------------------------ |
| `BUCKET_ENDPOINT_URL`      | The endpoint URL of your S3 bucket.                     | `https://s3.amazonaws.com`                 |
| `BUCKET_ACCESS_KEY_ID`     | Your AWS access key ID for accessing the S3 bucket.     | `AKIAIOSFODNN7EXAMPLE`                     |
| `BUCKET_SECRET_ACCESS_KEY` | Your AWS secret access key for accessing the S3 bucket. | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |

## ToDo

- use the network volume

## Setup

## Build the image

`docker build -t timpietruskyblibla/runpod-worker-comfy:1.0.0 .`

## Local testing

- You can test the handler: `python src/rp_handler.py`
- Or you can run the container: `docker-compose up`

Both will use the data from [test_input.json](./test_input.json).

### Test setup for Windows

**Note**: Our hope was that we can use this Docker Image with Docker Desktop on Windows. But regardless what we did, it was not possible. So we decided to use Ubuntu as part of WSL (Windows Subsystem for Linux) inside of Windows. This works without any problems, but only if you don't run Docker on Windows itself.

To run the Docker image on Windows, we need to have WSL2 and a Linux distro (like Ubuntu) installed on Windows.

- Follow the [guide on how to get WSL2 and Linux installed in Windows](https://ubuntu.com/tutorials/install-ubuntu-on-wsl2-on-windows-11-with-gui-support#1-overview) to install Ubuntu
  - You can skip the "Install and use a GUI package" part as we don't need a GUI

* When Ubuntu is installed, you have to login to Ubuntu in the terminal: `wsl -d Ubuntu`
* Update the packages: `sudo apt update`
* [Install Docker in Ubuntu](https://docs.docker.com/engine/install/ubuntu/) & then install docker-compose `sudo apt-get install docker-compose`
* [Install the NVIDIA Toolkit in Ubuntu](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html#configuring-docker) and create the `nvidia` runtime

- [Enable GPU acceleration on Ubuntu on WSL2 to use NVIDIA CUDA](https://ubuntu.com/tutorials/enabling-gpu-acceleration-on-ubuntu-on-wsl2-with-the-nvidia-cuda-platform#1-overview)

  - For the step "Install the appropriate Windows vGPU driver for WSL": If you already have your GPU driver installed on Windows, you can skip this

- Add your user to the `docker` group, so that you can use Docker without `sudo`: `sudo usermod -aG docker $USER`
