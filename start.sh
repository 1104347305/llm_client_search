#!/usr/bin/env bash
# ============================================================
# 客户搜索系统 启动脚本（Linux / macOS，无 Docker）
#
# 用法：
#   ./start.sh                # 启动 ES + 搜索 API + AgentOS
#   ./start.sh --api-only     # 仅启动搜索 API（跳过 ES / AgentOS）
#   ./start.sh --agent-only   # 仅启动 AgentOS（跳过 ES / API）
#   ./start.sh --no-es        # 跳过 ES 启动（ES 已在运行时使用）
#   ./start.sh --stop         # 停止所有服务
#
# 环境变量（可在 .env 中配置）：
#   ES_HOME    Elasticsearch 安装目录（不设则跳过 ES 自动启动）
#   API_PORT   搜索 API 端口（默认 8080）
#   AGENT_PORT AgentOS 端口（默认 7777）
# ============================================================

set -uo pipefail

# ── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── 路径 ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/.pids"
VENV_DIR="$SCRIPT_DIR/.venv"
mkdir -p "$LOG_DIR" "$PID_DIR"

API_PID_FILE="$PID_DIR/api.pid"
AGENT_PID_FILE="$PID_DIR/agent_os.pid"
ES_PID_FILE="$PID_DIR/es.pid"

API_PORT="${API_PORT:-8080}"
AGENT_PORT="${AGENT_PORT:-7777}"
ES_URL="${ES_URL:-http://localhost:9200}"
ES_HOME="${ES_HOME:-}"

# ── 参数解析 ───────────────────────────────────────────────
START_API=true
START_AGENT=true
START_ES=true

for arg in "$@"; do
  case "$arg" in
    --api-only)   START_AGENT=false; START_ES=false ;;
    --agent-only) START_API=false;   START_ES=false ;;
    --no-es)      START_ES=false ;;
    --stop)       goto_stop=true ;;
    --help|-h)
      sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

# ── 停止 ──────────────────────────────────────────────────
stop_services() {
  info "停止所有服务..."

  # 按命令行特征杀（最可靠）
  pkill -f "uvicorn app.main"  2>/dev/null && ok "uvicorn 已停止"  || true
  pkill -f "agent_os_app"      2>/dev/null && ok "AgentOS 已停止" || true

  # 按 PID 文件补充清理
  for pid_file in "$API_PID_FILE" "$AGENT_PID_FILE"; do
    if [[ -f "$pid_file" ]]; then
      pid=$(cat "$pid_file")
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
      rm -f "$pid_file"
    fi
  done

  # 验证端口释放
  sleep 1
  still=false
  for port in "$API_PORT" "$AGENT_PORT"; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
       lsof -i ":${port}" -sTCP:LISTEN &>/dev/null 2>/dev/null; then
      warn "端口 ${port} 仍被占用，请手动检查"
      still=true
    fi
  done
  $still || ok "所有服务已停止"
  exit 0
}

[[ "${goto_stop:-false}" == "true" ]] && stop_services

# ── 虚拟环境 ───────────────────────────────────────────────
find_python3() {
  for cand in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$cand" &>/dev/null; then
      if "$cand" -c "import sys; exit(0 if sys.version_info>=(3,9) else 1)" 2>/dev/null; then
        echo "$cand"; return 0
      fi
    fi
  done
  return 1
}

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  info "创建虚拟环境 .venv ..."
  SYS_PY=$(find_python3 || true)
  if [[ -z "${SYS_PY:-}" ]]; then
    err "未找到 Python 3.9+，请先安装"; exit 1
  fi
  "$SYS_PY" -m venv "$VENV_DIR"
  ok "虚拟环境已创建"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
info "Python: $PYTHON ($("$PYTHON" --version 2>&1))"

# 按需安装依赖
STAMP="$VENV_DIR/.install_stamp"
REQ="$SCRIPT_DIR/requirements.txt"
if ! "$PYTHON" -c "import fastapi" &>/dev/null || \
   [[ -f "$REQ" && ( ! -f "$STAMP" || "$REQ" -nt "$STAMP" ) ]]; then
  info "安装依赖（首次约 1-2 分钟）..."
  "$PIP" install --upgrade pip -q
  "$PIP" install -r "$REQ" -q
  touch "$STAMP"
  ok "依赖安装完成"
