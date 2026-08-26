#!/bin/bash
# Double-click this file in Finder to start mlev.
#
# It sets up an isolated Python environment the first time (a few minutes),
# then starts the local web app and opens it in your browser. Nothing leaves
# your machine except the data downloads.
#
# To stop it: close this Terminal window, or press Ctrl+C.

set -euo pipefail

# Finder launches .command files from the user's home directory, not from where
# the file lives, so anchor everything to the script's own folder.
cd "$(dirname "${BASH_SOURCE[0]}")"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'

banner() { printf '\n%s%s%s\n' "$BOLD" "$1" "$OFF"; }
ok()     { printf '%s  ✓%s %s\n' "$GREEN" "$OFF" "$1"; }
info()   { printf '%s    %s%s\n' "$DIM" "$1" "$OFF"; }
warn()   { printf '%s  !%s %s\n' "$YELLOW" "$OFF" "$1"; }

fail() {
  printf '\n%s  ✗ %s%s\n\n' "$RED" "$1" "$OFF"
  shift || true
  for line in "$@"; do printf '    %s\n' "$line"; done
  printf '\n%sPress Return to close this window.%s\n' "$DIM" "$OFF"
  read -r _ || true
  exit 1
}

banner "mlev — NFL & Premier League prediction models"

# ---- 1. find a usable Python -------------------------------------------------
PYTHON=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    major=${version%%.*}; minor=${version##*.}
    if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then PYTHON="$candidate"; break; fi
  fi
done

if [ -z "$PYTHON" ]; then
  fail "Python 3.10 or newer is required, and I could not find it." \
       "The easiest fix on a Mac:" \
       "" \
       "  1. Open https://www.python.org/downloads/macos/" \
       "  2. Download and run the latest installer" \
       "  3. Double-click 'Start mlev.command' again" \
       "" \
       "If you use Homebrew, 'brew install python@3.12' also works."
fi
ok "Python $("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# ---- 2. virtual environment --------------------------------------------------
VENV=".venv"
STAMP="$VENV/.requirements-installed"

if [ ! -d "$VENV" ]; then
  banner "First run — setting up (this takes a few minutes, only happens once)"
  "$PYTHON" -m venv "$VENV" || fail "Could not create the Python environment in $VENV."
  ok "created an isolated environment in $VENV/"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Reinstall only when requirements.txt has actually changed.
REQ_HASH=$(shasum -a 256 requirements.txt | cut -d' ' -f1)
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$REQ_HASH" ]; then
  info "installing packages…"
  python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  if ! python -m pip install --quiet -r requirements.txt; then
    fail "Could not install the required packages." \
         "Check your internet connection and try again." \
         "If it keeps failing, delete the .venv folder and re-run this file."
  fi
  printf '%s' "$REQ_HASH" > "$STAMP"
  ok "packages installed"
else
  ok "packages already installed"
fi

# ---- 3. pick a free port -----------------------------------------------------
PORT=8733
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if python - "$PORT" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  then break; fi
  warn "port $PORT is busy, trying $((PORT + 1))"
  PORT=$((PORT + 1))
done

# ---- 4. go -------------------------------------------------------------------
banner "Starting mlev"
info "http://127.0.0.1:$PORT will open in your browser"
info "keep this window open while you use it — closing it stops the app"
printf '\n'

exec python -m app.launch --port "$PORT"
