#!/usr/bin/env python3

try:
    print("Testing backend app import...")
    from backend import app as app_module
    print("backend app imported successfully")

    routes = [route.path for route in app_module.app.routes if hasattr(route, "path")]
    print(f"App routes: {routes}")
    assert any(r.startswith("/api/v1/health") for r in routes)
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
