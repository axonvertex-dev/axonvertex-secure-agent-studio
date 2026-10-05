import subprocess

VALID_API_KEY = "demo-key"

def ping_host(request):
    api_key = request.headers.get("X-API-Key")

    if api_key != VALID_API_KEY:
        return {"error": "unauthenticated"}, 401

    host = request.args.get("host", "")

    command = f"ping -c 1 {host}"

    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=5,
    )

    return {
        "host": host,
        "output": result.stdout,
        "stderr": result.stderr,
    }, 200
