@echo off
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%
cd /d "%SCRIPT_DIR%"

set LOG_DIR=%SCRIPT_DIR%\logs
set PID_DIR=%SCRIPT_DIR%\.pids
set VENV_DIR=%SCRIPT_DIR%\.venv
set PYTHON=%VENV_DIR%\Scripts\python.exe
set PIP=%VENV_DIR%\Scripts\pip.exe
set STAMP_FILE=%VENV_DIR%\.install_stamp
set REQ_FILE=%SCRIPT_DIR%\requirements.txt
set API_PORT=8080
set AGENT_PORT=7777
set ES_URL=http://localhost:9200
if not defined ES_HOME set ES_HOME=

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%PID_DIR%" mkdir "%PID_DIR%"

set START_API=1
set START_AGENT=1
set START_ES=1

for %%A in (%*) do (
    if "%%A"=="--api-only"   ( set START_AGENT=0 & set START_ES=0 )
    if "%%A"=="--agent-only" ( set START_API=0   & set START_ES=0 )
    if "%%A"=="--no-es"      ( set START_ES=0 )
    if "%%A"=="--stop"       goto :stop
    if "%%A"=="--help"       goto :help
    if "%%A"=="-h"           goto :help
)
goto :main

:help
echo Usage: run.bat [--api-only] [--agent-only] [--no-es] [--stop]
exit /b 0

:stop
echo [INFO] Stopping all services...

:: ── 检测是否以管理员身份运行，否则自动提权重启 ──
net session >nul 2>&1
if errorlevel 1 (
    echo [INFO] Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c \"%~f0\" --stop' -Verb RunAs -Wait"
    exit /b 0
)

:: ── 方法1：按命令行特征杀进程（最可靠，不依赖 PID 是否变化）──
wmic process where "name='python.exe' and commandline like '%%uvicorn%%app%%main%%'" delete >nul 2>&1
wmic process where "name='python.exe' and commandline like '%%agent_os_app%%'"       delete >nul 2>&1

:: ── 方法2：通过保存的父进程 PID 杀整棵进程树 ──
if exist "%PID_DIR%\api.pid" (
    set /p _APID=<"%PID_DIR%\api.pid"
    taskkill /F /T /PID !_APID! >nul 2>&1
    del /f "%PID_DIR%\api.pid"
)
if exist "%PID_DIR%\agent_os.pid" (
    set /p _GPID=<"%PID_DIR%\agent_os.pid"
    taskkill /F /T /PID !_GPID! >nul 2>&1
    del /f "%PID_DIR%\agent_os.pid"
)

:: ── 方法3：按端口扫描残留进程（含 /T 杀子树）──
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%API_PORT% " ^| findstr "LISTENING"') do taskkill /F /T /PID %%P >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%AGENT_PORT% " ^| findstr "LISTENING"') do taskkill /F /T /PID %%P >nul 2>&1

timeout /t 1 /nobreak >nul
:: ── 验证端口是否已释放 ──
set _STILL=0
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%API_PORT% " ^| findstr "LISTENING"') do set _STILL=1
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%AGENT_PORT% " ^| findstr "LISTENING"') do set _STILL=1
if "!_STILL!"=="1" (
    echo [WARN] Ports still in use. Check if another app is using ports %API_PORT%/%AGENT_PORT%.
) else (
    echo [OK] All services stopped.
)
exit /b 0

:: ==================== MAIN ====================
:main

if exist "%PYTHON%" goto :venv_ok
echo [INFO] Creating virtual environment...
set SYS_PY=
for %%C in (python python3 py) do (
    if "!SYS_PY!"=="" (
        %%C -c "import sys; exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
        if !errorlevel!==0 set SYS_PY=%%C
    )
)
if "!SYS_PY!"=="" ( echo [ERROR] Python 3.9+ not found. & pause & exit /b 1 )
!SYS_PY! -m venv "%VENV_DIR%"
if errorlevel 1 ( echo [ERROR] Failed to create venv. & pause & exit /b 1 )
echo [OK] Virtual environment created.

:venv_ok
echo [INFO] Using Python: %PYTHON%

