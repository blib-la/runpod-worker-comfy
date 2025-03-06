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
from datetime import datetime, timedelta
import logging
import uuid
import sys
import traceback
from typing import Dict, List, Tuple, Any, Optional, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] [%(levelname)s] [%(job_id)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add a filter to include job_id in log records
class JobIdFilter(logging.Filter):
    """Filter that adds job_id to log records."""
    
    def __init__(self, name=''):
        super().__init__(name)
        self.job_id = 'no_job'
    
    def set_job_id(self, job_id):
        """Set the current job ID."""
        self.job_id = job_id
    
    def filter(self, record):
        """Add job_id to the log record."""
        if not hasattr(record, 'job_id'):
            record.job_id = self.job_id
        return True

# Create and add the filter to the logger
job_id_filter = JobIdFilter()
logger.addFilter(job_id_filter)

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
    # Set job ID for logging
    job_id_filter.set_job_id(job_id)
    
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
        logger.info(f"Updated job state to {state}")
    except Exception as e:
        logger.error(f"Failed to update Redis: {str(e)}")

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
    
    # Get optional webhook URL
    webhook_url = job_input.get("webhookUrl")
    if webhook_url is not None and not isinstance(webhook_url, str):
        return None, "'webhookUrl' must be a string"

    return {"workflow": workflow, "images": images, "loras": loras, "webhook_url": webhook_url}, None

def check_server(url, retries=500, delay=50, job_id=None):
    """Check if ComfyUI API is available.
    
    Args:
        url: URL to check
        retries: Number of retries
        delay: Delay between retries in milliseconds
        job_id: ID of the job for logging
        
    Returns:
        bool: True if API is available, False otherwise
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
    for _ in range(retries):
        try:
            response = requests.get(f"{url}/system_stats", timeout=5)
            if response.status_code == 200:
                logger.info("ComfyUI API is reachable")
                return True
        except:
            pass
        time.sleep(delay / 1000)
    
    logger.error(f"Failed to connect to {url} after {retries} attempts")
    return False

def upload_images(images, job_id=None):
    """Upload images to ComfyUI.
    
    Args:
        images: List of image data (base64 or URLs)
        job_id: ID of the job for logging
        
    Returns:
        dict: Status of upload operation
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
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

def queue_workflow(workflow, job_id=None):
    """Queue a workflow in ComfyUI.
    
    Args:
        workflow: Workflow to queue
        job_id: ID of the job for logging
        
    Returns:
        dict: Response from ComfyUI API
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
    response = requests.post(f"http://{COMFY_HOST}/prompt", json=workflow)
    response.raise_for_status()
    return response.json()

def get_history(prompt_id, job_id=None):
    """Get history for a prompt from ComfyUI.
    
    Args:
        prompt_id: ID of the prompt
        job_id: ID of the job for logging
        
    Returns:
        dict: History from ComfyUI API
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
    response = requests.get(f"http://{COMFY_HOST}/history/{prompt_id}")
    response.raise_for_status()
    return response.json()

def base64_encode(img_path):
    """Returns base64 encoded image."""
    with open(img_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def process_output_images(outputs, job_id):
    """Process output images from ComfyUI.
    
    Args:
        outputs: Dictionary of outputs from ComfyUI
        job_id: ID of the job
        
    Returns:
        dict: Status of processing with image URLs
    """
    # Set job ID for logging
    job_id_filter.set_job_id(job_id)
    
    if not outputs:
        return {"status": "error", "message": "No outputs found"}

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

def verify_lora_files(lora_info, job_id=None):
    """Verify that lora files are accessible to ComfyUI.
    
    Args:
        lora_info: List of dictionaries with lora information
        job_id: ID of the job for logging
        
    Returns:
        bool: True if all lora files are accessible, False otherwise
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
    if not lora_info:
        return True

    try:
        # Import ComfyUI's folder_paths module to check lora paths
        import folder_paths
        
        # Get the lora folder paths from ComfyUI
        lora_folders = folder_paths.get_folder_paths("loras")
        logger.info(f"ComfyUI lora folders: {lora_folders}")
        
        # Check which lora directory exists and use that
        LORA_DIRS = [
            "/runpod-volume/models/loras",
            "/workspace/models/loras"
        ]
        
        our_lora_dirs = []
        for dir_path in LORA_DIRS:
            if os.path.exists(dir_path):
                our_lora_dirs.append(dir_path)
                logger.info(f"Found lora directory: {dir_path}")
        
        if not our_lora_dirs:
            logger.warning("No lora directories found")
            return False
        
        # Check if our lora directories are in ComfyUI's lora folders
        for our_lora_dir in our_lora_dirs:
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
                    
                    # Check if the file exists in the other lora directory
                    filename = os.path.basename(lora_path)
                    found = False
                    for our_lora_dir in our_lora_dirs:
                        if our_lora_dir not in lora_path:  # Check if it's a different directory
                            alt_path = os.path.join(our_lora_dir, filename)
                            if os.path.exists(alt_path):
                                logger.info(f"Found lora file in alternate location: {alt_path}")
                                lora["path"] = alt_path  # Update the path
                                found = True
                                break
                    
                    if not found:
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
    
    # Set job ID for logging
    job_id_filter.set_job_id(job_id)
    
    job_input = job["input"]
    lora_file_paths = []  # Track downloaded lora files for cleanup
    start_time = datetime.utcnow().isoformat()

    # Validate input
    validated_data, error_message = validate_input(job_input)
    if error_message:
        update_redis(job_id, "FAILED", error=error_message)
        return {"error": error_message, "job_id": job_id}

    workflow = validated_data["workflow"]
    images = validated_data.get("images")
    loras = validated_data.get("loras")
    webhook_url = validated_data.get("webhook_url")

    # Write initial state to Redis
    update_redis(job_id, "NOT_STARTED", workflow=workflow)

    # Check ComfyUI availability
    if not check_server(f"http://{COMFY_HOST}", COMFY_API_AVAILABLE_MAX_RETRIES, COMFY_API_AVAILABLE_INTERVAL_MS, job_id):
        error = "ComfyUI API unavailable"
        update_redis(job_id, "FAILED", error=error)
        
        # Call webhook with error if provided
        if webhook_url:
            call_webhook(webhook_url, job_id, "error", error=error, additional_data={
                "start_time": start_time,
                "end_time": datetime.utcnow().isoformat(),
                "error_type": "comfy_unavailable"
            })
            
        return {"error": error, "job_id": job_id}

    # Upload images if provided
    upload_result = upload_images(images, job_id)
    if upload_result["status"] == "error":
        update_redis(job_id, "FAILED", error=upload_result["message"])
        
        # Call webhook with error if provided
        if webhook_url:
            call_webhook(webhook_url, job_id, "error", error=upload_result["message"], additional_data={
                "start_time": start_time,
                "end_time": datetime.utcnow().isoformat(),
                "error_type": "image_upload_failed",
                "upload_details": upload_result.get("details", [])
            })
            
        return {**upload_result, "job_id": job_id}
    
    # Process loras if provided
    lora_info = []
    if loras:
        logger.info(f"Processing {len(loras)} loras")
        update_redis(job_id, "PROCESSING_LORAS")
        lora_result = download_lora_files(loras, job_id)
        
        # Only track paths of downloaded loras, not local ones
        lora_file_paths = lora_result.get("file_paths", [])
        logger.info(f"Tracking {len(lora_file_paths)} downloaded lora files for cleanup: {lora_file_paths}")
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
            if not verify_lora_files(lora_info, job_id):
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
        queued_workflow = queue_workflow(workflow, job_id)
        prompt_id = queued_workflow["prompt_id"]
        logger.info(f"Queued workflow with prompt ID {prompt_id}")
    except Exception as e:
        error = f"Error queuing workflow: {str(e)}"
        update_redis(job_id, "FAILED", error=error)
        
        # Clean up lora files if any were downloaded
        if lora_file_paths:
            cleanup_result = cleanup_lora_files(lora_file_paths, job_id)
            logger.info(f"Cleaned up lora files after error: {cleanup_result['message']}")
            logger.info(f"Deleted {len(cleanup_result.get('details', []))} files, skipped {len(cleanup_result.get('skipped_files', []))} files")
        
        # Call webhook with error if provided
        if webhook_url:
            call_webhook(webhook_url, job_id, "error", error=error, additional_data={
                "start_time": start_time,
                "end_time": datetime.utcnow().isoformat(),
                "error_type": "workflow_queue_failed",
                "lora_count": len(lora_info) if lora_info else 0
            })
            
        return {"error": error, "job_id": job_id}

    # Poll for completion
    logger.info("Polling for image generation completion")
    retries = 0
    try:
        while retries < COMFY_POLLING_MAX_RETRIES:
            history = get_history(prompt_id, job_id)
            if prompt_id in history and history[prompt_id].get("outputs"):
                break
            time.sleep(COMFY_POLLING_INTERVAL_MS / 1000)
            retries += 1
        else:
            error = "Max retries reached while waiting for image generation"
            update_redis(job_id, "FAILED", error=error)
            
            # Clean up lora files if any were downloaded
            if lora_file_paths:
                cleanup_result = cleanup_lora_files(lora_file_paths, job_id)
                logger.info(f"Cleaned up lora files after timeout: {cleanup_result['message']}")
                logger.info(f"Deleted {len(cleanup_result.get('details', []))} files, skipped {len(cleanup_result.get('skipped_files', []))} files")
            
            # Call webhook with error if provided
            if webhook_url:
                call_webhook(webhook_url, job_id, "error", error=error, additional_data={
                    "start_time": start_time,
                    "end_time": datetime.utcnow().isoformat(),
                    "error_type": "generation_timeout",
                    "retries": retries,
                    "lora_count": len(lora_info) if lora_info else 0
                })
                
            return {"error": error, "job_id": job_id}
    except Exception as e:
        error = f"Error polling for image generation: {str(e)}"
        update_redis(job_id, "FAILED", error=error)
        
        # Clean up lora files if any were downloaded
        if lora_file_paths:
            cleanup_result = cleanup_lora_files(lora_file_paths, job_id)
            logger.info(f"Cleaned up lora files after polling error: {cleanup_result['message']}")
            logger.info(f"Deleted {len(cleanup_result.get('details', []))} files, skipped {len(cleanup_result.get('skipped_files', []))} files")
            
        # Call webhook with error if provided
        if webhook_url:
            call_webhook(webhook_url, job_id, "error", error=error, additional_data={
                "start_time": start_time,
                "end_time": datetime.utcnow().isoformat(),
                "error_type": "polling_error",
                "lora_count": len(lora_info) if lora_info else 0
            })
            
        return {"error": error, "job_id": job_id}

    # Process output images
    images_result = process_output_images(history[prompt_id].get("outputs"), job_id)
    
    # Clean up lora files if any were downloaded
    cleanup_info = {}
    if lora_file_paths:
        cleanup_result = cleanup_lora_files(lora_file_paths, job_id)
        logger.info(f"Cleaned up lora files after successful inference: {cleanup_result['message']}")
        logger.info(f"Deleted {len(cleanup_result.get('details', []))} files, skipped {len(cleanup_result.get('skipped_files', []))} files")
        cleanup_info = {
            "lora_cleanup": cleanup_result["status"],
            "lora_cleanup_details": cleanup_result.get("details", []),
            "lora_skipped_files": cleanup_result.get("skipped_files", [])
        }
    
    end_time = datetime.utcnow().isoformat()
    
    if images_result["status"] == "success":
        update_redis(job_id, "COMPLETED", result=images_result["message"])
        
        # Call webhook with success result if provided
        if webhook_url:
            # Prepare additional data for webhook
            additional_data = {
                "start_time": start_time,
                "end_time": end_time,
                "processing_time_seconds": (datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)).total_seconds(),
                "lora_count": len(lora_info) if lora_info else 0,
                "image_count": len(images_result.get("message", [])),
                "prompt_id": prompt_id
            }
            
            webhook_result = call_webhook(
                webhook_url, 
                job_id, 
                "success", 
                result=images_result["message"],
                additional_data=additional_data
            )
            cleanup_info["webhook_result"] = webhook_result
    else:
        update_redis(job_id, "FAILED", error="Image processing failed")
        
        # Call webhook with error if provided
        if webhook_url:
            webhook_result = call_webhook(
                webhook_url, 
                job_id, 
                "error", 
                error="Image processing failed",
                additional_data={
                    "start_time": start_time,
                    "end_time": end_time,
                    "error_type": "image_processing_failed",
                    "lora_count": len(lora_info) if lora_info else 0,
                    "prompt_id": prompt_id
                }
            )
            cleanup_info["webhook_result"] = webhook_result

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
    # Set a default job ID for initialization logs
    job_id_filter.set_job_id('init')
    
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

def download_lora_files(loras, job_id=None):
    """Download lora files from network paths to disk.
    
    Args:
        loras: List of dictionaries with 'path' and 'scale' keys
        job_id: ID of the job for logging
        
    Returns:
        dict: Status of download operation with downloaded file paths and lora info
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
    if not loras:
        return {"status": "success", "message": "No loras to process", "details": [], "file_paths": [], "lora_info": []}
    
    # Check which lora directory exists and use that
    LORA_DIRS = [
        "/runpod-volume/models/loras",
        "/workspace/models/loras"
    ]
    
    LORA_DIR = None
    for dir_path in LORA_DIRS:
        if os.path.exists(dir_path):
            LORA_DIR = dir_path
            logger.info(f"Using lora directory: {LORA_DIR}")
            break
    
    if LORA_DIR is None:
        # If neither exists, default to the first one and create it
        LORA_DIR = LORA_DIRS[0]
        logger.warning(f"No existing lora directory found, creating: {LORA_DIR}")
    
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
            
            # Check if the file already exists
            file_exists = os.path.exists(local_path)
            
            # Check if this is a protected model
            is_protected = is_protected_model(filename)
            
            if file_exists:
                logger.info(f"Lora file already exists: {local_path}")
                
                # Only add to file_paths for cleanup if it's not a protected model
                # (i.e., only if it has "pytorch_lora_weights" in the name)
                if not is_protected:
                    file_paths.append(local_path)
                    logger.info(f"Added existing lora path to file_paths for cleanup: {local_path}")
                else:
                    logger.info(f"Not adding protected model to cleanup list: {local_path}")
                
                # Add to lora info with local path
                lora_info.append({
                    "path": local_path,
                    "scale": scale,
                    "original_path": path,
                    "downloaded": False,  # Mark as not downloaded since it already existed
                    "lora_name": filename  # Add lora_name for ComfyUI workflow
                })
                
                responses.append(f"Using existing lora file: {local_path}")
                continue
            
            # If we get here, we need to download the file
            # Only add to file_paths for cleanup if it's not a protected model
            if not is_protected:
                file_paths.append(local_path)
                logger.info(f"Added downloaded lora path to file_paths for cleanup: {local_path}")
            else:
                logger.info(f"Not adding protected model to cleanup list: {local_path}")
            
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
            logger.info(f"Using local lora at {path} (not adding to file_paths for cleanup)")
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

def is_protected_model(filename):
    """Check if a file is a protected model that should never be deleted.
    
    Args:
        filename: Name of the file to check
        
    Returns:
        bool: True if the file is protected, False otherwise
    """
    # Check if the file has the signature of a model that should be deleted
    # Only delete files with "pytorch_lora_weights" in the name
    if "pytorch_lora_weights" in filename:
        logger.info(f"File {filename} is not protected (has pytorch_lora_weights in name)")
        return False
    
    # All other models are protected
    logger.info(f"File {filename} is protected (does not have pytorch_lora_weights in name)")
    return True

def cleanup_lora_files(file_paths, job_id=None):
    """Delete downloaded lora files after inference is complete.
    
    Args:
        file_paths: List of file paths to delete
        job_id: ID of the job for logging
        
    Returns:
        dict: Status of cleanup operation
    """
    # Set job ID for logging if provided
    if job_id:
        job_id_filter.set_job_id(job_id)
    
    if not file_paths:
        return {"status": "success", "message": "No lora files to clean up"}
    
    logger.info(f"Cleanup requested for {len(file_paths)} lora files: {file_paths}")
    
    cleanup_errors = []
    deleted_files = []
    skipped_files = []
    
    # Define the directories where downloaded loras are stored
    LORA_DIRS = [
        "/runpod-volume/models/loras",
        "/workspace/models/loras"
    ]
    
    for file_path in file_paths:
        try:
            # Check if the file exists
            if not os.path.exists(file_path):
                reason = "non-existent file"
                logger.warning(f"Skipping deletion of {reason}: {file_path}")
                skipped_files.append(file_path)
                continue
                
            # Check if the file is in one of the lora directories
            is_in_lora_dir = any(file_path.startswith(lora_dir) for lora_dir in LORA_DIRS)
            
            # Get the filename
            filename = os.path.basename(file_path)
            
            # Check if the file is a protected model
            if is_protected_model(filename):
                reason = "protected model file (does not have pytorch_lora_weights in name)"
                logger.warning(f"Skipping deletion of {reason}: {file_path}")
                skipped_files.append(file_path)
                continue
            
            # Only delete files that are in the download directories AND were downloaded from URLs
            # We can identify URL downloads because they were added to file_paths in download_lora_files
            if is_in_lora_dir:
                logger.info(f"Deleting lora file (has pytorch_lora_weights in name): {file_path}")
                os.remove(file_path)
                deleted_files.append(file_path)
                logger.info(f"Successfully deleted lora file: {file_path}")
            else:
                reason = "local file (not in download directory)"
                logger.warning(f"Skipping deletion of {reason}: {file_path}")
                skipped_files.append(file_path)
        except Exception as e:
            error_msg = f"Error deleting {file_path}: {str(e)}"
            cleanup_errors.append(error_msg)
            logger.error(error_msg)
    
    if cleanup_errors:
        return {
            "status": "warning",
            "message": "Some lora files could not be deleted",
            "details": cleanup_errors,
            "deleted_files": deleted_files,
            "skipped_files": skipped_files
        }
    
    return {
        "status": "success",
        "message": "All lora files cleaned up successfully",
        "details": deleted_files,
        "skipped_files": skipped_files
    }

def call_webhook(webhook_url, job_id, status, result=None, error=None, additional_data=None):
    """Call a webhook URL with the job results.
    
    Args:
        webhook_url: URL to call
        job_id: ID of the job
        status: Status of the job (success, error)
        result: Result of the job (if successful)
        error: Error message (if failed)
        additional_data: Additional data to include in the payload
        
    Returns:
        dict: Status of webhook call
    """
    # Set job ID for logging
    job_id_filter.set_job_id(job_id)
    
    if not webhook_url:
        return {"status": "skipped", "message": "No webhook URL provided"}
    
    try:
        logger.info(f"Calling webhook URL: {webhook_url}")
        
        # Prepare payload
        payload = {
            "job_id": job_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if result is not None:
            payload["result"] = result
            
        if error is not None:
            payload["error"] = error
            
        if additional_data is not None:
            payload.update(additional_data)
        
        # Send POST request to webhook URL
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30  # 30 second timeout
        )
        
        # Check response
        if response.status_code >= 200 and response.status_code < 300:
            logger.info(f"Webhook call successful: {response.status_code}")
            return {
                "status": "success",
                "message": f"Webhook call successful: {response.status_code}",
                "response": response.text
            }
        else:
            logger.error(f"Webhook call failed: {response.status_code} - {response.text}")
            return {
                "status": "error",
                "message": f"Webhook call failed: {response.status_code}",
                "response": response.text
            }
    except Exception as e:
        error_msg = f"Error calling webhook: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": error_msg
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