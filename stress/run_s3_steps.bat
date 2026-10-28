@echo off
REM S3 step load: 10/30/60/100 users x 3 min each (Locust 2.47 removed --step-load)
@chcp 65001 >nul
cd /d "%~dp0.."
set STRESS_MODE=S1
set PY=backend\.venv\Scripts\python.exe

for %%U in (10 30 60 100) do (
  echo [S3] %%U users x 3min ...
  %PY% -m locust -f stress\locustfile.py --host http://127.0.0.1:8001 --headless -u %%U -r 5 --run-time 3m --csv stress\results\s3_%%U
)
echo S3 done.
