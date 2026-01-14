import requests
import json
import sys

def check_service(name, url):
    print(f"Checking {name} ({url})...", end=" ")
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            print("OK")
            return True
        print(f"FAIL (Status: {response.status_code})")
        return False
    except Exception as e:
        print(f"FAIL ({e})")
        return False

if __name__ == "__main__":
    backend = check_service("Backend", "http://localhost:8000/api/v1/health")
    frontend = check_service("Frontend", "http://localhost:3001")
    sys.exit(0 if backend and frontend else 1)
