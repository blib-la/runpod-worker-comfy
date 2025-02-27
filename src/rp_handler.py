import runpod
from runpod.serverless.utils import rp_upload
import json
import urllib.request
import urllib.parse
import time
import os
import requests
import base64
from io import BytesIO
import redis
from datetime import datetime
import logging
import uuid
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add ComfyUI directory to Python path
comfy_path = "/comfyui"
if comfy_path not in sys.path:
    sys.path.append(comfy_path)

# Redis configuration from environment variables
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
r = redis.Redis(
    host='redis-13524.fcrce180.us-east-1-1.ec2.redns.redis-cloud.com',
    port=13524,
    decode_responses=True,
    username="default",
    password="Z8w8yMLSTJ6HZqGUoIw4cnUsb36qQuWf",
)

# Time to wait between API check attempts in milliseconds
COMFY_API_AVAILABLE_INTERVAL_MS = 50
# Maximum number of API check attempts
COMFY_API_AVAILABLE_MAX_RETRIES = 500
# Time to wait between poll attempts in milliseconds
COMFY_POLLING_INTERVAL_MS = int(os.environ.get("COMFY_POLLING_INTERVAL_MS", 250))
# Maximum number of poll attempts
COMFY_POLLING_MAX_RETRIES = int(os.environ.get("COMFY_POLLING_MAX_RETRIES", 500))
# Host where ComfyUI is running
COMFY_HOST = "127.0.0.1:8188"
# Enforce a clean state after each job is done
REFRESH_WORKER = os.environ.get("REFRESH_WORKER", "false").lower() == "true"
FLUX = os.environ.get("FLUX", "false").lower() == "true"

def update_redis(job_id, state, workflow=None, result=None, error=None):
    """Update job state in Redis."""
    job = {
        "id": job_id,
        "state": state,
        "workflow": workflow if workflow is not None else {},
        "result": result,
        "error": error,
        "updated_at": datetime.utcnow().isoformat()
    }
    try:
        r.set(f"job:{job_id}", json.dumps(job))
        logger.info(f"Updated job {job_id} state to {state}")
    except Exception as e:
        logger.error(f"Failed to update Redis for job {job_id}: {str(e)}")

def validate_input(job_input):
    """Validates the input for the handler function."""
    if job_input is None:
        return None, "Please provide input"

    if isinstance(job_input, str):
        try:
            job_input = json.loads(job_input)
        except json.JSONDecodeError:
            return None, "Invalid JSON format in input"

    workflow = job_input.get("workflow")
    if workflow is None:
        return None, "Missing 'workflow' parameter"

    images = job_input.get("images")
    if images is not None:
        if not isinstance(images, list) or not all(
            "name" in image and "image" in image for image in images
        ):
            return None, "'images' must be a list of objects with 'name' and 'image' keys"
    
    # Validate loras parameter if provided
    loras = job_input.get("loras")
    if loras is not None:
        if not isinstance(loras, list) or not all(
            "path" in lora and "scale" in lora for lora in loras
        ):
            return None, "'loras' must be a list of objects with 'path' and 'scale' keys"

    return {"workflow": workflow, "images": images, "loras": loras}, None

def check_server(url, retries=500, delay=50):
    """Check if a server is reachable via HTTP GET request."""
    for i in range(retries):
        try:
            response = requests.get(url)
            if response.status_code == 200:
                logger.info("ComfyUI API is reachable")
                return True
        except requests.RequestException:
            pass
        time.sleep(delay / 1000)
    logger.error(f"Failed to connect to {url} after {retries} attempts")
    return False

def upload_images(images):
    """Upload a list of base64 encoded images to the ComfyUI server."""
    if not images:
        return {"status": "success", "message": "No images to upload", "details": []}

    responses = []
    upload_errors = []
    logger.info("Starting image upload")

    for image in images:
        name = image["name"]
        image_data = image["image"]
        blob = base64.b64decode(image_data)
        files = {
            "image": (name, BytesIO(blob), "image/png"),
            "overwrite": (None, "true"),
        }
        response = requests.post(f"http://{COMFY_HOST}/upload/image", files=files)
        if response.status_code != 200:
            upload_errors.append(f"Error uploading {name}: {response.text}")
        else:
            responses.append(f"Successfully uploaded {name}")

    if upload_errors:
        logger.error("Image upload completed with errors")
        return {
            "status": "error",
            "message": "Some images failed to upload",
            "details": upload_errors,
        }
    logger.info("Image upload completed successfully")
    return {
        "status": "success",
        "message": "All images uploaded successfully",
        "details": responses,
    }

