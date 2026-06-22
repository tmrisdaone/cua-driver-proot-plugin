"""Tool handlers for the cua-driver-proot plugin.

Each handler receives ``args`` (the parameters the LLM passed) plus any
forward-compat kwargs, and returns a JSON string. Errors are returned as
JSON too — never raise to the LLM unless something is truly unrecoverable
in a way the model can't act on (missing proot, missing $HOME, etc.).

Implementation strategy: delegate to the bundled ``install.sh`` (for
install/upgrade) or to ``cua-driver`` on $PATH (for doctor). No
subprocess is called via python's subprocess module unless the LLM is
asking for something it can't synthesize — long-running installs benefit
from a shell that can stream output.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from typing import Any, Callable

from .schemas import ALL_SCHEMAS

logger = __import__("logging").getLogger("cua_driver_proot.tools")

TOOLSET = "cua_driver"


# ---------------------------------------------------------------- helpers ---

def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """Run a subprocess, capture stdout+stderr, return (rc, stdout, stderr)."""
    try:
        cp = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}"


def _ensure_termux_preflight() -> str | None:
    """Return an error JSON string if the host isn't Termux / proot-ready.

    Used by every tool. If the host is plain Linux (not Termux) the
    install path still works — the user just needs to install proot
    themselves. We refuse to run on non-Linux entirely.
    """
    if os.name == "nt":
        return json.dumps({"error": "Windows is not supported. Use WSL."})
    if not shutil.which("proot-distro"):
        return json.dumps({
            "error": "proot-distro is not installed. Run: pkg install proot-distro",
            "hint": "If you're on plain Linux, install proot via your package manager.",
        })
    return None


# ----------------------------------------------------------------- tools ---

def cua_driver_install(args: dict, **_kwargs) -> str:
    """Run the bundled install script. Streams output to stderr.

    The script lives alongside the plugin as ``install.sh`` — but for
    a one-shot install from a fresh proot-distro, the user typically
    reaches the script via the one-liner in SKILL.md. This tool is for
    when hermes is asked to install/uninstall/upgrade cua-driver.
    """
    err = _ensure_termux_preflight()
    if err:
        return err

    version = args.get("version") or ""
    proot_distro = args.get("proot_distro") or "ubuntu"
    skip_apt = bool(args.get("skip_apt"))

    # Find the bundled install.sh — walk up from this file's location.
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.normpath(os.path.join(here, "..", "install.sh")),
        os.path.normpath(os.path.join(here, "..", "..", "install.sh")),
        os.path.expanduser("~/tmp/cua-driver-proot/install.sh"),
    ]
    install_sh = next((c for c in candidates if os.path.isfile(c)), None)
    if not install_sh:
        return json.dumps({
            "error": "install.sh not found alongside the plugin",
            "searched": candidates,
            "hint": "Run the one-liner: curl -fsSL "
                    "https://raw.githubusercontent.com/tmrisdaone/hermes-skills/"
                    "main/cua-driver-proot/install.sh | bash",
        })

    cmd = ["bash", install_sh]
    env = os.environ.copy()
    if version:
        env["CUA_DRIVER_RS_VERSION"] = version
    env["PROOT_DISTRO"] = proot_distro
    if skip_apt:
        env["SKIP_APT"] = "1"

    # Stream install progress to hermes's tool output. Long install
    # (~30-60s on a slow phone for the apt step) — give it room.
    try:
        cp = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "install timed out after 600s"})

    out = (cp.stdout or "") + (cp.stderr or "")
    ok = cp.returncode == 0
    return json.dumps({
        "ok": ok,
        "exit_code": cp.returncode,
        "version_pinned": version or "latest",
        "proot_distro": proot_distro,
        "output_tail": out[-2000:] if len(out) > 2000 else out,
    })


def cua_driver_doctor(args: dict, **_kwargs) -> str:
    """Run `cua-driver doctor` and return a structured summary."""
    err = _ensure_termux_preflight()
    if err:
        return err

    want_json = bool(args.get("json"))
    if not shutil.which("cua-driver"):
        return json.dumps({
            "ok": False,
            "error": "cua-driver not found on $PATH",
            "hint": "Run the install tool first, or "
                    "curl -fsSL https://raw.githubusercontent.com/tmrisdaone/"
                    "hermes-skills/main/cua-driver-proot/install.sh | bash",
        })

    cmd = ["cua-driver", "doctor"]
    if want_json:
        cmd.append("--json")
    rc, out, errout = _run(cmd, timeout=15)

    raw = (out or "") + (errout or "")
    # Parse the [ok] / [warn] / [err] lines for a structured view.
    summary = {"ok": rc == 0, "exit_code": rc, "checks": []}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        if "[ok  ]" in line:
            summary["checks"].append({"status": "ok", "message": line.split("]", 1)[-1].strip()})
        elif "[warn]" in line:
            summary["checks"].append({"status": "warn", "message": line.split("]", 1)[-1].strip()})
        elif "[err ]" in line or "[fail]" in line:
            summary["checks"].append({"status": "error", "message": line.split("]", 1)[-1].strip()})
    summary["raw_output"] = raw
    return json.dumps(summary)


def cua_driver_upgrade(args: dict, **_kwargs) -> str:
    """Upgrade = install without a pinned version. Reuses cua_driver_install."""
    return cua_driver_install({"version": "", "proot_distro": "ubuntu", "skip_apt": True}, **_kwargs)


def cua_driver_atspi_setup(args: dict, **_kwargs) -> str:
    """Start a D-Bus session inside proot so AT-SPI becomes reachable.

    Strategy: install dbus + at-spi2-core (already done by install.sh),
    then drop a small wrapper script at /usr/local/bin/cua-driver-with-atspi
    inside proot that wraps the binary with `dbus-run-session --`. The
    agent (and the user) can then call that wrapper instead of the
    plain `cua-driver` for the AX-tree-walking tools.
    """
    err = _ensure_termux_preflight()
    if err:
        return err

    proot_distro = args.get("proot_distro") or "ubuntu"
    wrapper_inner = "/usr/local/bin/cua-driver-with-atspi"

    # Write the in-proot wrapper. Idempotent — overwrites the file each
    # time so a re-run picks up any new flags.
    rc, out, errout = _run([
        "proot-distro", "login", proot_distro, "--shared-tmp", "--",
        "bash", "-c", f"""
            set -e
            cat > {wrapper_inner} <<'EOF'
