#!/usr/bin/env python3
"""
Configuration Deployment Script

One-shot deployment of the complete multiroom audio configuration.
Generates configs, installs them, restarts services, and configures
Snapcast groups via JSON-RPC API.

Deployment steps:
  1. Generate ALSA config (per-channel, room, and all_rooms PCM devices)
  2. Install to /etc/asound.conf (requires sudo)
  3. Generate Snapcast server config (stream sources)
  4. Install to /etc/snapserver.conf (requires sudo)
  5. Restart snapserver service
  6. Wait for snapclients to connect (timeout: 30s)
  7. Configure Snapcast groups via JSON-RPC API based on stream_targets

Prerequisites:
  - speaker_config.json must exist (run speaker_identify.py first)
  - sudo access for installing configs and restarting services
  - snapserver and snapclient services configured
  - Snapcast JSON-RPC API available on localhost:1705

Usage:
  python3 deploy_config.py

The script reads stream_targets from speaker_config.json to determine
which rooms should be assigned to which streams. Each stream target
specifies zones, which are resolved to rooms based on zone membership.

Example stream_targets in speaker_config.json:
  "stream_targets": {
    "spotify_lou": { "zones": ["kinderzimmer_lou"] },
    "spotify_alle": { "zones": ["alle"] }
  }

After deployment, test with:
  aplay -D room_<roomname> /usr/share/sounds/alsa/Front_Center.wav
"""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "speaker_config.json"
SNAPCAST_HOST = "localhost"
SNAPCAST_PORT = 1705  # TCP JSON-RPC port
SNAPSERVER_CONF = "/etc/snapserver.conf"
ASOUND_CONF = "/etc/asound.conf"


