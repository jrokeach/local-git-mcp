#!/usr/bin/env bash
set -euo pipefail

# local-git-mcp installer
# Usage: curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/install.sh | bash
#   or:  curl -fsSL ... | bash -s -- --no-service
#
# Flags:
#   --no-service   Install and generate token, but skip service registration

REPO_URL="https://github.com/jrokeach/local-git-mcp.git"
INSTALL_DIR="${LOCAL_GIT_MCP_DIR:-$HOME/.local/share/local-git-mcp}"
VENV_DIR="$INSTALL_DIR/.venv"
TOKEN_FILE="$INSTALL_DIR/auth-token"
SERVICE_LABEL="com.local-git-mcp"
DEFAULT_PORT=44514

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
INSTALL_SERVICE=true
for arg in "$@"; do
  case "$arg" in
    --no-service) INSTALL_SERVICE=false ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: install.sh [--no-service]"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\033[1;34m==> %s\033[0m\n' "$1"; }
warn()  { printf '\033[1;33m==> %s\033[0m\n' "$1"; }
error() { printf '\033[1;31m==> %s\033[0m\n' "$1" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || error "Required command not found: $1"
}

detect_python() {
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local ver
      ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) || continue
      local major minor
      major=${ver%%.*}
      minor=${ver#*.}
      if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
        echo "$candidate"
        return
      fi
    fi
  done
  error "Python 3.11 or later is required but was not found on PATH."
}

install_macos_service() {
  local bin_path="$1"
  local plist_dir="$HOME/Library/LaunchAgents"
  local plist_path="$plist_dir/$SERVICE_LABEL.plist"

  mkdir -p "$plist_dir"

  if launchctl list "$SERVICE_LABEL" >/dev/null 2>&1; then
    info "Stopping existing LaunchAgent"
    launchctl bootout "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
  fi

  info "Installing macOS LaunchAgent"
  cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$SERVICE_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$bin_path</string>
        <string>--token-file</string>
        <string>$TOKEN_FILE</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/stderr.log</string>
</dict>
</plist>
PLIST

  launchctl bootstrap "gui/$(id -u)" "$plist_path"
  info "LaunchAgent installed and started"
  if [ "$IS_UPGRADE" = true ]; then
    info "Upgrade detected — service restarted with new version"
  fi
}

install_linux_service() {
  local bin_path="$1"
  local systemd_dir="$HOME/.config/systemd/user"
  local unit_path="$systemd_dir/local-git-mcp.service"
  local escaped_bin_path
  local escaped_token_file

  mkdir -p "$systemd_dir"
  require_cmd systemd-escape

  escaped_bin_path=$(systemd-escape --quote -- "$bin_path")
  escaped_token_file=$(systemd-escape --quote -- "$TOKEN_FILE")

  info "Installing systemd user service"
  cat > "$unit_path" <<UNIT
[Unit]
Description=local-git-mcp - Local MCP server for git operations
After=default.target

[Service]
Type=simple
ExecStart=$escaped_bin_path --token-file $escaped_token_file
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

  systemctl --user daemon-reload
  systemctl --user enable local-git-mcp.service
  systemctl --user restart local-git-mcp.service
  info "systemd user service installed and started"
}

# ---------------------------------------------------------------------------
# Detect OS
# ---------------------------------------------------------------------------
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *)      error "Unsupported platform: $OS" ;;
esac

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
require_cmd git
require_cmd openssl
require_cmd lsof
PYTHON=$(detect_python)
info "Using Python: $PYTHON ($($PYTHON --version 2>&1))"

# ---------------------------------------------------------------------------
# Install the package
# ---------------------------------------------------------------------------
IS_UPGRADE=false
if [ -d "$INSTALL_DIR/.git" ]; then
  IS_UPGRADE=true
  info "Updating existing installation in $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  info "Cloning local-git-mcp to $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

info "Creating virtual environment"
"$PYTHON" -m venv "$VENV_DIR"

info "Installing local-git-mcp"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null 2>&1
"$VENV_DIR/bin/pip" install --upgrade "$INSTALL_DIR" >/dev/null 2>&1
"$VENV_DIR/bin/pip" install --force-reinstall --no-deps "$INSTALL_DIR" >/dev/null 2>&1

BIN_PATH="$VENV_DIR/bin/local-git-mcp"
if [ ! -f "$BIN_PATH" ]; then
  error "Installation failed: $BIN_PATH not found."
fi

info "Installed: $BIN_PATH"

# ---------------------------------------------------------------------------
# Generate auth token
# ---------------------------------------------------------------------------
if [ -f "$TOKEN_FILE" ]; then
  info "Auth token already exists at $TOKEN_FILE"
else
  info "Generating auth token"
  mkdir -p "$(dirname "$TOKEN_FILE")"
  # Create file with 0600 from the start — never world-readable, even briefly.
  (umask 077 && openssl rand -hex 32 > "$TOKEN_FILE")
  info "Auth token written to $TOKEN_FILE (mode 0600)"
fi

TOKEN=$(cat "$TOKEN_FILE")

# ---------------------------------------------------------------------------
# Service installation
# ---------------------------------------------------------------------------
if [ "$INSTALL_SERVICE" = true ]; then
  case "$PLATFORM" in
    macos) install_macos_service "$BIN_PATH" ;;
    linux) install_linux_service "$BIN_PATH" ;;
  esac
else
  info "Skipping service installation (--no-service)"
  echo ""
  echo "  To run manually:"
  echo "    $BIN_PATH"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
info "Installation complete!"
echo ""
echo "  Binary:     $BIN_PATH"
echo "  Auth token: $TOKEN_FILE"
if [ "$INSTALL_SERVICE" = true ]; then
  case "$PLATFORM" in
    macos) echo "  Service:    macOS LaunchAgent ($SERVICE_LABEL)" ;;
    linux) echo "  Service:    systemd user unit (local-git-mcp.service)" ;;
  esac
fi
echo ""
echo "  Add one of the configs below to your MCP client."
echo "  The URL uses the default port ($DEFAULT_PORT); adjust if you changed it."
echo ""
echo "  Claude Code (CLI / IDE) — ~/.claude/mcp_settings.json or .mcp.json:"
echo ""
cat <<MCPCONFIG
    {
      "mcpServers": {
        "local-git-mcp": {
          "type": "http",
          "url": "http://127.0.0.1:$DEFAULT_PORT/mcp",
          "headers": {
            "Authorization": "Bearer $TOKEN"
          }
        }
      }
    }
MCPCONFIG
echo ""
echo "  Claude Desktop — claude_desktop_config.json (requires Node.js/npx):"
echo ""
cat <<MCPCONFIG
    {
      "mcpServers": {
        "local-git-mcp": {
          "command": "npx",
          "args": [
            "mcp-remote",
            "http://127.0.0.1:$DEFAULT_PORT/mcp",
            "--header",
            "Authorization: Bearer $TOKEN"
          ]
        }
      }
    }
MCPCONFIG
echo ""
echo "  Remember to create a .git-mcp-allowed file in each repo you want to manage."
