@echo off
REM 一键压测：隔离环境起后端(8001) -> 准备数据 -> 依次跑场景 -> 抓 metrics -> 关后端
REM 用法：双击或命令行执行 stress\run_stress.bat [pilot|full]
REM   pilot: 5 用户 1 分钟试跑（验证脚本）
REM   full : S1/S2 各 10 分钟 + S3 阶梯加压

setlocal enabledelayedexpansion
cd /d "%~dp0.."

set STAGE=%1
if "%STAGE%"=="" set STAGE=full

REM ---- 压测环境变量（隔离数据目录，绝不碰 data/）----
set DATA_DIR=./data_stress
set LLM_MODE=mock
set DASHSCOPE_API_KEY=
set JWT_SECRET=stress-test-only-not-for-prod
set RATE_LIMIT_CHAT_PER_MIN=100000
set RATE_LIMIT_LOGIN_PER_MIN=100000
set RATE_LIMIT_REGISTER_PER_MIN=100000
set RATE_LIMIT_API_PER_MIN=100000

set PORT=8001
set PY=backend\.venv\Scripts\python.exe
set RESULTS=stress\results
if not exist %RESULTS% mkdir %RESULTS%
set STRESS_LOG=%RESULTS%\backend_stress.log

echo ============================================================
echo  压测环境：DATA_DIR=%DATA_DIR%  LLM_MODE=%LLM_MODE%  PORT=%PORT%
echo ============================================================

REM ---- 启动后端 ----
start "stress-backend" /min cmd /c "%PY% -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %PORT% > %STRESS_LOG% 2>&1"

REM ---- 等待就绪 ----
set /a TRIES=0
:wait_health
timeout /t 2 /nobreak >nul
%PY% -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:%PORT%/health',timeout=3).status_code==200 else 1)" >nul 2>&1
if errorlevel 1 (
  set /a TRIES+=1
  if !TRIES! geq 30 (
    echo 后端启动超时，日志见 %STRESS_LOG%
    goto :cleanup
  )
  goto :wait_health
)
echo 后端已就绪。

REM ---- 准备数据与用户 ----
%PY% stress\prepare_env.py
if errorlevel 1 (
  echo 环境准备失败，日志见 %STRESS_LOG%
  goto :cleanup
)

if "%STAGE%"=="pilot" goto :pilot

echo.
echo [S1] 稳态 100 并发纯问答 10 分钟...
set STRESS_MODE=S1
%PY% -m locust -f stress\locustfile.py --host http://127.0.0.1:%PORT% --headless -u 100 -r 10 --run-time 10m --csv %RESULTS%\s1 --html %RESULTS%\s1.html

echo.
echo [S2] 混合负载 100 并发 10 分钟...
set STRESS_MODE=S2
%PY% -m locust -f stress\locustfile.py --host http://127.0.0.1:%PORT% --headless -u 100 -r 10 --run-time 10m --csv %RESULTS%\s2 --html %RESULTS%\s2.html

echo.
echo [S3] 阶梯加压 10/30/60/100 各 3 分钟...
set STRESS_MODE=S1
call stress\run_s3_steps.bat
goto :snapshot

:pilot
echo.
echo [Pilot] 5 并发 1 分钟试跑...
set STRESS_MODE=S1
%PY% -m locust -f stress\locustfile.py --host http://127.0.0.1:%PORT% --headless -u 5 -r 2 --run-time 1m --csv %RESULTS%\pilot

:snapshot
echo.
echo 抓取 Prometheus 快照...
%PY% -c "import httpx; t=httpx.get('http://127.0.0.1:%PORT%/metrics',timeout=10).text; open(r'%RESULTS%\metrics_snapshot.txt','w',encoding='utf-8').write(t); print('已写入', r'%RESULTS%\metrics_snapshot.txt', len(t), '字节')"

:cleanup
echo.
echo 关闭压测后端...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1
echo 压测结束。结果目录：%RESULTS%
endlocal
