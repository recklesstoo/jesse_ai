#!/usr/bin/env python3

print("Importing backend app...")
from backend import app as app_module

app = app_module.app
routes = [route.path for route in app.routes if hasattr(route, "path")]
print(f"App routes: {routes}")

commands_routes = [r for r in routes if "commands" in r]
print(f"Commands routes in app: {commands_routes}")
