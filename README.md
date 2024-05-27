# runpod-worker-comfy

Chack out Captain: The AI Platform

- https://github.com/blib-la/captain
- https://get-captain.com

> [ComfyUI](https://github.com/comfyanonymous/ComfyUI) as a serverless API on [RunPod](https://www.runpod.io/)

<p align="center">
  <img src="assets/worker_sitting_in_comfy_chair.jpg" title="Worker sitting in comfy chair" />
</p>

Read our article here: https://blib.la/blog/comfyui-on-runpod

[![Discord](https://img.shields.io/discord/1091306623819059300?color=7289da&label=Discord&logo=discord&logoColor=fff&style=for-the-badge)](https://discord.com/invite/m3TBB9XEkb)

---

<!-- toc -->

- [Quickstart](#quickstart)
- [Features](#features)
- [Config](#config)
  - [Upload image to AWS S3](#upload-image-to-aws-s3)
- [Use the Docker image on RunPod](#use-the-docker-image-on-runpod)
- [API specification](#api-specification)
  - [JSON Request Body](#json-request-body)
  - [Fields](#fields)
    - ["input.images"](#inputimages)
- [Interact with your RunPod API](#interact-with-your-runpod-api)
  - [Health status](#health-status)
  - [Generate an image](#generate-an-image)
    - [Example request with cURL](#example-request-with-curl)
- [How to get the workflow from ComfyUI?](#how-to-get-the-workflow-from-comfyui)
- [Build the image](#build-the-image)
- [Local testing](#local-testing)
  - [Setup](#setup)
    - [Setup for Windows](#setup-for-windows)
  - [Test: handler](#test-handler)
  - [Local API](#local-api)
    - [Starting local endpoint](#starting-local-endpoint)
    - [Accessing the API](#accessing-the-api)
- [Automatically deploy to Docker hub with Github Actions](#automatically-deploy-to-docker-hub-with-github-actions)
- [Acknowledgments](#acknowledgments)

<!-- tocstop -->

---

## Quickstart

- 🐳 Use the latest image for your worker: [timpietruskyblibla/runpod-worker-comfy:latest](https://hub.docker.com/r/timpietruskyblibla/runpod-worker-comfy)
- ⚙️ [Set the environment variables](#config)
- ℹ️ [Use the Docker image on RunPod](#use-the-docker-image-on-runpod)

## Features

- Run any [ComfyUI](https://github.com/comfyanonymous/ComfyUI) workflow to generate an image
- Provide input images as base64-encoded string
- The generated image is either:
  - Returned as base64-encoded string (default)
  - Uploaded to AWS S3 ([if AWS S3 is configured](#upload-image-to-aws-s3))
- Build-in checkpoint:
  - [sd_xl_base_1.0.safetensors](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- Build-in VAE:
  - [sdxl_vae.safetensors](https://huggingface.co/stabilityai/sdxl-vae/)
  - [sdxl-vae-fp16-fix](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/)
- Based on [Ubuntu + NVIDIA CUDA](https://hub.docker.com/r/nvidia/cuda)

## Config

| Environment Variable | Description                                                                                                                                                                        | Default |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `REFRESH_WORKER`     | When you want stop the worker after each finished job to have a clean state, see [official documentation](https://docs.runpod.io/docs/handler-additional-controls#refresh-worker). | `false` |

### Upload image to AWS S3

This is only needed if you want to upload the generated picture to AWS S3. If you don't configure this, your image will be exported as base64-encoded string.

- Create a bucket in region of your choice in AWS S3 (`BUCKET_ENDPOINT_URL`)
- Create an IAM that has access rights to AWS S3
- Create an Access-Key (`BUCKET_ACCESS_KEY_ID` & `BUCKET_SECRET_ACCESS_KEY`) for that IAM
- Configure these environment variables for your RunPod worker:

| Environment Variable       | Description                                             | Example                                      |
| -------------------------- | ------------------------------------------------------- | -------------------------------------------- |
| `BUCKET_ENDPOINT_URL`      | The endpoint URL of your S3 bucket.                     | `https://<bucket>.s3.<region>.amazonaws.com` |
| `BUCKET_ACCESS_KEY_ID`     | Your AWS access key ID for accessing the S3 bucket.     | `AKIAIOSFODNN7EXAMPLE`                       |
| `BUCKET_SECRET_ACCESS_KEY` | Your AWS secret access key for accessing the S3 bucket. | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`   |

## Use the Docker image on RunPod

- Create a [new template](https://runpod.io/console/serverless/user/templates) by clicking on `New Template`
- In the dialog, configure:
  - Template Name: `runpod-worker-comfy` (it can be anything you want)
  - Container Image: `<dockerhub_username>/<repository_name>:tag`, in this case: `timpietruskyblibla/runpod-worker-comfy:latest` (or `dev` if you want to have the development release)
  - Container Registry Credentials: You can leave everything as it is, as this repo is public
  - Container Disk: `20 GB`
  - Enviroment Variables: [Configure S3](#upload-image-to-aws-s3)
    - Note: You can also not configure it, the images will then stay in the worker. In order to have them stored permanently, [we have to add the network volume](https://github.com/blib-la/runpod-worker-comfy/issues/1)
- Click on `Save Template`
- Navigate to [`Serverless > Endpoints`](https://www.runpod.io/console/serverless/user/endpoints) and click on `New Endpoint`
- In the dialog, configure:
  - Endpoint Name: `comfy`
  - Select Template: `runpow-worker-comfy` (or whatever name you gave your template)
  - Active Workers: `0` (whatever makes sense for you)
  - Max Workers: `3` (whatever makes sense for you)
  - Idle Timeout: `5` (you can leave the default)
  - Flash Boot: `enabled` (doesn't cost more, but provides faster boot of our worker, which is good)
  - Advanced: Leave the defaults
  - Select a GPU that has some availability
  - GPUs/Worker: `1`
- Click `deploy`
- Your endpoint will be created, you can click on it to see the dashboard

## API specification

The following describes which fields exist when doing requests to the API. We only describe the fields that are sent via `input` as those are needed by the worker itself. For a full list of fields, please take a look at the [official documentation](https://docs.runpod.io/docs/serverless-usage).

### JSON Request Body

```json
{
  "input": {
    "workflow": {},
    "images": [
      {
        "name": "example_image_name.png",
        "image": "base64_encoded_string"
      }
    ]
  }
}
```

### Fields

| Field Path       | Type   | Required | Description                                                                                                                               |
| ---------------- | ------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `input`          | Object | Yes      | The top-level object containing the request data.                                                                                         |
| `input.workflow` | Object | Yes      | Contains the ComfyUI workflow configuration.                                                                                              |
| `input.images`   | Array  | No       | An array of images. Each image will be added into the "input"-folder of ComfyUI and can then be used in the workflow by using it's `name` |

#### "input.images"

An array of images, where each image should have a different name.

🚨 The request body for a RunPod endpoint is 10 MB for `/run` and 20 MB for `/runsync`, so make sure that your input images are not super huge as this will be blocked by RunPod otherwise, see the [official documentation](https://docs.runpod.io/docs/serverless-endpoint-urls)

| Field Name | Type   | Required | Description                                                                              |
| ---------- | ------ | -------- | ---------------------------------------------------------------------------------------- |
| `name`     | String | Yes      | The name of the image. Please use the same name in your workflow to reference the image. |
| `image`    | String | Yes      | A base64 encoded string of the image.                                                    |

## Interact with your RunPod API

- In the [User Settings](https://www.runpod.io/console/serverless/user/settings) click on `API Keys` and then on the `API Key` button
- Save the generated key somewhere, as you will not be able to see it again when you navigate away from the page
- Use cURL or any other tool to access the API using the API key and your Endpoint-ID:
  - Replace `<api_key>` with your key
  - Replace `<endpoint_id>` with the ID of the endpoint, you find that when you click on your endpoint, it's part of the URLs shown at the bottom of the first box

### Health status

```bash
curl -H "Authorization: Bearer <api_key>" https://api.runpod.ai/v2/<endpoint_id>/health
```

### Generate an image

You can either create a new job async by using `/run` or a sync by using runsync. The example here is using a sync job and waits until the response is delivered.

The API expects a [JSON in this form](#json-request-body), where `workflow` is the [workflow from ComfyUI, exported as JSON](#how-to-get-the-workflow-from-comfyui) and `images` is optional.

Please also take a look at the [test_input.json](./test_input.json) to see how the API input should look like.

#### Example request with cURL

```bash
curl -X POST -H "Authorization: Bearer <api_key>" -H "Content-Type: application/json" -d '{"input":{"workflow":{"3":{"inputs":{"seed":1337,"steps":20,"cfg":8,"sampler_name":"euler","scheduler":"normal","denoise":1,"model":["4",0],"positive":["6",0],"negative":["7",0],"latent_image":["5",0]},"class_type":"KSampler"},"4":{"inputs":{"ckpt_name":"sd_xl_base_1.0.safetensors"},"class_type":"CheckpointLoaderSimple"},"5":{"inputs":{"width":512,"height":512,"batch_size":1},"class_type":"EmptyLatentImage"},"6":{"inputs":{"text":"beautiful scenery nature glass bottle landscape, purple galaxy bottle,","clip":["4",1]},"class_type":"CLIPTextEncode"},"7":{"inputs":{"text":"text, watermark","clip":["4",1]},"class_type":"CLIPTextEncode"},"8":{"inputs":{"samples":["3",0],"vae":["4",2]},"class_type":"VAEDecode"},"9":{"inputs":{"filename_prefix":"ComfyUI","images":["8",0]},"class_type":"SaveImage"}}}}' https://api.runpod.ai/v2/<endpoint_id>/runsync

# Response with AWS S3 bucket configuration
# {"delayTime":2188,"executionTime":2297,"id":"sync-c0cd1eb2-068f-4ecf-a99a-55770fc77391-e1","output":{"message":"https://bucket.s3.region.amazonaws.com/10-23/sync-c0cd1eb2-068f-4ecf-a99a-55770fc77391-e1/c67ad621.png","status":"success"},"status":"COMPLETED"}

# Response as base64-encoded image
# {"delayTime":2188,"executionTime":2297,"id":"sync-c0cd1eb2-068f-4ecf-a99a-55770fc77391-e1","output":{"message":"base64encodedimage","status":"success"},"status":"COMPLETED"}
```

## How to get the workflow from ComfyUI?

- Open ComfyUI in the browser
- Open the `Settings` (gear icon in the top right of the menu)
- In the dialog that appears configure:
  - `Enable Dev mode Options`: enable
  - Close the `Settings`
- In the menu, click on the `Save (API Format)` button, which will download a file named `workflow_api.json`

You can now take the content of this file and put it into your `workflow` when interacting with the API.

## Build the image

You can build the image locally: `docker build -t timpietruskyblibla/runpod-worker-comfy:dev --platform linux/amd64 .`

🚨 It's important to specify the `--platform linux/amd64`, otherwise you will get an error on RunPod, see [#13](https://github.com/blib-la/runpod-worker-comfy/issues/13)

## Local testing

Both tests will use the data from [test_input.json](./test_input.json), so make your changes in there to test this properly.

### Setup

- Make sure you have Python >= 3.10
- Create a virtual environment: `python -m venv venv`
- Activate the virtual environment: `.\venv\Scripts\activate` (Windows) or `source ./venv/bin/activate` (Mac / Linux)
- Install the dependencies: `pip install -r requirements.txt`

#### Setup for Windows

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

### Test: handler

- Run all tests: `python -m unittest discover`
- If you want to run a specific test: `python -m unittest tests.test_rp_handler.TestRunpodWorkerComfy.test_bucket_endpoint_not_configured`

You can also start the handler itself to have the local server running: `python src/rp_handler.py`
To get this to work you will also need to start "ComfyUI", otherwise the handler will not work.

### Local API

For enhanced local development, you can start an API server that simulates the RunPod worker environment. This feature is particularly useful for debugging and testing your integrations locally.

#### Starting local endpoint

Set the `SERVE_API_LOCALLY` environment variable to `true` to activate the local API server when running your Docker container. This is already the default value in the `docker-compose.yml`, so you can get it runnig by executing:

```bash
docker-compose up
```

#### Accessing the API

- With the local API server running, it's accessible at: [http://localhost:8000](http://localhost:8000)
- When you open this in your browser, you can also see the API documentation and can interact with the API directly

## Automatically deploy to Docker hub with Github Actions

The repo contains two workflows that publish the image to Docker hub using Github Actions:

- [docker-dev.yml](.github/workflows/docker-dev.yml): Creates the image and pushes it to Docker hub with the `dev` tag on every push to the `main` branch
- [docker-release.yml](.github/workflows/docker-release.yml): Creates the image and pushes it to Docker hub with the `latest` and the release tag. It will only be triggered when you create a release on GitHub

If you want to use this, you should add these secrets to your repository:

| Configuration Variable | Description                                                  | Example Value         |
| ---------------------- | ------------------------------------------------------------ | --------------------- |
| `DOCKERHUB_USERNAME`   | Your Docker Hub username.                                    | `your-username`       |
| `DOCKERHUB_TOKEN`      | Your Docker Hub token for authentication.                    | `your-token`          |
| `DOCKERHUB_REPO`       | The repository on Docker Hub where the image will be pushed. | `timpietruskyblibla`  |
| `DOCKERHUB_IMG`        | The name of the image to be pushed to Docker Hub.            | `runpod-worker-comfy` |

## Acknowledgments

- Thanks to [all contributors](https://github.com/blib-la/runpod-worker-comfy/graphs/contributors) for your awesome work
- Thanks to [Justin Merrell](https://github.com/justinmerrell) from RunPod for [worker-1111](https://github.com/runpod-workers/worker-a1111), which was used to get inspired on how to create this worker
- Thanks to [Ashley Kleynhans](https://github.com/ashleykleynhans) for [runpod-worker-a1111](https://github.com/ashleykleynhans/runpod-worker-a1111), which was used to get inspired on how to create this worker
- Thanks to [comfyanonymous](https://github.com/comfyanonymous) for creating [ComfyUI](https://github.com/comfyanonymous/ComfyUI), which provides such an awesome API to interact with Stable Diffusion
