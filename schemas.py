"""Tool schemas for the cua-driver-proot plugin.

Each schema is the JSON object hermes exposes to the LLM. The description
field is the single most important string here — it decides when the
agent reaches for the tool. Keep them specific.
"""

CUA_DRIVER_INSTALL = {
    "name": "cua_driver_install",
    "description": (
        "Install cua-driver-rs (the cua computer-use agent daemon) inside "
        "Termux's proot-distro ubuntu and wire up the Termux-side wrapper "
        "so `cua-driver` resolves on $PATH. Idempotent: re-running it "
        "upgrades cua-driver to the latest release. Use this when the "
        "user asks to set up desktop / X11 / computer-use automation on "
        "Termux, when `cua-driver` is missing, or when "
        "`⚠ computer_use (system dependency not met)` shows up in "
        "hermes's action-doctor log."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "description": (
                    "Optional cua-driver-rs version to pin (e.g. '0.6.2'). "
                    "Omit to install the latest release from GitHub."
                ),
            },
            "proot_distro": {
                "type": "string",
                "description": (
                    "Which proot-distro rootfs to install into. Default: 'ubuntu'."
                ),
                "default": "ubuntu",
            },
            "skip_apt": {
                "type": "boolean",
                "description": (
                    "If true, skip the apt-get install of X11/AT-SPI/D-Bus "
                    "libraries. Use when those packages are already installed."
                ),
                "default": False,
            },
        },
        "required": [],
    },
}

CUA_DRIVER_DOCTOR = {
    "name": "cua_driver_doctor",
    "description": (
        "Run a health report on the cua-driver-rs install. Reports binary "
        "version, install path, X11 connection (with on-screen window "
        "count), AT-SPI bus reachability, and shared-library status. Use "
        "this when something isn't working — first call in any "
        "investigation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "json": {
                "type": "boolean",
                "description": "If true, return the raw JSON output instead of a human summary.",
                "default": False,
            },
        },
        "required": [],
    },
}

CUA_DRIVER_UPGRADE = {
    "name": "cua_driver_upgrade",
    "description": (
        "Upgrade cua-driver-rs to the latest GitHub release inside "
        "proot-distro. Equivalent to re-running the install with no "
        "version pin. Use this when the user is on an old cua-driver and "
        "wants the new tool catalog, or when a security fix ships."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

CUA_DRIVER_ATSPI_SETUP = {
    "name": "cua_driver_atspi_setup",
    "description": (
        "Set up a D-Bus session inside the proot rootfs so AT-SPI (the "
        "Linux accessibility bus, equivalent to macOS AX) becomes "
        "reachable. Required for `get_window_state` — the AX tree walk "
        "that powers element-based clicks. After this, cua-driver can "
        "enumerate every interactable element in a window. Idempotent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "proot_distro": {
                "type": "string",
                "description": "Which proot-distro to set up. Default: 'ubuntu'.",
                "default": "ubuntu",
            },
        },
        "required": [],
    },
}


ALL_SCHEMAS = [
    CUA_DRIVER_INSTALL,
    CUA_DRIVER_DOCTOR,
    CUA_DRIVER_UPGRADE,
    CUA_DRIVER_ATSPI_SETUP,
]
