import json
import requests
import random
import sys
from PIL import Image
import io
import time

# Function to set parameters in the workflow JSON
def set_params(workflow, colorDetail, colorBody, token):
    for node in workflow:
        if '_meta' in workflow[node]:
            if workflow[node]['_meta']['title'] == 'ColorInputDetails':
                workflow[node]['inputs']['value'] = colorDetail
                print("Set ColorInputDetails")
            if workflow[node]['_meta']['title'] == 'ColorInputBody':
                workflow[node]['inputs']['value'] = colorBody
                print("Set ColorInputBody")
            if workflow[node]['_meta']['title'] == 'PromptTokenInput':
                workflow[node]['inputs']['value'] = token
                print("Set PromptTokenInput")
            if workflow[node]['_meta']['title'] == 'GlobalSeed':
                workflow[node]['inputs']['value'] = random.randint(0, sys.maxsize)
                print("Set GlobalSeed")
    return workflow

# Function to send a request to the Runpod API endpoint
def send_request(workflow, api_url, api_key):
    # Create the request payload
    request_payload = {
        "input": {
            "workflow": workflow,
            "images": []
            
        }
    }
    # Add headers
    headers = {
        "accept": "application/json",
        "authorization": f"{api_key}",
        "content-type": "application/json"
    }
    try:
        # Send the POST request
        response = requests.post(api_url, headers=headers, json=request_payload)
        response.raise_for_status()
        print("Request sent successfully.")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error sending request: {e}")
        return None

# Main script
def main(input_json_path, api_url, api_key, colorDetail, colorBody, token):
    # Load the input JSON file
    start = time.time()
    with open(input_json_path, "r") as f:
        workflow = json.load(f)

    # Modify the workflow parameters
    workflow = set_params(workflow, colorDetail, colorBody, token)

    # Send the modified workflow to the Runpod API
    response = send_request(workflow, api_url, api_key)

    # Process the response
    if response:
        end = time.time()
        timespent = round((end - start), 2)
        print("Response received:")
        print(json.dumps(response, indent=2))
        print(f"Time spent: {timespent}s.")

        # If the response contains image data
        if "images" in response:
            for node_id, image_data_list in response["images"].items():
                for image_data in image_data_list:
                    image = Image.open(io.BytesIO(image_data))
                    image.show()
 

if __name__ == "__main__":
    # Input file and API details
    input_json_path = "JasperAI_AWS_Endpoint_API.json"  # Replace with your JSON file path
    api_url = "https://api.runpod.ai/v2/e6s4y2ri7yc5aw/runsync"  # Replace with your Runpod API endpoint URL
    api_key = "rpa_RUGGARJG8B04GNBGCN5WK10NUZYBCCT4TWS68HMO5id23n"  # Replace with your API key

    # Parameters to set
    colorDetail = "5005441"  # Replace with your desired value
    colorBody = "12227444"   # Replace with your desired value
    token = "Bear"           # Replace with your desired value

    # Run the main script
    main(input_json_path, api_url, api_key, colorDetail, colorBody, token)
    #curl -Headers @{ "Authorization" = "Bearer rpa_RUGGARJG8B04GNBGCN5WK10NUZYBCCT4TWS68HMO5id23n" } https://api.runpod.ai/v2/e6s4y2ri7yc5aw/health

