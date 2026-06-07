"""Tests for the SandboxPort and its NullSandbox / BwrapSandbox impls.

The bwrap argv-shape tests do not invoke bwrap — they assert what the
sandbox *plans* to execute. One integration test runs bwrap for real
and is skipped when bwrap is absent.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pi_evaluator.adapters import sandbox as sandbox_mod
from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.adapters.sandbox import (
    BwrapSandbox,
    NullSandbox,
    ResourceCappedSandbox,
    ResourceCaps,
    bwrap_available,
    select_sandbox,
    systemd_run_available,
)
from pi_evaluator.domain.test_suite import GraduatedProblem, ValidationStep
from pi_evaluator.domain.types import Package
from pi_evaluator.ports.sandbox_port import SandboxedInvocation, SandboxPort


def _make_mock_pi(tmp_path: Path, exit_code: int = 0) -> str:
    script = tmp_path / "mock_pi"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "sys.stdout.write('{\"type\":\"agent_end\"}\\n')\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def _package() -> Package:
    return Package(
        model="google/gemini-2.5-flash",
        system_prompt="be concise",
        skills=["read", "write"],
        template_values={},
    )


def _problem(workspace: Path) -> GraduatedProblem:
    return GraduatedProblem(
        id="p1",
        title="Test",
        difficulty=1,
        prompt="solve it",
        workspace_dir=str(workspace),
        validation_steps=[ValidationStep(name="v", command="true")],
        tags=[],
    )


# --- NullSandbox -----------------------------------------------------


def test_null_sandbox_satisfies_port():
    assert isinstance(NullSandbox(), SandboxPort)


def test_null_sandbox_is_identity(tmp_path):
    sandbox = NullSandbox()
    cmd = ["pi", "--print", "do thing"]
    result = sandbox.wrap(cmd, workspace=tmp_path)
    assert result.cmd == cmd
    assert result.cwd == tmp_path
    assert result.env is None


def test_null_sandbox_returns_invocation_dataclass(tmp_path):
    result = NullSandbox().wrap(["pi"], workspace=tmp_path)
    assert isinstance(result, SandboxedInvocation)


# --- BwrapSandbox argv shape (unit) ---------------------------------


def test_bwrap_sandbox_satisfies_port():
    assert isinstance(BwrapSandbox(), SandboxPort)


def test_bwrap_prepends_bwrap_invocation(tmp_path):
    sandbox = BwrapSandbox(bwrap_binary="/usr/bin/bwrap")
    result = sandbox.wrap(["pi", "--print"], workspace=tmp_path)
    assert result.cmd[0] == "/usr/bin/bwrap"
    assert result.cmd[-2:] == ["pi", "--print"]


def test_bwrap_separates_bwrap_args_from_user_cmd(tmp_path):
    sandbox = BwrapSandbox()
    result = sandbox.wrap(["pi", "--print", "solve"], workspace=tmp_path)
    sep_idx = result.cmd.index("--")
    user_cmd_start = sep_idx + 1
    assert result.cmd[user_cmd_start:] == ["pi", "--print", "solve"]


def test_bwrap_binds_workspace_at_same_path(tmp_path):
    sandbox = BwrapSandbox()
    result = sandbox.wrap(["pi"], workspace=tmp_path)
    args = result.cmd
    bind_positions = [
        i for i, a in enumerate(args) if a == "--bind" and i + 2 < len(args)
    ]
    workspace_binds = [
        (args[i + 1], args[i + 2])
        for i in bind_positions
        if args[i + 1] == str(tmp_path.resolve())
    ]
    assert workspace_binds, "workspace should be --bind-mounted into the sandbox"
    src, dst = workspace_binds[0]
    assert src == dst, "workspace must appear at the same path inside the sandbox"


def test_bwrap_chdirs_to_workspace(tmp_path):
    sandbox = BwrapSandbox()
    result = sandbox.wrap(["pi"], workspace=tmp_path)
    args = result.cmd
    assert "--chdir" in args
    chdir_idx = args.index("--chdir")
    assert args[chdir_idx + 1] == str(tmp_path.resolve())


def test_bwrap_unshares_namespaces(tmp_path):
    """User/pid/ipc/uts/cgroup namespaces must be unshared. Network
    is deliberately *not* unshared — Pi must reach the model API."""
    args = BwrapSandbox().wrap(["pi"], workspace=tmp_path).cmd
    for flag in (
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
    ):
        assert flag in args, f"missing namespace flag: {flag}"
    assert "--unshare-net" not in args


def test_bwrap_die_with_parent_and_new_session(tmp_path):
    args = BwrapSandbox().wrap(["pi"], workspace=tmp_path).cmd
    assert "--die-with-parent" in args
    assert "--new-session" in args


def test_bwrap_mounts_proc_dev_tmp(tmp_path):
    args = BwrapSandbox().wrap(["pi"], workspace=tmp_path).cmd
    assert args[args.index("--proc") + 1] == "/proc"
    assert args[args.index("--dev") + 1] == "/dev"
    assert args[args.index("--tmpfs") + 1] == "/tmp"


def test_bwrap_does_not_bind_user_home(tmp_path):
    """The real $HOME (with ~/.ssh, ~/.aws, ~/.config/gh) must not
    appear inside the sandbox."""
    real_home = os.path.expanduser("~")
    args = BwrapSandbox().wrap(["pi"], workspace=tmp_path).cmd
    bind_flags = {"--bind", "--ro-bind", "--ro-bind-try", "--dev-bind"}
    for i, a in enumerate(args):
        if a in bind_flags and i + 1 < len(args):
            src = args[i + 1]
            assert src != real_home, f"{a} {src} would expose real $HOME"


def test_bwrap_extra_ro_binds_appended(tmp_path):
    """Callers can pin auxiliary paths (e.g., the Pi binary's install
    directory) into the sandbox via ``extra_ro_binds``."""
    aux = tmp_path / "pi-install"
    aux.mkdir()
    sandbox = BwrapSandbox(extra_ro_binds=(aux,))
    args = sandbox.wrap(["pi"], workspace=tmp_path / "ws").cmd
    pairs = [
        (args[i + 1], args[i + 2])
        for i in range(len(args) - 2)
        if args[i] == "--ro-bind" and args[i + 1] == str(aux.resolve())
    ]
    assert pairs and pairs[0][0] == pairs[0][1]


# --- BwrapSandbox env filtering -------------------------------------


def test_bwrap_env_scrubs_unallowed_keys(tmp_path):
    sandbox = BwrapSandbox()
    env = {
        "PATH": "/usr/bin",
        "GEMINI_API_KEY": "secret",
        "AWS_SECRET_ACCESS_KEY": "leakme",
        "GITHUB_TOKEN": "leakme2",
        "RANDOM_VAR": "x",
    }
    result = sandbox.wrap(["pi"], workspace=tmp_path, env=env)
    assert result.env is not None
    assert result.env["PATH"] == "/usr/bin"
    assert result.env["GEMINI_API_KEY"] == "secret"
    assert "AWS_SECRET_ACCESS_KEY" not in result.env
    assert "GITHUB_TOKEN" not in result.env
    assert "RANDOM_VAR" not in result.env


def test_bwrap_env_pi_prefix_passes_through(tmp_path):
    sandbox = BwrapSandbox()
    env = {"PATH": "/usr/bin", "PI_CONFIG_DIR": "/x", "PI_THEME": "dark"}
    result = sandbox.wrap(["pi"], workspace=tmp_path, env=env)
    assert result.env is not None
    assert result.env["PI_CONFIG_DIR"] == "/x"
    assert result.env["PI_THEME"] == "dark"


def test_bwrap_env_sets_sandbox_home(tmp_path):
    """HOME must be overridden so the real home dir isn't pointed at."""
    sandbox = BwrapSandbox()
    env = {"HOME": "/home/realuser", "PATH": "/usr/bin"}
    result = sandbox.wrap(["pi"], workspace=tmp_path, env=env)
    assert result.env is not None
    assert result.env["HOME"] == BwrapSandbox.DEFAULT_SANDBOX_HOME


