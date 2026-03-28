# local-git-mcp

A lightweight MCP server that handles git operations on behalf of AI coding assistants. Runs locally as a stdio subprocess — no network ports, no external exposure.

## Why?

When AI assistants run inside sandboxed environments with filesystem mounts (e.g. FUSE/bindfs), git lock files (`HEAD.lock`, `index.lock`, etc.) created during commits cannot be cleaned up by the sandbox process due to permission restrictions. This blocks subsequent git operations.

Running git operations through a local MCP server — which executes with full host OS permissions — eliminates this problem entirely.

## Tools

| Tool | Description |
|------|-------------|
| `git_status` | Get `git status` output |
| `git_commit` | Stage and commit changes (with automatic lock file cleanup) |
| `git_log` | View recent commit history |
| `git_diff` | View working tree or staged diffs |
| `git_add` | Stage specific files |
| `git_push` | Push to a remote |
| `git_pull` | Pull from a remote |
| `git_create_branch` | Create (and optionally check out) a new branch |
| `git_checkout` | Check out an existing branch |
| `git_current_branch` | Get the current branch name |

## Installation

```bash
# Using uv
uv pip install .

# Or using pip
pip install .
```

## Per-Repository Access Control

The server does **not** operate on arbitrary paths. Before executing any git operation, it validates that the target repository has explicitly opted in by checking for a sentinel file.

**To allow the server to operate on a repository**, create a `.git-mcp-allowed` file in the repository root:

```bash
cd /path/to/your/repo
touch .git-mcp-allowed
git add .git-mcp-allowed
git commit -m "Allow local-git-mcp operations"
```

The file may be empty or contain optional freeform notes. If the file is not present, all operations against that repository will be rejected with a clear error message.

**Security rationale:** Without this, any process that can reach the MCP server could request git operations on any directory on the filesystem. The sentinel file ensures that access must be granted intentionally, at the repo level, by someone with write access to that repo.

## MCP Client Configuration

### Claude Code

Add to your MCP settings (e.g. `~/.claude/mcp_settings.json` or project-level `.mcp.json`):

```json
{
  "mcpServers": {
    "local-git-mcp": {
      "command": "local-git-mcp",
      "args": [],
      "type": "stdio"
    }
  }
}
```

If you installed with `uv` and the command isn't on your PATH, use the full path:

```json
{
  "mcpServers": {
    "local-git-mcp": {
      "command": "/path/to/your/venv/bin/local-git-mcp",
      "args": [],
      "type": "stdio"
    }
  }
}
```

### Other MCP Clients

Any MCP client that supports stdio transport can use this server. Point it at the `local-git-mcp` command (or the full path to the installed script) with stdio transport.

## Credentials and Authentication

The server inherits whatever credential setup the host OS has — SSH keys, macOS Keychain, git credential helpers, etc. No authentication is handled by the server itself. This means the server works with whatever you already have configured, and credential management stays entirely out of scope.

If `git_push` or `git_pull` encounters an authentication issue, the error will be returned as-is from git rather than hanging on an interactive prompt.

## macOS LaunchAgent (Optional)

To keep the server available as a system service, create a LaunchAgent plist at `~/Library/LaunchAgents/com.local-git-mcp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local-git-mcp</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/your/venv/bin/local-git-mcp</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/local-git-mcp.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/local-git-mcp.stderr.log</string>
</dict>
</plist>
```

Load it with:

```bash
launchctl load ~/Library/LaunchAgents/com.local-git-mcp.plist
```

> **Note:** A LaunchAgent is typically unnecessary since MCP clients spawn the server on demand via stdio. This is only useful if your setup benefits from a persistent background process.

## Security Model

- **Sentinel file required**: Every repository must contain a `.git-mcp-allowed` file before the server will execute any git commands against it. This is the sole access control mechanism — the server is stateless and config-free.
- **Repository validation**: The server verifies that `repo_path` points to a real git repository (contains a `.git` directory) before executing any command.
- **No network exposure**: stdio transport only — the server is never bound to a port.
- **No hardcoded paths**: All repository paths are passed as parameters at call time.
- **Lock file cleanup**: `git_commit` automatically cleans up stale `.lock` files in `.git/` before and after operations, solving the sandbox permission issue.
- **No credentials stored**: The server delegates all authentication to the host OS's existing git credential configuration.

## License

MIT
