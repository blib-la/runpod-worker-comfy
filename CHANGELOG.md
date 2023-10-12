#  (2023-10-12)


### Bug Fixes

* don't run ntpdate as this is not working in GitHub Actions ([2f7bd3f](https://github.com/blib-la/runpod-worker-comfy/commit/2f7bd3f71f24dd3b6ecc56f3a4c27bbc2d140eca))
* got rid of syntax error ([c04de4d](https://github.com/blib-la/runpod-worker-comfy/commit/c04de4dea93dbe586a9a887e04907b33597ff73e))
* updated path to "comfyui" ([37f66d0](https://github.com/blib-la/runpod-worker-comfy/commit/37f66d04b8c98810714ffbc761412f3fcdb1d861))


### Features

* added default ComfyUI workflow ([fa6c385](https://github.com/blib-la/runpod-worker-comfy/commit/fa6c385e0dc9487655b42772bb6f3a5f5218864e))
* added runpod as local dependency ([9deae9f](https://github.com/blib-la/runpod-worker-comfy/commit/9deae9f5ec723b93540e6e2deac04b8650cf872a))
* example on how to configure the .env ([4ed5296](https://github.com/blib-la/runpod-worker-comfy/commit/4ed529601394e8a105d171ab1274737392da7df5))
* logs should be written to stdout so that we can see them inside the worker ([fc731ff](https://github.com/blib-la/runpod-worker-comfy/commit/fc731fffcd79af67cf6fcdf6a6d3df6b8e30c7b5))
* simplified input ([35c2341](https://github.com/blib-la/runpod-worker-comfy/commit/35c2341deca346d4e6df82c36e101b7495f3fc03))
* simplified input to just have "prompt", removed unused code ([0c3ccda](https://github.com/blib-la/runpod-worker-comfy/commit/0c3ccda9c5c8cdc56eae829bb358ceb532b36371))
* updated path to "comfyui", added "ntpdate" to have the time of the container in sync with AWS ([2fda578](https://github.com/blib-la/runpod-worker-comfy/commit/2fda578d62460275abec11d6b2fbe5123d621d5f))
* use local ".env" to load env variables, mount "comfyui/output" to localhost so that people can see the generated images ([aa645a2](https://github.com/blib-la/runpod-worker-comfy/commit/aa645a233cd6951d296d68f7ddcf41b14b3f4cf9))
* use models from huggingface, not from local folder ([b1af369](https://github.com/blib-la/runpod-worker-comfy/commit/b1af369bb577c0aaba8875d8b2076e1888356929))
* wait until server is ready, wait until image generation is done, upload to s3 ([ecfec13](https://github.com/blib-la/runpod-worker-comfy/commit/ecfec1349da0d04ea5f21c82d8903e1a5bd3c923))



