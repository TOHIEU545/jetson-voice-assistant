#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LLAMA_BIN="$PROJECT_ROOT/runtime/llama.cpp/bin/llama-server"
LLAMA_LIB="$PROJECT_ROOT/runtime/llama.cpp/lib"

MODEL="$PROJECT_ROOT/models/llm/gemma-3-1b-it-Q4_K_M.gguf"

LOG_DIR="$PROJECT_ROOT/logs"
LOG="$LOG_DIR/llama_server.log"
PID_FILE="$LOG_DIR/llama_server.pid"

mkdir -p "$LOG_DIR"

start_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")

        if kill -0 "$PID" 2>/dev/null; then
            echo "llama-server is already running."
            echo "PID: $PID"
            exit 0
        fi

        rm -f "$PID_FILE"
    fi

    LD_LIBRARY_PATH="$LLAMA_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$LLAMA_BIN" \
        -m "$MODEL" \
        --host 127.0.0.1 \
        --port 8080 \
        -c 2048 \
        -ngl 99 \
        -t 2 \
        > "$LOG" 2>&1 &

    echo $! > "$PID_FILE"

    echo "llama-server started."
    echo "PID: $(cat "$PID_FILE")"
    echo "Model: $MODEL"
    echo "Log: $LOG"
}

stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")

        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo "llama-server stopped."
        else
            echo "llama-server is not running."
        fi

        rm -f "$PID_FILE"
    else
        echo "llama-server is not running."
    fi
}

status_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")

        if kill -0 "$PID" 2>/dev/null; then
            echo "llama-server is running."
            echo "PID: $PID"

            HEALTH=$(curl -s http://127.0.0.1:8080/health)

            if [ -n "$HEALTH" ]; then
                echo "Health: $HEALTH"
            fi

            exit 0
        fi
    fi

    echo "llama-server is not running."
}

case "${1:-start}" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    status)
        status_server
        ;;
    *)
        echo "Usage: $0 [start|stop|status]"
        exit 1
        ;;
esac
