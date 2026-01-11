
import requests
import json

try:
    response = requests.get("http://localhost:8000/api/v1/health")
    response.raise_for_status()  # Raise an exception for bad status codes
    print(json.dumps(response.json(), indent=2))
except requests.exceptions.RequestException as e:
    print(f"Error: {e}")
    exit(1)
