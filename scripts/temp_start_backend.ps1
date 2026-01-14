 = Start-Process -FilePath '.\\.venv\\Scripts\\python.exe' -ArgumentList @('-m','uvicorn','backend.app:app','--host','0.0.0.0','--port','8000','--reload') -RedirectStandardOutput 'backend_stdout.log' -RedirectStandardError 'backend_stderr.log' -PassThru
.Id | Out-File backend.pid -Encoding utf8
