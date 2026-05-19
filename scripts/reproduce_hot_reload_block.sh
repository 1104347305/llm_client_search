#!/usr/bin/env sh

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${APP_DIR:-$ROOT_DIR/src/main/python}"
GUNICORN_CONF="${1:-${GUNICORN_CONF:-$APP_DIR/gunicorn_conf.py}}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
BASE_URL="${BASE_URL:-http://$HOST:$PORT}"
ROUNDS="${ROUNDS:-30}"
PARSE_PER_ROUND="${PARSE_PER_ROUND:-3}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-5}"
SLOW_SECONDS="${SLOW_SECONDS:-2}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs/reproduce_hot_reload_block}"
PID_FILE="$LOG_DIR/gunicorn.pid"
GUNICORN_LOG="$LOG_DIR/gunicorn.out"
RESULT_LOG="$LOG_DIR/requests.tsv"
QUERY_TEXT="${QUERY_TEXT:-身份证下周即将过期的客户}"

mkdir -p "$LOG_DIR"
: > "$RESULT_LOG"

if [ ! -f "$GUNICORN_CONF" ]; then
  echo "gunicorn config not found: $GUNICORN_CONF" >&2
  echo "usage: $0 /absolute/path/to/gunicorn_conf.py" >&2
  echo "or set GUNICORN_CONF=/absolute/path/to/gunicorn_conf.py" >&2
  exit 2
fi

cleanup() {
  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
      echo "stopping gunicorn pid=$PID"
      kill "$PID" 2>/dev/null || true
    fi
  fi
}

trap cleanup INT TERM

echo "starting gunicorn"
echo "  app dir: $APP_DIR"
echo "  conf:    $GUNICORN_CONF"
echo "  url:     $BASE_URL"
echo "  log:     $GUNICORN_LOG"

cd "$APP_DIR"
nohup python -m gunicorn -c "$GUNICORN_CONF" main:app > "$GUNICORN_LOG" 2>&1 &
echo "$!" > "$PID_FILE"

echo "waiting for /health ..."
READY=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 "$BASE_URL/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" != "1" ]; then
  echo "service did not become healthy, last gunicorn log:" >&2
  tail -n 80 "$GUNICORN_LOG" >&2 || true
  exit 1
fi

echo "method	round	index	http_code	total_seconds	exit_code" >> "$RESULT_LOG"

parse_once() {
  ROUND="$1"
  INDEX="$2"
  PAYLOAD=$(printf '{"source":"askbob","user_text":"%s","session_id":"reproduce-hot-reload","trace_id":"reload-%s-%s","user_id":"debug-user","user_action":"write","action_scenario":"customerSearch","extra_input_params":{}}' "$QUERY_TEXT" "$ROUND" "$INDEX")
  OUT=$(curl -sS \
    --max-time "$REQUEST_TIMEOUT" \
    -o /dev/null \
    -w "%{http_code}\t%{time_total}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$BASE_URL/api/v1/client_search_query_parse_no_encipher" 2>/dev/null) || CODE="$?"
  CODE="${CODE:-0}"
  printf "parse\t%s\t%s\t%s\t%s\n" "$ROUND" "$INDEX" "$OUT" "$CODE" >> "$RESULT_LOG"
  TOTAL=$(printf "%s" "$OUT" | awk '{print $2}')
  if [ "$CODE" != "0" ]; then
    echo "BLOCKED/TIMEOUT parse round=$ROUND index=$INDEX exit=$CODE"
  elif awk "BEGIN {exit !($TOTAL >= $SLOW_SECONDS)}"; then
    echo "SLOW parse round=$ROUND index=$INDEX total=${TOTAL}s"
  fi
  unset CODE
}

echo "warmup parse ..."
parse_once 0 0

echo "reproducing: trigger background full reload, then hit parse during reload"
for ROUND in $(seq 1 "$ROUNDS"); do
  curl -sS \
    --max-time "$REQUEST_TIMEOUT" \
    -o /dev/null \
    -w "reload\t$ROUND\t0\t%{http_code}\t%{time_total}\t0\n" \
    -H "Content-Type: application/json" \
    -d '{"force_reindex_fields":false,"wait":false}' \
    "$BASE_URL/api/v1/config/reload" >> "$RESULT_LOG" 2>/dev/null || \
    printf "reload\t%s\t0\t000\t0\t%s\n" "$ROUND" "$?" >> "$RESULT_LOG"

  curl -fsS --max-time 2 "$BASE_URL/health" >/dev/null 2>&1 || true

  for INDEX in $(seq 1 "$PARSE_PER_ROUND"); do
    parse_once "$ROUND" "$INDEX"
  done
done

echo "done"
echo "request results: $RESULT_LOG"
echo "gunicorn log:     $GUNICORN_LOG"
echo "pid file:         $PID_FILE"
echo "stop manually:    kill \$(cat \"$PID_FILE\")"
