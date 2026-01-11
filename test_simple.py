print("This is a test")
from backend import app as app_module

app = app_module.app
assert app.title == "BridgePuppet Backend"
print("Import completed")
