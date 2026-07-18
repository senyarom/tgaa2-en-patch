#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_SCRIPT="$ROOT/scripts/build_court_record_hook.sh"
AZAHAR="${AZAHAR:-/Applications/Azahar.app/Contents/MacOS/azahar}"
PROFILE="${AZAHAR_PROFILE:-$ROOT/build/azahar-home}"
PID_FILE="$PROFILE/azahar.pid"
LOG_FILE="$PROFILE/azahar.log"
QT_CONFIG="$PROFILE/Library/Application Support/Azahar/config/qt-config.ini"

GAME="tgaa2"
BUILD_ONLY=0
STOP_ONLY=0
FOREGROUND=0
WINDOW_MODE="--windowed"
GDB_PORT=""

usage() {
    cat <<'EOF'
Usage:
  ./run.sh [tgaa1|tgaa2] [options]
  ./run.sh --stop

Options:
  --build-only       Build the CIA without starting Azahar
  --gdb              Enable the GDB stub on port 24689
  --gdb=PORT         Enable the GDB stub on the specified port
  --fullscreen       Start in fullscreen mode
  --foreground       Keep Azahar attached to this terminal
  --stop             Stop the Azahar instance started by this script
  -h, --help         Show this help
EOF
}

running_pid() {
    if [[ ! -f "$PID_FILE" ]]; then
        return 1
    fi

    local pid
    pid="$(<"$PID_FILE")"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf '%s\n' "$pid"
        return 0
    fi

    rm -f "$PID_FILE"
    return 1
}

stop_emulator() {
    local pid
    if ! pid="$(running_pid)"; then
        echo "Azahar is not running (no active project PID)."
        return 0
    fi

    echo "Stopping Azahar (PID $pid)..."
    kill "$pid"
    local attempt
    for attempt in {1..30}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            echo "Azahar stopped."
            return 0
        fi
        sleep 0.1
    done

    echo "Azahar did not stop after SIGTERM; forcing it to stop..."
    kill -9 "$pid"
    rm -f "$PID_FILE"
    echo "Azahar stopped."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        tgaa1|tgaa2) GAME="$1" ;;
        --build-only) BUILD_ONLY=1 ;;
        --gdb) GDB_PORT="24689" ;;
        --gdb=*) GDB_PORT="${1#*=}" ;;
        --fullscreen) WINDOW_MODE="--fullscreen" ;;
        --foreground) FOREGROUND=1 ;;
        --stop) STOP_ONLY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ "$STOP_ONLY" -eq 1 ]]; then
    stop_emulator
    exit 0
fi

case "$GAME" in
    tgaa1)
        BUILD_DIR="$ROOT/build/tgaa1"
        CIA="$BUILD_DIR/TGAA1-Official-English-v2.8.6.cia"
        ROM="$ROOT/game-data/tgaa1/base.cxi"
        ;;
    tgaa2)
        BUILD_DIR="$ROOT/build/tgaa2"
        CIA="$BUILD_DIR/DGS2-Official-English-v2.3.3.cia"
        ROM="$ROOT/game-data/tgaa2/base.cxi"
        ;;
esac

"$BUILD_SCRIPT" "$GAME" "$BUILD_DIR"
if [[ "$BUILD_ONLY" -eq 1 ]]; then
    exit 0
fi

if [[ ! -x "$AZAHAR" ]]; then
    echo "Azahar was not found at: $AZAHAR" >&2
    exit 1
fi
if [[ ! -f "$ROM" ]]; then
    echo "Base image was not found: $ROM" >&2
    exit 1
fi
if [[ -n "$GDB_PORT" ]] && { [[ ! "$GDB_PORT" =~ ^[0-9]+$ ]] || (( GDB_PORT < 1 || GDB_PORT > 65535 )); }; then
    echo "Invalid GDB port: $GDB_PORT" >&2
    exit 2
fi

stop_emulator
mkdir -p "$PROFILE"

echo "Installing update into the Azahar test profile..."
env HOME="$PROFILE" "$AZAHAR" -i "$CIA"

# Azahar persists this setting, so normal launches must explicitly disable it.
if [[ -f "$QT_CONFIG" ]]; then
    if [[ -n "$GDB_PORT" ]]; then
        sed -i '' -E "s/^use_gdbstub=.*/use_gdbstub=true/" "$QT_CONFIG"
        sed -i '' -E "s/^gdbstub_port=.*/gdbstub_port=$GDB_PORT/" "$QT_CONFIG"
    else
        sed -i '' -E "s/^use_gdbstub=.*/use_gdbstub=false/" "$QT_CONFIG"
    fi
fi

args=("$WINDOW_MODE")
if [[ -n "$GDB_PORT" ]]; then
    args+=(--gdbport "$GDB_PORT")
fi
args+=("$ROM")

echo "Starting $GAME in Azahar..."
echo "Profile: $PROFILE"
if [[ "$FOREGROUND" -eq 1 ]]; then
    printf '%s\n' "$$" >"$PID_FILE"
    exec env HOME="$PROFILE" "$AZAHAR" "${args[@]}"
fi

HOME="$PROFILE" nohup "$AZAHAR" "${args[@]}" >"$LOG_FILE" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$PID_FILE"
sleep 1
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Azahar exited during startup. Log: $LOG_FILE" >&2
    exit 1
fi

echo "Azahar started (PID $pid)."
echo "Log: $LOG_FILE"
if [[ -n "$GDB_PORT" ]]; then
    echo "The game is paused until GDB connects to 127.0.0.1:$GDB_PORT."
fi
