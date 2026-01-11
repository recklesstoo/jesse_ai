#!/usr/bin/env python3

print("Importing backend app...")
from backend import app as app_module

app = app_module.app
routes = [route.path for route in app.routes if hasattr(route, "path")]
print(f"Routes: {routes}")

# Test the endpoint
if __name__ == "__main__":
    import uvicorn
    print("Starting server on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
