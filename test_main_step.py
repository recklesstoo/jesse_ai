#!/usr/bin/env python3

import traceback

try:
    print("Step 1: Importing FastAPI...")
    from fastapi import FastAPI

    print("Step 2: Importing backend app...")
    from backend import app as app_module
    print(f"App imported: {app_module.app}")

    print("Step 3: Checking routes...")
    routes = [route.path for route in app_module.app.routes if hasattr(route, "path")]
    print(f"Routes: {routes}")

except Exception as e:
    print(f"Error at step: {e}")
    traceback.print_exc()
