"""Adversarial subprocess-boundary tests for GitTool."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_dev_team.tools.git import GitTool


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _init_repo(repo: Path) -> None:
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.name", "Test User")
    _run_git(repo, "config", "user.email", "test@example.invalid")


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


def _install_fake_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> Path:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    _write_executable(fake_git, source)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    return fake_git


async def _assert_process_stopped(pid: int) -> None:
    """Accept absence or a harmless zombie waiting for the OS to reap it."""
    for _ in range(200):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return

        status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not status or status.startswith("Z"):
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"process {pid} remained runnable after process-group termination")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
async def test_git_hook_cannot_read_provider_or_server_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    _run_git(tmp_path, "add", "source.txt")

    captured_env = tmp_path / "hook-env.txt"
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    _write_executable(
        hook,
        f"#!/bin/sh\nenv > {shlex.quote(str(captured_env))}\n",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret-must-not-reach-git")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret-must-not-reach-git")
    monkeypatch.setenv("API_KEY", "server-secret-must-not-reach-git")

    result = await GitTool(repo_dir=str(tmp_path)).execute(
        action="commit",
        args="environment probe",
    )

    assert result.ok, result.error
    hook_env = captured_env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in hook_env
    assert "ANTHROPIC_API_KEY" not in hook_env
    assert "API_KEY" not in hook_env
    assert "secret-must-not-reach-git" not in hook_env


async def test_git_timeout_kills_and_reaps_the_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_pid_file = tmp_path / "git.pid"
    child_pid_file = tmp_path / "helper.pid"
    _install_fake_git(
        tmp_path,
        monkeypatch,
        "#!/bin/sh\n"
        f"echo $$ > {shlex.quote(str(parent_pid_file))}\n"
        "sleep 30 &\n"
        f"echo $! > {shlex.quote(str(child_pid_file))}\n"
        "wait\n",
    )

    result = await GitTool(repo_dir=str(tmp_path), timeout_seconds=0.5).execute(action="status")

    assert not result.ok
    assert result.error == "Git command timed out"
    await _assert_process_stopped(int(parent_pid_file.read_text(encoding="utf-8")))
    await _assert_process_stopped(int(child_pid_file.read_text(encoding="utf-8")))


async def test_git_timeout_kills_helper_after_direct_parent_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_pid_file = tmp_path / "git.pid"
    child_pid_file = tmp_path / "helper.pid"
    _install_fake_git(
        tmp_path,
        monkeypatch,
        "#!/bin/sh\n"
        f"echo $$ > {shlex.quote(str(parent_pid_file))}\n"
        "sleep 30 &\n"
        f"echo $! > {shlex.quote(str(child_pid_file))}\n"
        "exit 0\n",
    )

    result = await GitTool(repo_dir=str(tmp_path), timeout_seconds=0.5).execute(action="status")

    assert not result.ok
    assert result.error == "Git command timed out"
    await _assert_process_stopped(int(parent_pid_file.read_text(encoding="utf-8")))
    await _assert_process_stopped(int(child_pid_file.read_text(encoding="utf-8")))


async def test_git_cancellation_kills_and_reaps_the_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_pid_file = tmp_path / "git.pid"
    child_pid_file = tmp_path / "helper.pid"
    _install_fake_git(
        tmp_path,
        monkeypatch,
        "#!/bin/sh\n"
        f"echo $$ > {shlex.quote(str(parent_pid_file))}\n"
        "sleep 30 &\n"
        f"echo $! > {shlex.quote(str(child_pid_file))}\n"
        "wait\n",
    )
    task = asyncio.create_task(
        GitTool(repo_dir=str(tmp_path), timeout_seconds=10).execute(action="status")
    )
    async with asyncio.timeout(2):
        while not child_pid_file.exists():
            await asyncio.sleep(0.01)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await _assert_process_stopped(int(parent_pid_file.read_text(encoding="utf-8")))
    await _assert_process_stopped(int(child_pid_file.read_text(encoding="utf-8")))


async def test_git_output_limit_stops_and_reaps_a_noisy_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_file = tmp_path / "git.pid"
    _install_fake_git(
        tmp_path,
        monkeypatch,
        "#!/bin/sh\n"
        f"echo $$ > {shlex.quote(str(pid_file))}\n"
        "while :; do printf '0123456789abcdef'; done\n",
    )

    result = await GitTool(
        repo_dir=str(tmp_path),
        timeout_seconds=5,
        max_output_bytes=2_048,
    ).execute(action="status")

    assert not result.ok
    assert "2,048-byte safety limit" in (result.error or "")
    await _assert_process_stopped(int(pid_file.read_text(encoding="utf-8")))


async def test_git_generic_capture_error_still_reaps_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_file = tmp_path / "git.pid"
    _install_fake_git(
        tmp_path,
        monkeypatch,
        f"#!/bin/sh\necho $$ > {shlex.quote(str(pid_file))}\nsleep 30\n",
    )

    class ExplodingGitTool(GitTool):
        async def _communicate_bounded(
            self,
            proc: asyncio.subprocess.Process,
        ) -> tuple[bytes, bytes]:
            async with asyncio.timeout(2):
                while not pid_file.exists():
                    await asyncio.sleep(0.01)
            raise RuntimeError("capture failed")

    result = await ExplodingGitTool(repo_dir=str(tmp_path)).execute(action="status")

    assert not result.ok
    assert result.error == "Git error: RuntimeError: capture failed"
    await _assert_process_stopped(int(pid_file.read_text(encoding="utf-8")))
