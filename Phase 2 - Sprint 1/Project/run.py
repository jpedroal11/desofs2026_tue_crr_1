import sys
import os

# Get absolute path to the marketplace directory
marketplace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marketplace")

# Set PYTHONPATH env var BEFORE importing uvicorn — subprocesses inherit env vars
os.environ["PYTHONPATH"] = marketplace_path
sys.path.insert(0, marketplace_path)
os.chdir(marketplace_path)

import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