def test_bwrap_env_none_inherits_os_environ_filtered(tmp_path, monkeypatch):
    """When env=None, scrub os.environ rather than passing it raw."""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leakme")
    monkeypatch.setenv("GEMINI_API_KEY", "passme")
    result = BwrapSandbox().wrap(["pi"], workspace=tmp_path, env=None)
    assert result.env is not None
    assert "AWS_SECRET_ACCESS_KEY" not in result.env
    assert result.env.get("GEMINI_API_KEY") == "passme"


# --- Adapter wiring -------------------------------------------------


def test_adapter_default_sandbox_is_null():
    adapter = CliSubprocessAdapter(pi_binary="pi")
    assert isinstance(adapter._sandbox, NullSandbox)


def test_adapter_accepts_sandbox_port():
    class RecordingSandbox:
        def __init__(self):
            self.calls = []

        def wrap(self, cmd, workspace, env=None):
            self.calls.append((list(cmd), workspace, env))
            return SandboxedInvocation(cmd=list(cmd), cwd=workspace, env=env)

    rs = RecordingSandbox()
    adapter = CliSubprocessAdapter(pi_binary="pi", sandbox=rs)
    assert adapter._sandbox is rs


def test_adapter_routes_invocation_through_sandbox(tmp_path):
    """The adapter must hand the planned Pi command to the sandbox's
    wrap() and execute whatever the sandbox returns."""
    src = tmp_path / "src"
    src.mkdir()
    pi = _make_mock_pi(tmp_path)
    captured: dict = {}

    class CapturingSandbox:
        def wrap(self, cmd, workspace, env=None):
            captured["cmd"] = list(cmd)
            captured["workspace"] = workspace
            return SandboxedInvocation(cmd=list(cmd), cwd=workspace, env=env)

    adapter = CliSubprocessAdapter(
        pi_binary=pi, retry_budget=0, sandbox=CapturingSandbox()
    )
    adapter.run(_package(), _problem(src), workspace=str(src))
    assert captured["cmd"][0] == pi
    assert captured["cmd"][1] == "--print"


