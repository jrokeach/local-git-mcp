import os
import stat
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


def _install_dependency_stubs() -> None:
    if "mcp.server.fastmcp" not in sys.modules:
        mcp_module = types.ModuleType("mcp")
        mcp_server_module = types.ModuleType("mcp.server")
        fastmcp_module = types.ModuleType("mcp.server.fastmcp")

        class FastMCP:
            def __init__(self, _name: str) -> None:
                self.settings = types.SimpleNamespace(host=None, port=None)

            def tool(self):
                def decorator(func):
                    return func

                return decorator

            def streamable_http_app(self):
                return types.SimpleNamespace(routes=[])

        fastmcp_module.FastMCP = FastMCP
        sys.modules["mcp"] = mcp_module
        sys.modules["mcp.server"] = mcp_server_module
        sys.modules["mcp.server.fastmcp"] = fastmcp_module

    if "starlette.requests" not in sys.modules:
        starlette_module = types.ModuleType("starlette")
        requests_module = types.ModuleType("starlette.requests")
        responses_module = types.ModuleType("starlette.responses")
        types_module = types.ModuleType("starlette.types")

        class Request:
            pass

        class JSONResponse:
            def __init__(self, _body, status_code: int = 200) -> None:
                self.status_code = status_code

            async def __call__(self, scope, receive, send) -> None:
                return None

        requests_module.Request = Request
        responses_module.JSONResponse = JSONResponse
        types_module.ASGIApp = object
        types_module.Receive = object
        types_module.Scope = dict
        types_module.Send = object

        sys.modules["starlette"] = starlette_module
        sys.modules["starlette.requests"] = requests_module
        sys.modules["starlette.responses"] = responses_module
        sys.modules["starlette.types"] = types_module


_install_dependency_stubs()

import server  # noqa: E402


class LoadOrCreateTokenTests(unittest.TestCase):
    def test_creates_new_token_with_0600_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "auth-token"

            token = server.load_or_create_token(str(token_path))

            self.assertEqual(64, len(token))
            self.assertTrue(token_path.exists())
            self.assertEqual(
                stat.S_IRUSR | stat.S_IWUSR,
                stat.S_IMODE(token_path.stat().st_mode),
            )

    def test_rejects_symlinked_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real_path = Path(tmpdir) / "real-token"
            token_path = Path(tmpdir) / "auth-token"
            real_path.write_text("a" * 64)
            os.chmod(real_path, 0o600)
            token_path.symlink_to(real_path)

            with self.assertRaisesRegex(RuntimeError, "symlinked token file"):
                server.load_or_create_token(str(token_path))

    def test_rejects_insecure_permissions_on_existing_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "auth-token"
            token_path.write_text("a" * 64)
            os.chmod(token_path, 0o644)

            with self.assertRaisesRegex(RuntimeError, "insecure mode"):
                server.load_or_create_token(str(token_path))


class CleanupStaleLockFilesTests(unittest.TestCase):
    def _make_repo(self, root: Path) -> Path:
        repo_path = root / "repo"
        git_dir = repo_path / ".git"
        git_dir.mkdir(parents=True)
        return repo_path

    def test_removes_old_known_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = self._make_repo(Path(tmpdir))
            lock_path = repo_path / ".git" / "index.lock"
            lock_path.write_text("")
            stale_time = time.time() - (server.STALE_LOCK_AGE_SECONDS + 10)
            os.utime(lock_path, (stale_time, stale_time))

            with mock.patch.object(server, "_resolve_git_dir", return_value=(repo_path / ".git").resolve()):
                with mock.patch.object(server, "_lock_is_in_use", return_value=False):
                    result = server._cleanup_stale_lock_files(str(repo_path))

            self.assertIsNone(result)
            self.assertFalse(lock_path.exists())

    def test_uses_resolved_git_dir_for_lock_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "repo"
            repo_path.mkdir()
            real_git_dir = Path(tmpdir) / "real-git-dir"
            real_git_dir.mkdir()
            lock_path = real_git_dir / "index.lock"
            lock_path.write_text("")
            stale_time = time.time() - (server.STALE_LOCK_AGE_SECONDS + 10)
            os.utime(lock_path, (stale_time, stale_time))

            with mock.patch.object(server, "_resolve_git_dir", return_value=real_git_dir):
                with mock.patch.object(server, "_lock_is_in_use", return_value=False):
                    result = server._cleanup_stale_lock_files(str(repo_path))

            self.assertIsNone(result)
            self.assertFalse(lock_path.exists())

    def test_rejects_recent_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = self._make_repo(Path(tmpdir))
            lock_path = repo_path / ".git" / "index.lock"
            lock_path.write_text("")

            with mock.patch.object(server, "_resolve_git_dir", return_value=(repo_path / ".git").resolve()):
                result = server._cleanup_stale_lock_files(str(repo_path))

            self.assertIn("looks active", result)
            self.assertTrue(lock_path.exists())

    def test_rejects_unknown_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = self._make_repo(Path(tmpdir))
            lock_path = repo_path / ".git" / "custom.lock"
            lock_path.write_text("")
            stale_time = time.time() - (server.STALE_LOCK_AGE_SECONDS + 10)
            os.utime(lock_path, (stale_time, stale_time))

            with mock.patch.object(server, "_resolve_git_dir", return_value=(repo_path / ".git").resolve()):
                result = server._cleanup_stale_lock_files(str(repo_path))

            self.assertIn("unsupported git lock file", result)


class ValidateRepoTests(unittest.TestCase):
    def test_accepts_git_repo_root_reported_by_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "repo"
            repo_path.mkdir()
            (repo_path / server.SENTINEL_FILE).write_text("")

            with mock.patch.object(
                server, "_resolve_git_toplevel", return_value=repo_path.resolve()
            ):
                result = server._validate_repo(str(repo_path))

            self.assertIsNone(result)

    def test_rejects_subdirectory_inside_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "repo"
            subdir_path = repo_path / "subdir"
            subdir_path.mkdir(parents=True)
            (subdir_path / server.SENTINEL_FILE).write_text("")

            with mock.patch.object(server, "_resolve_git_toplevel", return_value=repo_path):
                result = server._validate_repo(str(subdir_path))

            self.assertIn("is not the repository root", result)


if __name__ == "__main__":
    unittest.main()
