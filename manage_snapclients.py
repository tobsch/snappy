#!/usr/bin/env python3
"""
Snapclient Service Manager

Manages systemd snapclient services for all rooms defined in speaker_config.json.
"""

import json
import subprocess
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "speaker_config.json"
SERVICE_TEMPLATE = "snapclient@.service"
SERVICE_INSTALL_PATH = Path("/etc/systemd/system")


def load_config() -> dict:
    """Load speaker configuration from JSON."""
    if not CONFIG_FILE.exists():
        print(f"Error: {CONFIG_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_room_devices(config: dict) -> list[str]:
    """Get list of room ALSA device names."""
    rooms = config.get("rooms", {})
    return [f"room_{room_id}" for room_id in rooms.keys()]


def run_cmd(cmd: list[str], check: bool = True) -> bool:
    """Run a command and return success status."""
    try:
        subprocess.run(cmd, check=check, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Error: {e.stderr.strip()}", file=sys.stderr)
        return False


def install_service():
    """Install the systemd template service."""
    src = Path(__file__).parent / SERVICE_TEMPLATE
    dst = SERVICE_INSTALL_PATH / SERVICE_TEMPLATE

    if not src.exists():
        print(f"Error: {src} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Installing {SERVICE_TEMPLATE} to {SERVICE_INSTALL_PATH}...")
    subprocess.run(["sudo", "cp", str(src), str(dst)], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    print("Service template installed.")


def enable_all(config: dict):
    """Enable snapclient services for all rooms."""
    devices = get_room_devices(config)
    print(f"\nEnabling {len(devices)} snapclient services...")

    for device in devices:
        service = f"snapclient@{device}.service"
        print(f"  Enabling {service}...", end=" ")
        if run_cmd(["sudo", "systemctl", "enable", service]):
            print("OK")


def start_all(config: dict):
    """Start snapclient services for all rooms."""
    devices = get_room_devices(config)
    print(f"\nStarting {len(devices)} snapclient services...")

    for device in devices:
        service = f"snapclient@{device}.service"
        print(f"  Starting {service}...", end=" ")
        if run_cmd(["sudo", "systemctl", "start", service]):
            print("OK")


def stop_all(config: dict):
    """Stop snapclient services for all rooms."""
    devices = get_room_devices(config)
    print(f"\nStopping {len(devices)} snapclient services...")

    for device in devices:
        service = f"snapclient@{device}.service"
        print(f"  Stopping {service}...", end=" ")
        if run_cmd(["sudo", "systemctl", "stop", service], check=False):
            print("OK")


def disable_all(config: dict):
    """Disable snapclient services for all rooms."""
    devices = get_room_devices(config)
    print(f"\nDisabling {len(devices)} snapclient services...")

    for device in devices:
        service = f"snapclient@{device}.service"
        print(f"  Disabling {service}...", end=" ")
        if run_cmd(["sudo", "systemctl", "disable", service], check=False):
            print("OK")


def restart_all(config: dict):
    """Restart snapclient services for all rooms."""
    devices = get_room_devices(config)
    print(f"\nRestarting {len(devices)} snapclient services...")

    for device in devices:
        service = f"snapclient@{device}.service"
        print(f"  Restarting {service}...", end=" ")
        if run_cmd(["sudo", "systemctl", "restart", service]):
            print("OK")


def status_all(config: dict):
    """Show status of all snapclient services."""
    devices = get_room_devices(config)
    print(f"\nStatus of {len(devices)} snapclient services:\n")

    for device in devices:
        service = f"snapclient@{device}.service"
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True
        )
        status = result.stdout.strip()
        symbol = "●" if status == "active" else "○"
        print(f"  {symbol} {service}: {status}")


def print_usage():
    print("""
Snapclient Service Manager

Usage: python3 manage_snapclients.py <command>

Commands:
  install   Install the systemd template service
  enable    Enable services for all rooms (auto-start on boot)
  start     Start services for all rooms
  stop      Stop services for all rooms
  restart   Restart services for all rooms
  disable   Disable services for all rooms
  status    Show status of all services
  setup     Full setup: install + enable + start

Examples:
  python3 manage_snapclients.py setup     # First-time setup
  python3 manage_snapclients.py restart   # After config changes
  python3 manage_snapclients.py status    # Check what's running
""")


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()
    config = load_config()

    if command == "install":
        install_service()
    elif command == "enable":
        enable_all(config)
    elif command == "start":
        start_all(config)
    elif command == "stop":
        stop_all(config)
    elif command == "restart":
        restart_all(config)
    elif command == "disable":
        disable_all(config)
    elif command == "status":
        status_all(config)
    elif command == "setup":
        install_service()
        enable_all(config)
        start_all(config)
        print("\nSetup complete!")
        status_all(config)
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
