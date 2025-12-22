#!/usr/bin/env python3
"""
Snapcast Server Configuration Generator

Reads ../speaker_config.json (v2.0 format) and generates snapserver.conf with:
- Multiple stream sources (pipe, librespot, airplay, etc.)
- Configured for the defined Spotify and AirPlay instances
"""

import json
import sys
import urllib.parse
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "speaker_config.json"


def load_config() -> dict:
    """Load speaker configuration from JSON."""
    if not CONFIG_FILE.exists():
        print(f"Error: {CONFIG_FILE} not found.", file=sys.stderr)
        print("Run speaker_identify.py first to create the configuration.", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    if config.get("version") != "2.0":
        print("Error: Config file is not v2.0 format.", file=sys.stderr)
        print("Run speaker_identify.py to upgrade the configuration.", file=sys.stderr)
        sys.exit(1)

    return config


def generate_stream_source(stream_id: str, stream_config: dict, config: dict) -> str:
    """Generate a source line for snapserver.conf."""
    stream_type = stream_config.get("type", "pipe")
    name = stream_config.get("name", stream_id)

    # Generate a user-friendly display name for Snapcast based on stream type
    # This appears in Snapcast clients/web UI
    if stream_type == "librespot":
        stream_name = f"Spotify {name}"
    elif stream_type == "airplay":
        stream_name = f"AirPlay {name}"
    elif stream_type == "pipe" and stream_id == "default":
        stream_name = "Default"
    else:
        stream_name = name if name != stream_id else stream_id

    # URL-encode the stream name for use in source URI
    encoded_stream_name = urllib.parse.quote(stream_name, safe='')

    if stream_type == "pipe":
        path = stream_config.get("path", f"/tmp/snapfifo_{stream_id}")
        sampleformat = stream_config.get("sampleformat", "48000:16:2")
        codec = stream_config.get("codec", "flac")
        return f"source = pipe://{path}?name={encoded_stream_name}&sampleformat={sampleformat}&codec={codec}"

    elif stream_type == "librespot":
        bitrate = stream_config.get("bitrate", 320)
        device_name = stream_config.get("name", stream_id)
        initial_volume = stream_config.get("initial_volume", 50)
        # Cache directory for storing Spotify credentials after first login
        cache_dir = stream_config.get("cache", f"/var/cache/snapserver/librespot-{stream_id}")
        # librespot streams use the meta stream type in newer snapcast versions
        # but the librespot source type for direct integration
        # Use 320kbps for best quality, 44100 Hz (Spotify's native format)
        return f"source = librespot:///librespot?name={encoded_stream_name}&devicename={device_name}&bitrate=320&cache={cache_dir}&volume={initial_volume}&sampleformat=44100:16:2"

    elif stream_type == "airplay":
        device_name = stream_config.get("name", stream_id)
        # AirPlay 2 uses port 7000+ (classic AirPlay uses 5000)
        port = stream_config.get("port", 7000)
        shairport_path = stream_config.get("shairport_path", "/usr/local/bin/shairport-sync")
        # Each AirPlay 2 instance needs a unique device ID offset
        device_id_offset = stream_config.get("device_id_offset", 0)
        config_file = stream_config.get("config_file", "")

        if config_file:
            # Use process source with explicit config file for unique device IDs
            params = f"-c {config_file} -o stdout -a \"{device_name}\" -p {port}"
            encoded_params = urllib.parse.quote(params, safe='')
            return f"source = process://{shairport_path}?name={encoded_stream_name}&params={encoded_params}"
        else:
            # Fallback to native airplay source (single instance only)
            return f"source = airplay://{shairport_path}?name={encoded_stream_name}&devicename={device_name}&port={port}&coverart=false"

    elif stream_type == "process":
        path = stream_config.get("path", "")
        params = stream_config.get("params", "")
        return f"source = process://{path}?name={encoded_stream_name}&params={params}"

    elif stream_type == "tcp":
        host = stream_config.get("host", "0.0.0.0")
        port = stream_config.get("port", 4953)
        mode = stream_config.get("mode", "server")
        return f"source = tcp://{host}:{port}?name={encoded_stream_name}&mode={mode}"

    elif stream_type == "alsa":
        # Look up input from inputs section if specified
        input_id = stream_config.get("input")
        if input_id:
            inputs = config.get("inputs", {})
            input_config = inputs.get(input_id, {})
            device = f"hw:{input_config.get('card', input_id)}"
            # Use input's display name if stream doesn't have one
            if name == stream_id:
                name = input_config.get("name", stream_id)
                encoded_stream_name = urllib.parse.quote(name, safe='')
            # Use sampleformat from input config, then stream config, then default
            sampleformat = stream_config.get("sampleformat", input_config.get("sampleformat", "48000:16:2"))
        else:
            device = stream_config.get("device", "default")
            sampleformat = stream_config.get("sampleformat", "48000:16:2")
        # ALSA source format: alsa://?device=<dev>&name=<name>&sampleformat=<fmt>
        return f"source = alsa://?name={encoded_stream_name}&device={device}&sampleformat={sampleformat}"

    else:
        print(f"Warning: Unknown stream type '{stream_type}' for {stream_id}", file=sys.stderr)
        return f"# Unknown type: {stream_type} for {stream_id}"


def generate_snapserver_conf(config: dict) -> str:
    """Generate complete snapserver.conf content."""
    snapcast = config.get("snapcast", {})
    streams = snapcast.get("streams", {})

    output = """###############################################################################
#     ______                                                                  #
#    / _____)                                                                 #
#   ( (____   ____   _____  ____    ___  _____   ____  _   _  _____   ____    #
#    \\____ \\ |  _ \\ (____ ||  _ \\  /___)| ___ | / ___)| | | || ___ | / ___)   #
#    _____) )| | | |/ ___ || |_| ||___ || ____|| |     \\ V / | ____|| |       #
#   (______/ |_| |_|\\_____||  __/ (___/ |_____)|_|      \\_/  |_____)|_|       #
#                          |_|                                                #
#                                                                             #
#  Snapserver configuration - AUTO-GENERATED by generate_snapserver_conf.py  #
#                                                                             #
###############################################################################

# General server settings
[server]
# Number of threads to use (0 = auto)
threads = -1

# Logging
[logging]
# Log level: trace, debug, info, notice, warning, error, fatal
filter = *:info

# HTTP / Websocket / JSON-RPC settings
[http]
enabled = true
bind_to_address = 0.0.0.0
port = 1780
# Serve static web content
doc_root = /usr/share/snapserver/snapweb

# TCP JSON-RPC settings
[tcp]
enabled = true
bind_to_address = 0.0.0.0
port = 1705

# Stream settings
[stream]
# Default sample format
sampleformat = 48000:16:2
# Default codec (flac, ogg, opus, pcm)
codec = flac
# Buffer size in ms
buffer = 200
# Chunk size in ms
chunk_ms = 26
# Send audio to muted clients
send_to_muted = false

"""

    # Generate source lines for each stream
    output += "# Stream sources\n"
    for stream_id in sorted(streams.keys()):
        stream_config = streams[stream_id]
        source_line = generate_stream_source(stream_id, stream_config, config)
        output += f"{source_line}\n"

    return output


def print_stream_targets(config: dict):
    """Print stream target mappings for reference."""
    snapcast = config.get("snapcast", {})
    stream_targets = snapcast.get("stream_targets", {})
    zones = config.get("zones", {})
    rooms = config.get("rooms", {})

    print("\n" + "=" * 50, file=sys.stderr)
    print("STREAM TARGET MAPPINGS", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("\nUse these mappings to configure Snapcast groups via JSON-RPC:\n", file=sys.stderr)

    for stream_id, targets in sorted(stream_targets.items()):
        target_zones = targets.get("zones", [])
        target_rooms = targets.get("rooms", [])

        # Resolve zones to rooms
        resolved_rooms = set(target_rooms)
        for zone_id in target_zones:
            zone_info = zones.get(zone_id, {})
            if zone_info.get("include_all"):
                resolved_rooms = set(rooms.keys())
                break
            # Find rooms in this zone
            for room_id, room_info in rooms.items():
                if zone_id in room_info.get("zones", []):
                    resolved_rooms.add(room_id)

        print(f"  {stream_id}:", file=sys.stderr)
        if target_zones:
            print(f"    zones: {', '.join(target_zones)}", file=sys.stderr)
        print(f"    rooms: {', '.join(sorted(resolved_rooms))}", file=sys.stderr)


def main():
    print("=" * 50, file=sys.stderr)
    print("SNAPSERVER CONFIGURATION GENERATOR", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    config = load_config()
    snapcast = config.get("snapcast", {})
    streams = snapcast.get("streams", {})

    if not streams:
        print("No Snapcast streams configured!", file=sys.stderr)
        sys.exit(1)

    print(f"\nGenerating config for {len(streams)} stream(s)...\n", file=sys.stderr)

    # Count stream types
    type_counts = {}
    for stream_id, stream_config in streams.items():
        stream_type = stream_config.get("type", "pipe")
        type_counts[stream_type] = type_counts.get(stream_type, 0) + 1
        stream_name = stream_config.get("name", stream_id)
        print(f"  {stream_id}: {stream_type} ({stream_name})", file=sys.stderr)

    # Generate and print config
    output = generate_snapserver_conf(config)
    print(output)

    # Print stream targets
    print_stream_targets(config)

    print("\n" + "=" * 50, file=sys.stderr)
    print("USAGE:", file=sys.stderr)
    print("  Save to snapserver.conf:", file=sys.stderr)
    print("    python3 generate_snapserver_conf.py > /etc/snapserver.conf", file=sys.stderr)
    print("\n  Or append streams to existing config:", file=sys.stderr)
    print("    python3 generate_snapserver_conf.py | grep '^source' >> /etc/snapserver.conf", file=sys.stderr)
    print("\n  Restart snapserver:", file=sys.stderr)
    print("    sudo systemctl restart snapserver", file=sys.stderr)
    print("=" * 50, file=sys.stderr)


if __name__ == "__main__":
    main()
