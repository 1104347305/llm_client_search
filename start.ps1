# 客户搜索系统启动脚本 (PowerShell 包装器)
# 用法：
#   .\start.ps1               启动所有服务
#   .\start.ps1 --api-only    仅启动搜索 API
#   .\start.ps1 --agent-only  仅启动 AgentOS
#   .\start.ps1 --no-es       跳过 ES 检查
#   .\start.ps1 --stop        停止所有服务

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
& "$ScriptDir\start.bat" @args