def load_config() -> dict:
    """Load speaker configuration from JSON."""
    if not CONFIG_FILE.exists():
        print(f"Error: {CONFIG_FILE} not found.")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def run_command(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command."""
    print(f"  Running: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def generate_alsa_config() -> str:
    """Generate ALSA configuration."""
    result = run_command(["python3", str(Path(__file__).parent / "generate_alsa_config.py")])
    return result.stdout


def generate_snapserver_config() -> str:
    """Generate Snapcast server configuration."""
    result = run_command(["python3", str(Path(__file__).parent / "generate_snapserver_conf.py")])
    return result.stdout


def install_config(content: str, path: str):
    """Install configuration file (requires sudo)."""
    print(f"  Installing {path}")
    proc = subprocess.Popen(
        ["sudo", "tee", path],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True
    )
    proc.communicate(input=content)
    if proc.returncode != 0:
        print(f"Error: Failed to install {path}")
        sys.exit(1)


def restart_snapserver():
    """Restart the snapserver service."""
    print("  Restarting snapserver...")
    run_command(["sudo", "systemctl", "restart", "snapserver"])
    time.sleep(2)  # Give it time to start


def snapcast_request(method: str, params: dict = None) -> dict:
    """Send a JSON-RPC request to Snapcast server."""
    request = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": method,
    }
    if params:
        request["params"] = params

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((SNAPCAST_HOST, SNAPCAST_PORT))
        sock.sendall((json.dumps(request) + "\r\n").encode())

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\r\n" in response:
                break

        sock.close()
        return json.loads(response.decode().strip())
    except Exception as e:
        print(f"  Snapcast API error: {e}")
        return None


def get_snapcast_status() -> dict:
    """Get current Snapcast server status."""
    response = snapcast_request("Server.GetStatus")
    if response and "result" in response:
        return response["result"]["server"]
    return None


def wait_for_clients(expected_rooms: list, timeout: int = 30) -> dict:
    """Wait for expected clients to connect."""
    print(f"  Waiting for {len(expected_rooms)} clients to connect...")

    start = time.time()
    while time.time() - start < timeout:
        status = get_snapcast_status()
        if not status:
            time.sleep(1)
            continue

        # Get all connected client names
        connected = set()
        for group in status.get("groups", []):
            for client in group.get("clients", []):
                config = client.get("config", {})
                name = config.get("name", "")
                if name:
                    connected.add(name)

        # Check if all expected rooms have clients
        missing = set(expected_rooms) - connected
        if not missing:
            print(f"  All {len(expected_rooms)} clients connected!")
            return status

        time.sleep(1)

    print(f"  Timeout waiting for clients. Missing: {missing}")
    return get_snapcast_status()


def resolve_stream_rooms(config: dict, stream_id: str) -> set:
    """Resolve which rooms should be assigned to a stream based on stream_targets."""
    stream_targets = config.get("snapcast", {}).get("stream_targets", {})
    zones = config.get("zones", {})
    rooms = config.get("rooms", {})

    targets = stream_targets.get(stream_id, {})
    target_zones = targets.get("zones", [])
    target_rooms = set(targets.get("rooms", []))

    # Resolve zones to rooms
    for zone_id in target_zones:
        zone_info = zones.get(zone_id, {})
        if zone_info.get("include_all"):
            return set(rooms.keys())
        # Find rooms in this zone
        for room_id, room_info in rooms.items():
            if zone_id in room_info.get("zones", []):
                target_rooms.add(room_id)

    return target_rooms


def configure_snapcast_groups(config: dict, status: dict):
    """Configure Snapcast groups based on stream_targets."""
    if not status:
        print("  No Snapcast status available, skipping group configuration")
        return

    rooms = config.get("rooms", {})
    streams = config.get("snapcast", {}).get("streams", {})

    # Build client -> group map
    client_to_group = {}
    for group in status.get("groups", []):
        for client in group.get("clients", []):
            client_id = client.get("id", "")
            client_to_group[client_id] = group["id"]

    # Build room -> stream map using stream_targets
    room_to_stream = {}
    for stream_id in streams.keys():
        target_rooms = resolve_stream_rooms(config, stream_id)
        for room_id in target_rooms:
            # Later streams override earlier ones (allows specific overrides)
            room_to_stream[room_id] = stream_id

    # For each room, assign to target stream
    print(f"\n  Assigning {len(rooms)} rooms to streams...")

    for room_id in rooms.keys():
        target_stream = room_to_stream.get(room_id, "default")

        # Find all clients for this room (including _left/_right for cross-device)
        room_clients = []
        for client_id in client_to_group.keys():
            if client_id == f"room_{room_id}" or client_id.startswith(f"room_{room_id}_"):
                room_clients.append(client_id)

        for client_id in room_clients:
            group_id = client_to_group.get(client_id)
            if group_id:
                snapcast_request("Group.SetStream", {"id": group_id, "stream_id": target_stream})
                print(f"    {client_id} -> {target_stream}")

    print("\n  Room assignment complete!")


def main():
    print("=" * 60)
    print("CONFIGURATION DEPLOYMENT")
    print("=" * 60)

    config = load_config()
    rooms = list(config.get("rooms", {}).keys())

    # Step 1: Generate and install ALSA config
    print("\n[1/5] Generating ALSA configuration...")
    alsa_config = generate_alsa_config()
    install_config(alsa_config, ASOUND_CONF)

    # Step 2: Generate and install Snapcast config
    print("\n[2/5] Generating Snapcast configuration...")
    snap_config = generate_snapserver_config()
    install_config(snap_config, SNAPSERVER_CONF)

    # Step 3: Restart snapserver
    print("\n[3/5] Restarting Snapcast server...")
    restart_snapserver()

    # Step 4: Wait for clients
    print("\n[4/5] Waiting for Snapcast clients...")
    expected_clients = [f"room_{room}" for room in rooms]
    status = wait_for_clients(expected_clients, timeout=30)

    # Step 5: Configure groups
    print("\n[5/5] Configuring Snapcast groups...")
    configure_snapcast_groups(config, status)

    print("\n" + "=" * 60)
    print("DEPLOYMENT COMPLETE")
    print("=" * 60)
    print("\nTest with:")
    for room in sorted(rooms)[:3]:
        print(f"  aplay -D room_{room} /usr/share/sounds/alsa/Front_Center.wav")
    print("  ...")


if __name__ == "__main__":
    main()