:: ---- dependency check (no nested if/else) ----
set NEED_INSTALL=0
"%PYTHON%" -c "import fastapi" >nul 2>&1
if errorlevel 1 set NEED_INSTALL=1
if not exist "%STAMP_FILE%" set NEED_INSTALL=1

if "%NEED_INSTALL%"=="0" goto :deps_ok

echo [INFO] Installing dependencies...
"%PYTHON%" -m pip install --upgrade pip -q
"%PYTHON%" -m pip install -r "%REQ_FILE%" -q
if errorlevel 1 ( echo [ERROR] Install failed. & pause & exit /b 1 )
type nul > "%STAMP_FILE%"
echo [OK] Dependencies installed.
goto :es_check

:deps_ok
echo [OK] Dependencies ready.

:: ==================== ES ====================
:es_check
if "%START_ES%"=="0" goto :api_check
curl -sf "%ES_URL%/_cluster/health" -o nul 2>nul
if errorlevel 1 goto :es_start
echo [OK] Elasticsearch running.
goto :api_check

:es_start
if "!ES_HOME!"=="" ( echo [WARN] ES not running. Set ES_HOME or start ES manually. & goto :api_check )
if not exist "!ES_HOME!\bin\elasticsearch.bat" ( echo [ERROR] Not found: !ES_HOME!\bin\elasticsearch.bat & goto :api_check )
echo [INFO] Starting Elasticsearch...
start "Elasticsearch" /min cmd /c "\"!ES_HOME!\bin\elasticsearch.bat\" >> \"%LOG_DIR%\es.log\" 2>&1"
set ES_READY=0
for /l %%i in (1,1,30) do (
    if "!ES_READY!"=="0" (
        curl -sf "%ES_URL%/_cluster/health" -o nul 2>nul
        if not errorlevel 1 set ES_READY=1
        if "!ES_READY!"=="0" timeout /t 2 /nobreak >nul
    )
)
if "!ES_READY!"=="0" echo [WARN] ES timeout. Check: %LOG_DIR%\es.log

:: ==================== API ====================
:api_check
if "%START_API%"=="0" goto :agent_check
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%API_PORT% " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%P /F >nul 2>&1
    timeout /t 1 /nobreak >nul
)
echo [INFO] Starting Search API (port %API_PORT%)...
start "SearchAPI" /min cmd /c "%PYTHON% -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT% --log-level info >>%LOG_DIR%\api.log 2>&1"
set API_READY=0
for /l %%i in (1,1,20) do (
    if "!API_READY!"=="0" (
        curl -sf "http://localhost:%API_PORT%/docs" -o nul 2>nul
        if not errorlevel 1 set API_READY=1
        if "!API_READY!"=="0" timeout /t 1 /nobreak >nul
    )
)
if "!API_READY!"=="1" ( echo [OK] Search API: http://localhost:%API_PORT%/docs ) else ( echo [WARN] API timeout. Check: %LOG_DIR%\api.log )

:: ==================== AGENT ====================
:agent_check
if "%START_AGENT%"=="0" goto :done
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%AGENT_PORT% " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%P /F >nul 2>&1
    timeout /t 1 /nobreak >nul
)
echo [INFO] Starting AgentOS (port %AGENT_PORT%)...
start "AgentOS" /min cmd /c "%PYTHON% agent_os_app.py >>%LOG_DIR%\agent_os.log 2>&1"
set AGENT_READY=0
for /l %%i in (1,1,20) do (
    if "!AGENT_READY!"=="0" (
        curl -sf "http://localhost:%AGENT_PORT%" -o nul 2>nul
        if not errorlevel 1 set AGENT_READY=1
        if "!AGENT_READY!"=="0" timeout /t 1 /nobreak >nul
    )
)
if "!AGENT_READY!"=="1" ( echo [OK] AgentOS: http://localhost:%AGENT_PORT% ) else ( echo [WARN] AgentOS timeout. Check: %LOG_DIR%\agent_os.log )

:done
echo.
echo ==============================
if "%START_API%"=="1"   echo   API    http://localhost:%API_PORT%/docs
if "%START_AGENT%"=="1" echo   Agent  http://localhost:%AGENT_PORT%
echo   Logs   %LOG_DIR%
echo   Stop   run.bat --stop
echo ==============================
echo.
pause
