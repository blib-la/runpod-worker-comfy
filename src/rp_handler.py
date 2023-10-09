import runpod


def hello_world(job):
    job_input = job["input"]
    greeting = job_input["greeting"]

    if not isinstance(greeting, str):
        return {"error": "Please provide a String"}

    return f"Hello {greeting}"


runpod.serverless.start({"handler": hello_world})