def queue_workflow(workflow):
    """Queue a workflow to be processed by ComfyUI."""
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(f"http://{COMFY_HOST}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_history(prompt_id):
    """Retrieve the history of a given prompt using its ID."""
    with urllib.request.urlopen(f"http://{COMFY_HOST}/history/{prompt_id}") as response:
        return json.loads(response.read())

def base64_encode(img_path):
    """Returns base64 encoded image."""
    with open(img_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def process_output_images(outputs, job_id):
    """Process generated images and return as S3 URL or base64."""
    COMFY_OUTPUT_PATH = os.environ.get("COMFY_OUTPUT_PATH", "/comfyui/output")
    output_images = []

    for node_id, node_output in outputs.items():
        if "images" in node_output:
            for image in node_output["images"]:
                output_images.append(os.path.join(image["subfolder"], image["filename"]))

    logger.info("Image generation completed")
    processed_images = []

    for rel_path in output_images:
        local_image_path = f"{COMFY_OUTPUT_PATH}/{rel_path}"
        logger.info(f"Processing image at {local_image_path}")

        if os.path.exists(local_image_path):
            if os.environ.get("BUCKET_ENDPOINT_URL", False):
                image_result = rp_upload.upload_image(job_id, local_image_path)
                logger.info("Image uploaded to AWS S3")
            else:
                image_result = base64_encode(local_image_path)
                logger.info("Image converted to base64")
            processed_images.append(image_result)
        else:
            logger.error(f"Image not found at {local_image_path}")
            processed_images.append(f"Image not found: {local_image_path}")

    return {
        "status": "success",
        "message": processed_images,
    }

def verify_lora_files(lora_info):
    """Verify that downloaded lora files are accessible to ComfyUI.
    
    Args:
        lora_info: List of dictionaries with lora information
        
    Returns:
        bool: True if all files are accessible, False otherwise
    """
    try:
        # Import ComfyUI's folder_paths module to check lora paths
        import folder_paths
        
        # Get the lora folder paths from ComfyUI
        lora_folders = folder_paths.get_folder_paths("loras")
        logger.info(f"ComfyUI lora folders: {lora_folders}")
        
        # Check if our lora directory is in the ComfyUI lora folders
        our_lora_dir = "/runpod-volume/models/loras"
        if our_lora_dir not in lora_folders:
            logger.warning(f"Our lora directory {our_lora_dir} is not in ComfyUI's lora folders")
            # Try to add it to ComfyUI's folder paths
            folder_paths.add_model_folder_path("loras", our_lora_dir)
            logger.info(f"Added {our_lora_dir} to ComfyUI's lora folders")
            
            # Verify it was added
            lora_folders = folder_paths.get_folder_paths("loras")
            if our_lora_dir not in lora_folders:
                logger.error(f"Failed to add {our_lora_dir} to ComfyUI's lora folders")
                return False
        
        # Check if each downloaded lora file exists and is accessible
        for lora in lora_info:
            if lora.get("downloaded", False):
                lora_path = lora.get("path")
                if not os.path.exists(lora_path):
                    logger.error(f"Downloaded lora file does not exist: {lora_path}")
                    return False
                
                # Check if the file is readable
                try:
                    with open(lora_path, 'rb') as f:
                        # Just read a small chunk to verify access
                        f.read(1024)
                    logger.info(f"Verified access to lora file: {lora_path}")
                except Exception as e:
                    logger.error(f"Cannot read lora file {lora_path}: {str(e)}")
                    return False
        
        return True
    except Exception as e:
        logger.error(f"Error verifying lora files: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def handler(job):
    """Main handler for processing a job."""
    job_id = job.get("id", str(uuid.uuid4()))  # Use provided job ID or generate one
    job_input = job["input"]
    lora_file_paths = []  # Track downloaded lora files for cleanup

    # Validate input
    validated_data, error_message = validate_input(job_input)
    if error_message:
        update_redis(job_id, "FAILED", error=error_message)
        return {"error": error_message, "job_id": job_id}

    workflow = validated_data["workflow"]
    images = validated_data.get("images")
    loras = validated_data.get("loras")

    # Write initial state to Redis
    update_redis(job_id, "NOT_STARTED", workflow=workflow)

    # Check ComfyUI availability
    if not check_server(f"http://{COMFY_HOST}", COMFY_API_AVAILABLE_MAX_RETRIES, COMFY_API_AVAILABLE_INTERVAL_MS):
        error = "ComfyUI API unavailable"
        update_redis(job_id, "FAILED", error=error)
        return {"error": error, "job_id": job_id}

    # Upload images if provided
    upload_result = upload_images(images)
    if upload_result["status"] == "error":
        update_redis(job_id, "FAILED", error=upload_result["message"])
        return {**upload_result, "job_id": job_id}
    
    # Process loras if provided
    if loras:
        logger.info(f"Processing {len(loras)} loras")
        update_redis(job_id, "PROCESSING_LORAS")
        lora_result = download_lora_files(loras)
        lora_file_paths = lora_result.get("file_paths", [])
        lora_info = lora_result.get("lora_info", [])
        
        if lora_result["status"] == "error":
            # Continue even if some files failed, but log the errors
            logger.warning(f"Some loras failed to download: {lora_result['details']}")
            update_redis(job_id, "LORA_PROCESSING_PARTIAL", error=lora_result["message"])
        else:
            logger.info("All network loras processed successfully")
            update_redis(job_id, "LORA_PROCESSING_COMPLETE")
        
        # Verify lora files are accessible to ComfyUI
        if lora_info:
            if not verify_lora_files(lora_info):
                logger.warning("Some lora files may not be accessible to ComfyUI")
                update_redis(job_id, "LORA_VERIFICATION_WARNING", error="Some lora files may not be accessible to ComfyUI")
            else:
                logger.info("All lora files are accessible to ComfyUI")
        
        # Update workflow with local paths for downloaded loras
        if lora_info:
            logger.info("Updating workflow with local lora paths")
            try:
                # Check if this is a FLUX workflow by looking for specific node types
                is_flux_workflow = False
                workflow_str = json.dumps(workflow)
                
                if '"class_type": "DualCLIPLoader"' in workflow_str and '"class_type": "UNETLoader"' in workflow_str:
                    is_flux_workflow = True
                    logger.info("Detected FLUX workflow structure")
                
                if is_flux_workflow:
                    # For FLUX workflows, we need to update the LoraLoader nodes
                    for node_id, node in workflow.items():
                        if node.get("class_type") == "LoraLoader":
                            node_lora_name = node["inputs"].get("lora_name", "")
                            logger.info(f"Processing LoraLoader node {node_id} with lora_name: {node_lora_name}")
                            
                            # Find the corresponding lora in our downloaded list
                            for lora in lora_info:
                                if lora.get("downloaded", False):
                                    original_path = lora.get("original_path", "")
                                    original_filename = os.path.basename(original_path)
                                    
                                    # Check various matching conditions
                                    if (node_lora_name == original_path or  # Full path match
                                        node_lora_name == original_filename or  # Filename match
                                        os.path.basename(node_lora_name) == original_filename):  # Basename match
                                        
                                        # Update to use the local path's filename
                                        node["inputs"]["lora_name"] = lora.get("lora_name")
                                        logger.info(f"Updated LoraLoader node {node_id} to use {lora.get('lora_name')}")
                                        break
                else:
                    # For standard workflows, do a simple string replacement
                    path_mapping = {}
                    for lora in lora_info:
                        if lora.get("downloaded", False):
                            path_mapping[lora["original_path"]] = lora["path"]
                            # Also map the filename for cases where only the filename is used
                            filename = os.path.basename(lora["original_path"])
                            if filename:
                                path_mapping[filename] = os.path.basename(lora["path"])
                    
                    # Update the workflow
                    workflow_str = json.dumps(workflow)
                    for original_path, local_path in path_mapping.items():
                        workflow_str = workflow_str.replace(f'"{original_path}"', f'"{local_path}"')
                    workflow = json.loads(workflow_str)
                
                logger.info("Successfully updated workflow with local lora paths")
            except Exception as e:
                logger.error(f"Error updating workflow with local lora paths: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                # Continue with the original workflow

    # Queue the workflow
    try:
        update_redis(job_id, "IN_QUEUE")
        queued_workflow = queue_workflow(workflow)
        prompt_id = queued_workflow["prompt_id"]
        logger.info(f"Queued workflow with prompt ID {prompt_id}")
    except Exception as e:
        error = f"Error queuing workflow: {str(e)}"
        update_redis(job_id, "FAILED", error=error)
        
        # Clean up lora files if any were downloaded
        if lora_file_paths:
            cleanup_result = cleanup_lora_files(lora_file_paths)
            logger.info(f"Cleaned up lora files after error: {cleanup_result['message']}")
            
        return {"error": error, "job_id": job_id}

    # Poll for completion
    logger.info("Polling for image generation completion")
    retries = 0
    try:
        while retries < COMFY_POLLING_MAX_RETRIES:
            history = get_history(prompt_id)
            if prompt_id in history and history[prompt_id].get("outputs"):
                break
            time.sleep(COMFY_POLLING_INTERVAL_MS / 1000)
            retries += 1
        else:
            error = "Max retries reached while waiting for image generation"
            update_redis(job_id, "FAILED", error=error)
            
            # Clean up lora files if any were downloaded
            if lora_file_paths:
                cleanup_result = cleanup_lora_files(lora_file_paths)
                logger.info(f"Cleaned up lora files after timeout: {cleanup_result['message']}")
                
            return {"error": error, "job_id": job_id}
    except Exception as e:
        error = f"Error polling for image generation: {str(e)}"
        update_redis(job_id, "FAILED", error=error)
        
        # Clean up lora files if any were downloaded
        if lora_file_paths:
            cleanup_result = cleanup_lora_files(lora_file_paths)
            logger.info(f"Cleaned up lora files after polling error: {cleanup_result['message']}")
            
        return {"error": error, "job_id": job_id}

    # Process output images
    images_result = process_output_images(history[prompt_id].get("outputs"), job_id)
    
    # Clean up lora files if any were downloaded
    cleanup_info = {}
    if lora_file_paths:
        cleanup_result = cleanup_lora_files(lora_file_paths)
        logger.info(f"Cleaned up lora files after successful inference: {cleanup_result['message']}")
        cleanup_info = {
            "lora_cleanup": cleanup_result["status"],
            "lora_cleanup_details": cleanup_result.get("details", [])
        }
    
    if images_result["status"] == "success":
        update_redis(job_id, "COMPLETED", result=images_result["message"])
    else:
        update_redis(job_id, "FAILED", error="Image processing failed")

    return {
        "job_id": job_id,
        "status": images_result["status"],
        "message": images_result["message"],
        "refresh_worker": REFRESH_WORKER,
        **cleanup_info
    }

def preload_weights(checkpoint_name):
    try:
        # Import ComfyUI modules after adding to path
        from comfy.sd import load_checkpoint_guess_config
        import folder_paths
        
        # Load the model
        logger.info(f"Attempting to preload: {checkpoint_name}")
        
        # Special case for FLUX models which have a different structure
        if checkpoint_name == "flux1-dev.safetensors":
            logger.info("FLUX model detected, using specialized loading approach")
            
            # Load UNet
            unet_path = os.path.join('runpod-volume/models/unet', checkpoint_name)
            if not os.path.exists(unet_path):
                logger.error(f"FLUX UNet model not found at: {unet_path}")
                return None
            logger.info(f"Found FLUX UNet model at: {unet_path}")
            
            # Load VAE
            vae_path = os.path.join('runpod-volume/models/vae', 'ae.safetensors')
            if not os.path.exists(vae_path):
                logger.error(f"FLUX VAE model not found at: {vae_path}")
                return None
            logger.info(f"Found FLUX VAE model at: {vae_path}")
            
            # Load CLIP models
            clip_l_path = os.path.join('runpod-volume/models/clip', 'clip_l.safetensors')
            t5_path = os.path.join('runpod-volume/models/clip', 't5xxl_fp8_e4m3fn.safetensors')
            if not os.path.exists(clip_l_path):
                logger.error(f"FLUX CLIP_L model not found at: {clip_l_path}")
                return None
            if not os.path.exists(t5_path):
                logger.error(f"FLUX T5 model not found at: {t5_path}")
                return None
            logger.info(f"Found FLUX CLIP models at: {clip_l_path} and {t5_path}")
            
            # Try to load the components using load_checkpoint_guess_config
            unet_model = None
            vae_model = None
            clip_model = None
            
            try:
                # Load UNet
                logger.info(f"Attempting to load FLUX UNet with load_checkpoint_guess_config: {unet_path}")
                unet_model = load_checkpoint_guess_config(
                    unet_path,
                    output_vae=False,
                    output_clip=False
                )
                logger.info(f"Successfully loaded FLUX UNet: {type(unet_model)}")
            except Exception as e:
                logger.error(f"Error loading FLUX UNet: {str(e)}")
            
            try:
                # Load VAE
                logger.info(f"Attempting to load FLUX VAE: {vae_path}")
                vae_model = load_checkpoint_guess_config(
                    vae_path,
                    output_vae=True,
                    output_clip=False
                )
                logger.info(f"Successfully loaded FLUX VAE: {type(vae_model)}")
            except Exception as e:
                logger.error(f"Error loading FLUX VAE: {str(e)}")
            
            try:
                # Load CLIP models
                logger.info(f"Attempting to load FLUX CLIP models")
                # Import CLIP loading function
                from comfy.sd import load_clip
                
                # Try loading CLIP_L
                logger.info(f"Loading CLIP_L model: {clip_l_path}")
                clip_model = load_clip(clip_l_path, None)
                logger.info(f"Successfully loaded CLIP_L: {type(clip_model)}")
                
                # Note: T5 model might require special handling and may not load with standard functions
                # ComfyUI will handle loading it when needed
                logger.info(f"T5 model will be loaded by ComfyUI when needed")
            except Exception as e:
                logger.error(f"Error loading CLIP models: {str(e)}")
            
            # Check if we loaded at least some components
            if unet_model is not None or vae_model is not None or clip_model is not None:
                logger.info(f"Successfully preloaded some FLUX model components")
                return unet_model, clip_model, vae_model
            else:
                logger.warning("Failed to preload any FLUX model components")
                logger.info("FLUX models will be loaded by ComfyUI when needed")
                return "FLUX_MODEL_PLACEHOLDER"
        else:
            # Use the exact path to the model in the RunPod volume
            model_path = os.path.join('runpod-volume/models/checkpoints', checkpoint_name)
            
            if not os.path.exists(model_path):
                logger.error(f"Model file not found at: {model_path}")
                return None
            
            logger.info(f"Found model at: {model_path}")
            
            # Get the embedding directory from ComfyUI's folder_paths
            embedding_directory = None
            try:
                embedding_directory = folder_paths.get_folder_paths("embeddings")
                logger.info(f"Embedding directory: {embedding_directory}")
            except Exception as e:
                logger.warning(f"Could not get embedding directory: {str(e)}")
            
            # Call the function with the correct arguments as used in ComfyUI
            logger.info(f"Calling load_checkpoint_guess_config with path: {model_path}")
            result = load_checkpoint_guess_config(
                model_path, 
                output_vae=True, 
                output_clip=True, 
                embedding_directory=embedding_directory
            )
            
            # Log the type of result to help with debugging
            logger.info(f"Result type: {type(result)}")
            
            if isinstance(result, tuple):
                logger.info(f"Result has {len(result)} elements")
                # If it's a tuple, it might be (model, clip, vae) or (model, clip, vae, ...)
                if len(result) >= 3:
                    model, clip, vae = result[:3]
                    logger.info(f"Successfully preloaded: {checkpoint_name}")
                    return model, clip, vae
                else:
                    logger.error(f"Not enough values returned: expected at least 3, got {len(result)}")
                    return None
            else:
                # If it's not a tuple, it might be a single model object
                logger.info(f"Result is not a tuple, treating as single model object")
                return result, None, None
        
    except Exception as e:
        logger.error(f"Error preloading model {checkpoint_name}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def init():
    """Initialize the handler."""
    # Wait for ComfyUI to start up
    logger.info("Waiting for ComfyUI to initialize...")
    time.sleep(15)  # Give ComfyUI time to start
    
    # Check if models directory exists
    model_dir = 'runpod-volume/models/checkpoints'
    if os.path.exists(model_dir):
        logger.info(f"Model directory exists: {model_dir}")
        try:
            models = os.listdir(model_dir)
            logger.info(f"Available models: {models}")
        except Exception as e:
            logger.error(f"Error listing models: {str(e)}")
    else:
        logger.warning(f"Model directory does not exist: {model_dir}")
    
    # Check if FLUX is enabled, also check the required directories for FLUX models
    if FLUX:
        # Check for UNet model
        unet_dir = 'runpod-volume/models/unet'
        if os.path.exists(unet_dir):
            logger.info(f"Unet directory exists: {unet_dir}")
            try:
                unet_models = os.listdir(unet_dir)
                logger.info(f"Available unet models: {unet_models}")
                if "flux1-dev.safetensors" not in unet_models:
                    logger.warning("flux1-dev.safetensors not found in unet directory")
            except Exception as e:
                logger.error(f"Error listing unet models: {str(e)}")
        else:
            logger.warning(f"Unet directory does not exist: {unet_dir}")
        
        # Check for CLIP models
        clip_dir = 'runpod-volume/models/clip'
        if os.path.exists(clip_dir):
            logger.info(f"CLIP directory exists: {clip_dir}")
            try:
                clip_models = os.listdir(clip_dir)
                logger.info(f"Available CLIP models: {clip_models}")
                required_clip_models = ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"]
                for model in required_clip_models:
                    if model not in clip_models:
                        logger.warning(f"{model} not found in CLIP directory")
            except Exception as e:
                logger.error(f"Error listing CLIP models: {str(e)}")
        else:
            logger.warning(f"CLIP directory does not exist: {clip_dir}")
        
        # Check for VAE model
        vae_dir = 'runpod-volume/models/vae'
        if os.path.exists(vae_dir):
            logger.info(f"VAE directory exists: {vae_dir}")
            try:
                vae_models = os.listdir(vae_dir)
                logger.info(f"Available VAE models: {vae_models}")
                if "ae.safetensors" not in vae_models:
                    logger.warning("ae.safetensors not found in VAE directory")
            except Exception as e:
                logger.error(f"Error listing VAE models: {str(e)}")
        else:
            logger.warning(f"VAE directory does not exist: {vae_dir}")
    
    # Models to preload
    models_to_preload = [
        "realvisxlV40_v40LightningBakedvae.safetensors",
        "pixelArtDiffusionXL_pixelWorld.safetensors"
    ]

    # Check if FLUX environment variable is set to true
    if FLUX:
        models_to_preload.append("flux1-dev.safetensors")
        logger.info("FLUX environment variable is set to true, adding flux1-dev.safetensors to preload list")
    
    # Preload models
    preloaded = []
    for checkpoint_name in models_to_preload:
        try:
            result = preload_weights(checkpoint_name)
            if result is not None:
                preloaded.append(checkpoint_name)
                logger.info(f"Successfully preloaded: {checkpoint_name}")
        except Exception as e:
            logger.error(f"Failed to preload {checkpoint_name}: {str(e)}")
    
    logger.info(f"Preloaded {len(preloaded)} models: {preloaded}")

def download_lora_files(loras):
    """Download lora files from network paths to disk.
    
    Args:
        loras: List of dictionaries with 'path' and 'scale' keys
        
    Returns:
        dict: Status of download operation with downloaded file paths and lora info
    """
    if not loras:
        return {"status": "success", "message": "No loras to process", "details": [], "file_paths": [], "lora_info": []}
    
    LORA_DIR = "/runpod-volume/models/loras"
    os.makedirs(LORA_DIR, exist_ok=True)
    
    responses = []
    download_errors = []
    file_paths = []
    lora_info = []  # Store info about all loras (both local and downloaded)
    
    logger.info(f"Processing {len(loras)} loras")
    
    for lora in loras:
        path = lora["path"]
        scale = lora["scale"]
        
        # Check if the lora is a network path (http or https)
        if path.startswith(("http://", "https://")):
            # Extract filename from URL
            filename = os.path.basename(path)
            if not filename:
                # Generate a random filename if URL doesn't have one
                filename = f"lora_{uuid.uuid4().hex}.safetensors"
            elif not filename.endswith('.safetensors'):
                filename = f"{filename}.safetensors"
                
            local_path = os.path.join(LORA_DIR, filename)
            file_paths.append(local_path)
            
            try:
                # Download the file
                logger.info(f"Downloading lora from {path} to {local_path}")
                response = requests.get(path, stream=True)
                response.raise_for_status()
                
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                responses.append(f"Successfully downloaded lora from {path}")
                logger.info(f"Successfully downloaded lora from {path}")
                
                # Add to lora info with local path
                lora_info.append({
                    "path": local_path,
                    "scale": scale,
                    "original_path": path,
                    "downloaded": True,
                    "lora_name": filename  # Add lora_name for ComfyUI workflow
                })
            except Exception as e:
                error_msg = f"Error downloading lora from {path}: {str(e)}"
                download_errors.append(error_msg)
                logger.error(error_msg)
                
                # Still add to lora info but with original path
                lora_info.append({
                    "path": path,
                    "scale": scale,
                    "download_error": str(e),
                    "downloaded": False
                })
        else:
            # Local path, no need to download
            filename = os.path.basename(path)
            logger.info(f"Using local lora at {path}")
            lora_info.append({
                "path": path,
                "scale": scale,
                "downloaded": False,
                "lora_name": filename  # Add lora_name for ComfyUI workflow
            })
    
    if download_errors:
        logger.error("Lora download completed with errors")
        return {
            "status": "error",
            "message": "Some loras failed to download",
            "details": download_errors,
            "file_paths": file_paths,
            "lora_info": lora_info
        }
    
    logger.info("Lora processing completed successfully")
    return {
        "status": "success",
        "message": "All network loras downloaded successfully",
        "details": responses,
        "file_paths": file_paths,
        "lora_info": lora_info
    }

def cleanup_lora_files(file_paths):
    """Delete downloaded lora files after inference is complete.
    
    Args:
        file_paths: List of file paths to delete
        
    Returns:
        dict: Status of cleanup operation
    """
    if not file_paths:
        return {"status": "success", "message": "No lora files to clean up"}
    
    cleanup_errors = []
    deleted_files = []
    
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_files.append(file_path)
                logger.info(f"Successfully deleted lora file: {file_path}")
        except Exception as e:
            error_msg = f"Error deleting {file_path}: {str(e)}"
            cleanup_errors.append(error_msg)
            logger.error(error_msg)
    
    if cleanup_errors:
        return {
            "status": "warning",
            "message": "Some lora files could not be deleted",
            "details": cleanup_errors,
            "deleted_files": deleted_files
        }
    
    return {
        "status": "success",
        "message": "All lora files cleaned up successfully",
        "details": deleted_files
    }

# Only initialize if this module is the main program
if __name__ == "__main__":
    # Initialize after a delay to ensure ComfyUI is running
    import threading
    threading.Timer(5.0, init).start()
    
    # Start the handler
    logger.info("Starting RunPod handler")
    runpod.serverless.start({"handler": handler})
else:
    # If imported as a module, don't run init() immediately
    logger.info("rp_handler module imported, initialization will be handled by main process")