#!/usr/bin/env bash
# ============================================================
# 客户搜索系统 启动脚本
# 用法：./start.sh [选项]
#   --api-only     仅启动搜索 API（端口 8000）
#   --agent-only   仅启动 AgentOS（端口 7777）
#   --no-es        跳过 ES 启动检查
#   --stop         停止所有服务
# 默认：启动 ES + 搜索 API + AgentOS
# ============================================================

set -euo pipefail

# ---------- 颜色输出 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------- 脚本所在目录 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/.pids"
VENV_DIR="$SCRIPT_DIR/.venv"
mkdir -p "$LOG_DIR" "$PID_DIR"

API_PID_FILE="$PID_DIR/api.pid"
AGENT_PID_FILE="$PID_DIR/agent_os.pid"
API_PORT=8080
AGENT_PORT=7777
ES_URL="http://localhost:9200"

# ---------- 解析参数 ----------
START_API=true
START_AGENT=true
START_ES=true

for arg in "$@"; do
  case "$arg" in
    --api-only)   START_AGENT=false; START_ES=false ;;
    --agent-only) START_API=false;   START_ES=false ;;
    --no-es)      START_ES=false ;;
    --stop)
      info "停止所有服务..."
      for pid_file in "$API_PID_FILE" "$AGENT_PID_FILE"; do
        if [[ -f "$pid_file" ]]; then
          pid=$(cat "$pid_file")
          if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" && ok "已停止进程 $pid"
          fi
          rm -f "$pid_file"
        fi
      done
      pkill -f "uvicorn app.main" 2>/dev/null && ok "uvicorn 已停止" || true
      pkill -f "agent_os_app"    2>/dev/null && ok "AgentOS 已停止" || true
      exit 0
      ;;
    --help|-h)
      sed -n '2,9p' "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

# ---------- 虚拟环境（自动创建 + 安装依赖）----------
# 找一个系统 Python3（版本 >= 3.9）
find_python3() {
  for candidate in python3 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" &>/dev/null; then
      ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,9))" 2>/dev/null)
      if [[ "$ver" == "True" ]]; then
        echo "$candidate"; return
      fi
    fi
  done
  return 1
}

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  info "未找到虚拟环境，正在创建 .venv ..."
  SYS_PY=$(find_python3 || true)
  if [[ -z "$SYS_PY" ]]; then
    error "未找到 Python 3.9+，请先安装 Python"
    exit 1
  fi
  "$SYS_PY" -m venv "$VENV_DIR"
  ok "虚拟环境已创建：$VENV_DIR"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
info "使用 Python: $PYTHON ($("$PYTHON" --version 2>&1))"

# 检查依赖是否需要安装/更新（对比 requirements.txt 修改时间）
STAMP_FILE="$VENV_DIR/.install_stamp"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
need_install=false
if ! "$PYTHON" -c "import fastapi" &>/dev/null; then
  need_install=true
elif [[ -f "$REQ_FILE" && ( ! -f "$STAMP_FILE" || "$REQ_FILE" -nt "$STAMP_FILE" ) ]]; then
  need_install=true
fi

if $need_install; then
  info "安装/更新依赖（首次约需 1-2 分钟）..."
  "$PIP" install --upgrade pip -q
  "$PIP" install -r "$REQ_FILE" -q
  touch "$STAMP_FILE"
  ok "依赖安装完成"
else
  ok "依赖已就绪，跳过安装"
fi

# ---------- 启动/检查 Elasticsearch ----------
es_ready() {
  curl -sf "$ES_URL/_cluster/health" -o /dev/null 2>/dev/null
}

if $START_ES; then
  if es_ready; then
    ok "Elasticsearch 已在运行 ($ES_URL)"
  else
    info "启动 Elasticsearch (docker-compose)..."
    if command -v docker-compose &>/dev/null; then
      docker-compose up -d elasticsearch
      info "等待 ES 就绪..."
      for i in $(seq 1 30); do
        if es_ready; then ok "Elasticsearch 就绪"; break; fi
        sleep 2
        [[ $i -eq 30 ]] && warn "ES 启动超时，继续尝试..."
      done
    else
      warn "未找到 docker-compose，跳过 ES 启动（请手动确保 ES 在 ${ES_URL} 运行）"
    fi
  fi
fi

# ---------- 停止旧进程 ----------
stop_old() {
  local pid_file=$1 name=$2
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      warn "停止旧 $name 进程 (PID=$pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$pid_file"
  fi
}

# ---------- 启动搜索 API（端口 8080）----------
if $START_API; then
  stop_old "$API_PID_FILE" "搜索 API"
  pkill -f "uvicorn app.main" 2>/dev/null || true
  sleep 1

  info "启动搜索 API（端口 ${API_PORT}）..."
  nohup "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$API_PORT" \
    --reload \
    --log-level info \
    > "$LOG_DIR/api.log" 2>&1 &
  API_PID=$!
  echo "$API_PID" > "$API_PID_FILE"

  for i in $(seq 1 20); do
    if curl -sf "http://localhost:${API_PORT}/health" -o /dev/null 2>/dev/null || \
       curl -sf "http://localhost:${API_PORT}/docs"   -o /dev/null 2>/dev/null; then
      ok "搜索 API 就绪 → http://localhost:${API_PORT}/docs"
      break
    fi
    sleep 1
    [[ $i -eq 20 ]] && warn "搜索 API 启动超时，请查看日志：$LOG_DIR/api.log"
  done
fi

# ---------- 启动 AgentOS（端口 7777）----------
if $START_AGENT; then
  stop_old "$AGENT_PID_FILE" "AgentOS"
  pkill -f "agent_os_app" 2>/dev/null || true
  sleep 1

  info "启动 AgentOS（端口 ${AGENT_PORT}）..."
  nohup "$PYTHON" agent_os_app.py \
    > "$LOG_DIR/agent_os.log" 2>&1 &
  AGENT_PID=$!
  echo "$AGENT_PID" > "$AGENT_PID_FILE"

  for i in $(seq 1 20); do
    if curl -sf "http://localhost:${AGENT_PORT}" -o /dev/null 2>/dev/null; then
      ok "AgentOS 就绪 → http://localhost:${AGENT_PORT}"
      break
    fi
    sleep 1
    [[ $i -eq 20 ]] && warn "AgentOS 启动超时，请查看日志：$LOG_DIR/agent_os.log"
  done
fi

# ---------- 汇总 ----------
echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  服务启动完成${NC}"
echo -e "${GREEN}======================================${NC}"
$START_API   && echo -e "  搜索 API  → ${BLUE}http://localhost:${API_PORT}/docs${NC}"
$START_AGENT && echo -e "  AgentOS   → ${BLUE}http://localhost:${AGENT_PORT}${NC}"
$START_ES    && echo -e "  ES        → ${BLUE}$ES_URL${NC}"
echo ""
echo -e "  日志目录  → $LOG_DIR/"
echo -e "  停止服务  → ${YELLOW}./start.sh --stop${NC}"
echo -e "${GREEN}======================================${NC}"
