@echo off
:: Auto-elevate to Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo [INFO] Killing port 8080...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8080 " ^| findstr "LISTENING" 2^>nul') do (
    echo [INFO] taskkill PID %%P
    taskkill /PID %%P /F /T
)

echo [INFO] Killing port 7777...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":7777 " ^| findstr "LISTENING" 2^>nul') do (
    echo [INFO] taskkill PID %%P
    taskkill /PID %%P /F /T
)

echo [OK] Done.
pause
