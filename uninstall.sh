#!/usr/bin/env bash
set -euo pipefail

# local-git-mcp uninstaller
# Usage: curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/uninstall.sh | bash

INSTALL_DIR="${LOCAL_GIT_MCP_DIR:-$HOME/.local/share/local-git-mcp}"
SERVICE_LABEL="com.local-git-mcp"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\033[1;34m==> %s\033[0m\n' "$1"; }
warn()  { printf '\033[1;33m==> %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
# Detect OS
# ---------------------------------------------------------------------------
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *)      PLATFORM=unknown ;;
esac

# ---------------------------------------------------------------------------
# Remove system service
# ---------------------------------------------------------------------------
case "$PLATFORM" in
  macos)
    PLIST_PATH="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
    if [ -f "$PLIST_PATH" ]; then
      info "Stopping and removing macOS LaunchAgent"
      launchctl bootout "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
      rm -f "$PLIST_PATH"
      info "LaunchAgent removed"
    else
      info "No LaunchAgent found; skipping"
    fi
    ;;
  linux)
    UNIT_PATH="$HOME/.config/systemd/user/local-git-mcp.service"
    if [ -f "$UNIT_PATH" ]; then
      info "Stopping and removing systemd user service"
      systemctl --user disable --now local-git-mcp.service 2>/dev/null || true
      rm -f "$UNIT_PATH"
      systemctl --user daemon-reload
      info "systemd service removed"
    else
      info "No systemd user service found; skipping"
    fi
    ;;
  *)
    warn "Unknown platform ($OS); skipping service removal"
    ;;
esac

# ---------------------------------------------------------------------------
# Remove installation directory
# ---------------------------------------------------------------------------
if [ -d "$INSTALL_DIR" ]; then
  info "Removing installation directory: $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  info "Installation directory removed"
else
  info "Installation directory not found ($INSTALL_DIR); skipping"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
info "Uninstallation complete!"
echo ""
echo "  Note: .git-mcp-allowed sentinel files in your repositories were not removed."
echo "  Remove them manually if you no longer need them:"
echo "    find ~ -name .git-mcp-allowed -delete"
echo ""
echo "  If you configured an MCP client to use local-git-mcp, remember to remove"
echo "  the entry from your client config as well."