# --- BwrapSandbox integration (real bwrap) --------------------------


@pytest.mark.skipif(not bwrap_available(), reason="bwrap unavailable on host")
def test_bwrap_integration_runs_mock_pi(tmp_path):
    """End-to-end: adapter + BwrapSandbox runs a mock Pi binary inside
    a real bwrap sandbox.

    The script is placed inside the workspace source so that
    ``materialize_workspace`` copies it into the materialized tmpdir.
    ``pi_binary='./mock_pi'`` is then resolved by ``execvp`` against
    the materialized cwd — which is what the sandbox binds and what
    bwrap ``--chdir``'s into.
    """
    src = tmp_path / "src"
    src.mkdir()
    _make_mock_pi(src)
    adapter = CliSubprocessAdapter(
        pi_binary="./mock_pi",
        retry_budget=0,
        sandbox=BwrapSandbox(),
    )
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert result.exit_code == 0
    assert any(e.get("type") == "agent_end" for e in result.events)


@pytest.mark.skipif(not bwrap_available(), reason="bwrap unavailable on host")
def test_bwrap_integration_home_is_sandbox_tmpfs(tmp_path):
    """Inside the sandbox, ``$HOME`` resolves to the tmpfs path set by
    ``BwrapSandbox.DEFAULT_SANDBOX_HOME``, not the real host home.
    This is the load-bearing safety property: without HOME redirection,
    the agent could read ``~/.ssh``, ``~/.aws``, etc."""
    src = tmp_path / "src"
    src.mkdir()
    probe = src / "probe"
    probe.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "sys.stdout.write('HOME=' + os.environ.get('HOME', '') + chr(10))\n"
        "sys.stdout.write('{\"type\":\"agent_end\"}' + chr(10))\n"
    )
    probe.chmod(probe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    adapter = CliSubprocessAdapter(
        pi_binary="./probe",
        retry_budget=0,
        sandbox=BwrapSandbox(),
    )
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert result.exit_code == 0
    assert any(
        ln == f"HOME={BwrapSandbox.DEFAULT_SANDBOX_HOME}"
        for ln in result.malformed_lines
    )


class TestSelectSandbox:
    """select_sandbox: hard-fail isolation posture for the real-pi path (j8x).

    Policy (ADR 0009): BwrapSandbox when bwrap can sandbox; otherwise REFUSE
    to run unisolated unless PI_ALLOW_UNSANDBOXED is set, in which case fall
    back to NullSandbox with a loud warning.
    """

    def test_returns_capped_bwrap_when_available(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: True)
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        sb = select_sandbox(pi_binary="pi")
        assert isinstance(sb, ResourceCappedSandbox)
        assert isinstance(sb._inner, BwrapSandbox)

    def test_caps_param_flows_to_decorator(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: True)
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        caps = ResourceCaps(memory_max="1G", cpu_quota=None, tasks_max=64)
        sb = select_sandbox(pi_binary="pi", caps=caps)
        assert isinstance(sb, ResourceCappedSandbox)
        assert sb._caps is caps

    def test_raises_when_unavailable_and_no_override(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: False)
        monkeypatch.delenv("PI_ALLOW_UNSANDBOXED", raising=False)
        with pytest.raises(RuntimeError, match="PI_ALLOW_UNSANDBOXED"):
            select_sandbox(pi_binary="pi")

    def test_env_override_falls_back_to_null_with_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: False)
        monkeypatch.setenv("PI_ALLOW_UNSANDBOXED", "1")
        with caplog.at_level("WARNING", logger="pi_evaluator"):
            sb = select_sandbox(pi_binary="pi")
        assert isinstance(sb, NullSandbox)
        assert any("UNISOLATED" in r.message or "unsandboxed" in r.message.lower()
                   for r in caplog.records)

    def test_explicit_allow_param_overrides_env(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: False)
        monkeypatch.delenv("PI_ALLOW_UNSANDBOXED", raising=False)
        assert isinstance(
            select_sandbox(pi_binary="pi", allow_unsandboxed=True), NullSandbox
        )

    def test_explicit_allow_false_raises_despite_env(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: False)
        monkeypatch.setenv("PI_ALLOW_UNSANDBOXED", "1")
        with pytest.raises(RuntimeError):
            select_sandbox(pi_binary="pi", allow_unsandboxed=False)

    def test_unsandboxed_override_is_not_resource_capped(self, monkeypatch):
        """The explicit no-isolation escape hatch stays a bare NullSandbox —
        resource caps are tied to the bwrap path (ADR 0020 D2)."""
        monkeypatch.setattr(sandbox_mod, "bwrap_available", lambda *a, **k: False)
        monkeypatch.setenv("PI_ALLOW_UNSANDBOXED", "1")
        sb = select_sandbox(pi_binary="pi")
        assert isinstance(sb, NullSandbox)