#!/usr/bin/env bash
# Run cua-driver-rs inside a fresh D-Bus session so AT-SPI can be
# reached. Required for the AX-tree walking tools (get_window_state
# etc.) — without a session bus, at-spi2-core has nowhere to announce.
exec dbus-run-session -- env DISPLAY="${{DISPLAY:-:0}}" XDG_RUNTIME_DIR=/tmp \\
    /usr/local/bin/cua-driver "$@"
EOF
chmod +x {wrapper_inner}
echo "wrote {wrapper_inner}"
""",
    ], timeout=30)

    if rc != 0:
        return json.dumps({
            "ok": False,
            "exit_code": rc,
            "error": "failed to write in-proot wrapper",
            "stderr": errout,
        })

    # Also write a Termux-side wrapper that calls the in-proot one.
    termux_wrapper = "/data/data/com.termux/files/usr/bin/cua-driver-with-atspi"
    termux_wrapper_content = f"""#!/usr/bin/env bash
# Termux-side wrapper for the in-proot dbus-run-session entry point.
# Use this instead of plain `cua-driver` for AX-tree walks.
[ -n "${{DISPLAY:-}}" ] || export DISPLAY=:0
exec proot-distro login {proot_distro} --shared-tmp -- env \\
    DISPLAY="${{DISPLAY:-:0}}" XDG_RUNTIME_DIR=/tmp HOME=/root \\
    {wrapper_inner} "$@"
"""
    try:
        with open(termux_wrapper, "w") as f:
            f.write(termux_wrapper_content)
        os.chmod(termux_wrapper, 0o755)
    except OSError as e:
        return json.dumps({
            "ok": False,
            "error": f"failed to write {termux_wrapper}: {e}",
        })

    return json.dumps({
        "ok": True,
        "proot_distro": proot_distro,
        "in_proot_wrapper": wrapper_inner,
        "termux_wrapper": termux_wrapper,
        "usage": "cua-driver-with-atspi mcp   # instead of `cua-driver mcp`",
        "note": "Restart the MCP session to pick up AT-SPI — the bus is "
                "tied to the daemon's lifetime.",
    })


# ----------------------------------------------------- tool registration ---

def register_tools(detect_environment: Callable[[], dict] | None = None) -> list[str]:
    """Register all four tools with hermes's tool registry.

    Returns the list of registered tool names. Logs (does not raise) on
    failure so a partial install doesn't break the rest of hermes.
    """
    try:
        from tools.registry import register_tool  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover — hermes not on path
        logger.debug("cua_driver_proot: tools.registry import failed: %s", exc)
        return []

    handlers: dict[str, Callable[..., str]] = {
        "cua_driver_install":     cua_driver_install,
        "cua_driver_doctor":      cua_driver_doctor,
        "cua_driver_upgrade":     cua_driver_upgrade,
        "cua_driver_atspi_setup": cua_driver_atspi_setup,
    }
    registered: list[str] = []
    for schema in ALL_SCHEMAS:
        name = schema["name"]
        handler = handlers.get(name)
        if not handler:
            continue
        try:
            register_tool(
                name=name,
                description=schema["description"],
                parameters=schema["parameters"],
                handler=handler,
                toolset=TOOLSET,
            )
            registered.append(name)
            logger.info("cua_driver_proot: registered %s in toolset %s", name, TOOLSET)
        except Exception as exc:  # pragma: no cover
            logger.warning("cua_driver_proot: failed to register %s: %s", name, exc)
    return registered
