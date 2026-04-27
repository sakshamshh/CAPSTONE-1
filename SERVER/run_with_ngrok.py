import os
import sys

from pyngrok import ngrok
import uvicorn

if __name__ == "__main__":
    port = 8000
    print("Starting ngrok tunnel...")

    try:
        public_url = ngrok.connect(port, "http")
        print(f"ngrok tunnel created: {public_url}")
        print("If this is your first time using ngrok, visit https://dashboard.ngrok.com/get-started/your-authtoken to set an auth token.")
        print("Open the public URL in your phone browser or remote device.")
        print("Server will be available at http://localhost:8000 locally and through the public tunnel.")
    except Exception as exc:
        print("Failed to start ngrok tunnel:", exc, file=sys.stderr)
        sys.exit(1)

    uvicorn.run("server:app", host="0.0.0.0", port=port)