# --- ResourceCaps ---------------------------------------------------


class TestResourceCaps:
    def test_default_caps_render_all_three_properties(self):
        props = ResourceCaps().to_properties()
        assert props == [
            "-p", "MemoryMax=4G",
            "-p", "CPUQuota=400%",
            "-p", "TasksMax=512",
        ]

    def test_none_fields_are_omitted(self):
        props = ResourceCaps(memory_max="2G", cpu_quota=None, tasks_max=None)
        assert props.to_properties() == ["-p", "MemoryMax=2G"]

    def test_all_none_renders_empty(self):
        assert ResourceCaps(None, None, None).to_properties() == []


# --- ResourceCappedSandbox ------------------------------------------


class TestResourceCappedSandbox:
    def test_satisfies_port(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        assert isinstance(ResourceCappedSandbox(NullSandbox()), SandboxPort)

    def test_prepends_systemd_run_scope_prefix(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        sb = ResourceCappedSandbox(
            NullSandbox(), caps=ResourceCaps(), scope_mode="user"
        )
        cmd = sb.wrap(["pi", "--print"], workspace=tmp_path).cmd
        assert cmd[0] == "systemd-run"
        assert "--user" in cmd
        assert "--scope" in cmd
        assert "MemoryMax=4G" in cmd
        # the inner (NullSandbox identity) command follows the `--` terminator
        sep = cmd.index("--")
        assert cmd[sep + 1 :] == ["pi", "--print"]

    def test_system_scope_mode_omits_user_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        sb = ResourceCappedSandbox(NullSandbox(), scope_mode="system")
        cmd = sb.wrap(["pi"], workspace=tmp_path).cmd
        assert "--user" not in cmd
        assert cmd[0] == "systemd-run"

    def test_wraps_inner_bwrap_command(self, monkeypatch, tmp_path):
        """The scope prefix sits *outside* the whole bwrap invocation."""
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        sb = ResourceCappedSandbox(
            BwrapSandbox(bwrap_binary="/usr/bin/bwrap"), scope_mode="system"
        )
        cmd = sb.wrap(["pi"], workspace=tmp_path).cmd
        assert cmd[0] == "systemd-run"
        # bwrap appears after the systemd-run `--`, and pi is last
        assert "/usr/bin/bwrap" in cmd
        assert cmd.index("systemd-run") < cmd.index("/usr/bin/bwrap")
        assert cmd[-1] == "pi"

    def test_preserves_cwd_and_env(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: True
        )
        env = {"PATH": "/usr/bin"}
        result = ResourceCappedSandbox(NullSandbox()).wrap(
            ["pi"], workspace=tmp_path, env=env
        )
        assert result.cwd == tmp_path
        assert result.env == env

    def test_degrades_to_inner_when_systemd_run_unavailable(
        self, monkeypatch, tmp_path, caplog
    ):
        monkeypatch.setattr(
            sandbox_mod, "systemd_run_available", lambda *a, **k: False
        )
        with caplog.at_level("WARNING", logger="pi_evaluator"):
            sb = ResourceCappedSandbox(NullSandbox())
        cmd = sb.wrap(["pi", "--print"], workspace=tmp_path).cmd
        assert cmd == ["pi", "--print"]  # unchanged — no scope prefix
        assert any("unenforced" in r.message for r in caplog.records)

    def test_probe_runs_once_at_construction_not_per_wrap(
        self, monkeypatch, tmp_path
    ):
        calls = {"n": 0}

        def _probe(*a, **k):
            calls["n"] += 1
            return True

        monkeypatch.setattr(sandbox_mod, "systemd_run_available", _probe)
        sb = ResourceCappedSandbox(NullSandbox())
        sb.wrap(["pi"], workspace=tmp_path)
        sb.wrap(["pi"], workspace=tmp_path)
        assert calls["n"] == 1


# --- systemd_run_available probe ------------------------------------


class TestSystemdRunAvailable:
    def test_false_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod.shutil, "which", lambda _: None)
        assert systemd_run_available("systemd-run") is False

    def test_real_probe_returns_bool_without_crashing(self):
        # host-dependent result; the contract is that the probe never raises
        assert isinstance(systemd_run_available(scope_mode="user"), bool)
