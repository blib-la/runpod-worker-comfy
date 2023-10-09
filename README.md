# RunPod Worker Comfy

> ComfyUI via API on [RunPod](https://www.runpod.io/) serverless

<!-- toc -->

- [What](#what)

<!-- tocstop -->

---

## What

* Use ubuntu with cuda driver as base
* make sure to set the correct options as with a1111 from ashley
* clone comfy & install dependencies
* create a start.sh script to start comfy and then the handler
* use the start.sh as the entrypoint in the dockerfile
* create a loop to create the image
* store hte generated image in S3
* return the URL to the image via API
* use the network volume
