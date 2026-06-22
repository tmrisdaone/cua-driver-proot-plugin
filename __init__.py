"""cua-driver-proot plugin.

Lets Hermes self-install, diagnose, and upgrade cua-driver-rs inside the
proot-distro ubuntu rootfs so the existing ``computer_use`` toolset can
drive an X11 desktop from a phone.

The plugin is the runtime half; the recipe and the one-line installer
live in the bundled ``cua-driver-proot`` skill (see SKILL.md).

The four tools provided by this plugin:

* ``cua_driver_install``     — apt deps + binary download + wrapper write
* ``cua_driver_doctor``      — health report (binary / X11 / AT-SPI / lib)
* ``cua_driver_upgrade``     — upgrade to the latest cua-driver-rs release
* ``cua_driver_atspi_setup`` — start a D-Bus session inside proot so
                                ``get_window_state`` (the AX tree walk)
                                becomes available

What the plugin does NOT do, deliberately:

* It does not monkey-patch the bundled ``CuaDriverBackend.is_available``
  to return True on Linux. That would violate the AGENTS.md rule
  "plugins don't touch core files". Instead, see the SKILL.md section
  on making hermes's ``computer_use`` toolset use the daemon — it's a
  one-line config change.
* It does not run a long-lived ``cua-driver serve`` TCP daemon. The MCP
  stdio transport is invoked per turn by hermes and that's the path of
  least surprise.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any

logger = logging.getLogger("cua_driver_proot")

# Tools are registered at import time so the plugin manager picks them up
# during discovery. See schemas.py + tools.py for the actual contracts.
try:
    from . import tools as _tools  # noqa: F401
    from .tools import register_tools as _register_tools
except ImportError:  # pragma: no cover — flat install fallback
    import tools as _tools  # type: ignore[no-redef]  # noqa: F401
    from tools import register_tools as _register_tools  # type: ignore[no-redef]


def _detect_environment() -> dict:
    """Best-effort snapshot of the host. Returned by ``cua_driver_doctor``."""
    return {
        "proot_distro_available": bool(shutil.which("proot-distro")),
        "cua_driver_on_path": bool(shutil.which("cua-driver")),
        "termux_x11_socket": bool(
            shutil.which("termux-x11")
            or __import__("os").path.exists(
                "/data/data/com.termux/files/usr/tmp/.X11-unix/X0"
            )
        ),
        "is_termux": bool(__import__("os").environ.get("TERMUX_VERSION")),
    }


# Auto-register tools on import so the plugin manager sees them.
try:
    _register_tools(_detect_environment)
except Exception as exc:  # pragma: no cover
    logger.warning("cua-driver-proot: tool registration failed: %s", exc)