else
  ok "依赖已就绪"
fi

# ── Elasticsearch ──────────────────────────────────────────
es_ready() {
  curl -sf "$ES_URL/_cluster/health" -o /dev/null 2>/dev/null
}

if $START_ES; then
  if es_ready; then
    ok "Elasticsearch 已运行 ($ES_URL)"
  elif [[ -n "$ES_HOME" && -x "$ES_HOME/bin/elasticsearch" ]]; then
    info "启动 Elasticsearch ($ES_HOME)..."
    nohup "$ES_HOME/bin/elasticsearch" > "$LOG_DIR/es.log" 2>&1 &
    echo $! > "$ES_PID_FILE"
    info "等待 ES 就绪（最多 60 秒）..."
    for i in $(seq 1 30); do
      if es_ready; then ok "Elasticsearch 就绪"; break; fi
      sleep 2
      [[ $i -eq 30 ]] && warn "ES 启动超时，请查看 $LOG_DIR/es.log"
    done
  else
    warn "ES 未运行。请设置 ES_HOME 或手动启动 ES，再加 --no-es 重试"
    warn "例：ES_HOME=/opt/elasticsearch ./start.sh"
  fi
fi

# ── 工具函数：停止旧进程 ───────────────────────────────────
stop_old() {
  local pid_file=$1 label=$2
  if [[ -f "$pid_file" ]]; then
    local pid; pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      warn "停止旧 $label (PID=$pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$pid_file"
  fi
}

# ── 搜索 API（端口 API_PORT）──────────────────────────────
if $START_API; then
  stop_old "$API_PID_FILE" "搜索 API"
  pkill -f "uvicorn app.main" 2>/dev/null || true
  sleep 1

  info "启动搜索 API（端口 ${API_PORT}）..."
  nohup "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$API_PORT" \
    --log-level info \
    >> "$LOG_DIR/api.log" 2>&1 &
  echo $! > "$API_PID_FILE"

  ok_api=false
  for i in $(seq 1 20); do
    if curl -sf "http://localhost:${API_PORT}/docs" -o /dev/null 2>/dev/null; then
      ok "搜索 API 就绪 → http://localhost:${API_PORT}/docs"
      ok_api=true; break
    fi
    sleep 1
  done
  $ok_api || warn "搜索 API 启动超时，查看日志：$LOG_DIR/api.log"
fi

# ── AgentOS（端口 AGENT_PORT）────────────────────────────
if $START_AGENT; then
  stop_old "$AGENT_PID_FILE" "AgentOS"
  pkill -f "agent_os_app" 2>/dev/null || true
  sleep 1

  info "启动 AgentOS（端口 ${AGENT_PORT}）..."
  nohup "$PYTHON" agent_os_app.py \
    >> "$LOG_DIR/agent_os.log" 2>&1 &
  echo $! > "$AGENT_PID_FILE"

  ok_agent=false
  for i in $(seq 1 20); do
    if curl -sf "http://localhost:${AGENT_PORT}" -o /dev/null 2>/dev/null; then
      ok "AgentOS 就绪 → http://localhost:${AGENT_PORT}"
      ok_agent=true; break
    fi
    sleep 1
  done
  $ok_agent || warn "AgentOS 启动超时，查看日志：$LOG_DIR/agent_os.log"
fi

# ── 汇总 ──────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=====================================${NC}"
$START_API   && echo -e "  搜索 API  → ${BLUE}http://localhost:${API_PORT}/docs${NC}"
$START_AGENT && echo -e "  AgentOS   → ${BLUE}http://localhost:${AGENT_PORT}${NC}"
$START_ES    && echo -e "  ES        → ${BLUE}${ES_URL}${NC}"
echo ""
echo -e "  日志目录  → ${LOG_DIR}/"
echo -e "  停止服务  → ${YELLOW}./start.sh --stop${NC}"
echo -e "${GREEN}=====================================${NC}"
