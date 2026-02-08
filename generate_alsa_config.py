#!/usr/bin/env python3
"""
ALSA Configuration Generator for Wondom Speaker Setup

Reads ../speaker_config.json (v2.0 format) and generates ALSA configuration with:
- Base amplifier PCM definitions (amp1, amp2, etc.)
- Stereo PCM devices for each room (room_XXX)
- Combined all_rooms output for testing
- Support for cross-device stereo pairs using ALSA multi plugin

Note: Zones are handled by Snapcast, not ALSA.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# ALSA card name suffix pattern: GAB8, GAB8_1, GAB8_2, etc.
def get_alsa_card_name(base_card: str, index: int) -> str:
    """Get ALSA card name for nth device of same type."""
    if index == 0:
        return base_card
    return f"{base_card}_{index}"

CONFIG_FILE = Path(__file__).parent / "speaker_config.json"

# Default max volume coefficient (0.0-1.0)
DEFAULT_MAX_VOLUME = 0.5


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


def get_max_volume(config: dict) -> float:
    """Get max volume coefficient from global config."""
    return config.get("global", {}).get("max_volume", DEFAULT_MAX_VOLUME)


def generate_amplifier_config(config: dict) -> str:
    """Generate base PCM definitions for all amplifiers."""
    amplifiers = config.get("amplifiers", {})
    max_vol = get_max_volume(config)
    if not amplifiers:
        return ""

    # Group amps by card type to handle multiple devices of same type
    card_counts = defaultdict(int)
    amp_cards = {}

    for amp_name in sorted(amplifiers.keys()):
        amp = amplifiers[amp_name]
        base_card = amp.get("card", "GAB8")
        alsa_card = get_alsa_card_name(base_card, card_counts[base_card])
        card_counts[base_card] += 1
        amp_cards[amp_name] = alsa_card

    output = """
#########################################
# AMPLIFIER DEFINITIONS
#########################################
"""

    for amp_name in sorted(amplifiers.keys()):
        amp = amplifiers[amp_name]
        alsa_card = amp_cards[amp_name]
        channels = amp.get("channels", 8)

        output += f"""
# {amp_name} - {alsa_card} ({channels} channels)
pcm.{amp_name} {{
    type hw
    card {alsa_card}
    device 0
}}

pcm.{amp_name}_dmix {{
    type dmix
    ipc_key 10{amp_name[-1] if amp_name[-1].isdigit() else '0'}
    ipc_perm 0666
    slave {{
        pcm "{amp_name}"
        channels {channels}
        rate 48000
        period_size 2048
        buffer_size 16384
    }}
}}
"""
        # Generate per-channel devices for speaker identification (uses dmix for concurrent access)
        for ch in range(1, channels + 1):
            ch_idx = ch - 1  # 0-based for ALSA ttable
            output += f"""
pcm.{amp_name}_ch{ch}_raw {{
    type route
    slave.pcm "{amp_name}_dmix"
    slave.channels {channels}
    ttable.0.{ch_idx} {max_vol}
    ttable.1.{ch_idx} {max_vol}
}}

pcm.{amp_name}_ch{ch} {{
    type plug
    slave.pcm "{amp_name}_ch{ch}_raw"
}}
"""

    return output, amp_cards


def get_speaker_info(config: dict, speaker_name: str, max_vol: float) -> dict:
    """Get full speaker info including amplifier details."""
    if not speaker_name or speaker_name not in config["speakers"]:
        return None

    speaker = config["speakers"][speaker_name]
    amp_name = speaker["amplifier"]
    amp = config["amplifiers"].get(amp_name, {})

    # Calculate effective volume: speaker volume (0-100) * global max_volume
    speaker_vol = speaker.get("volume", 100) / 100.0
    effective_vol = speaker_vol * max_vol

    return {
        "amplifier": amp_name,
        "card": amp.get("card", ""),
        "channel": speaker["channel"],
        "volume": effective_vol
    }


def get_room_speakers(config: dict, max_vol: float) -> dict:
    """Get speaker pairs for each room."""
    rooms = {}

    for room_id, room_info in config["rooms"].items():
        left_info = get_speaker_info(config, room_info.get("left"), max_vol)
        right_info = get_speaker_info(config, room_info.get("right"), max_vol)

        if left_info or right_info:
            rooms[room_id] = {
                "name": room_info.get("name", room_id),
                "left": left_info,
                "right": right_info,
                "zones": room_info.get("zones", [])
            }

    return rooms


def generate_same_device_config(room_id: str, left: dict, right: dict) -> str:
    """Generate ALSA config for stereo pair on same device."""
    device = left["amplifier"]
    left_ch = left["channel"] - 1  # Convert to 0-based
    right_ch = right["channel"] - 1
    left_vol = left["volume"]
    right_vol = right["volume"]

    # Use dmix to allow concurrent access from multiple snapclients
    # Note: internal routing device uses _internal_ prefix to avoid snapclient substring matching
    return f"""
#########
# room_{room_id} - Stereo (same device: {device})
#########

pcm._internal_{room_id} {{
    type route
    slave.pcm "{device}_dmix"
    slave.channels 8
    ttable.0.{left_ch} {left_vol}
    ttable.1.{right_ch} {right_vol}
}}

pcm.room_{room_id} {{
    type plug
    slave.pcm "_internal_{room_id}"
}}
"""


def generate_cross_device_config(room_id: str, left: dict, right: dict) -> str:
    """Generate ALSA config for stereo pair across different devices.

    Creates two separate mono devices for left and right speakers.
    Requires two snapclient instances per room for proper playback.
    """
    left_device = left["amplifier"]
    right_device = right["amplifier"]
    left_ch = left["channel"] - 1  # Convert to 0-based
    right_ch = right["channel"] - 1
    left_vol = left["volume"]
    right_vol = right["volume"]

    # Note: internal routing devices use _internal_ prefix to avoid snapclient substring matching
    # Individual speaker devices use speaker_ prefix to avoid sendspin prefix-matching room_{room_id}
    return f"""
#########
# room_{room_id} - Cross-device stereo: {left_device} ch{left_ch+1} + {right_device} ch{right_ch+1}
# Use speaker_{room_id}_left and speaker_{room_id}_right with separate snapclients
#########

pcm._internal_{room_id}_left {{
    type route
    slave.pcm "{left_device}_dmix"
    slave.channels 8
    ttable.0.{left_ch} {left_vol}
    ttable.1.{left_ch} {left_vol}
}}

pcm.speaker_{room_id}_left {{
    type plug
    slave.pcm "_internal_{room_id}_left"
}}

pcm._internal_{room_id}_right {{
    type route
    slave.pcm "{right_device}_dmix"
    slave.channels 8
    ttable.0.{right_ch} {right_vol}
    ttable.1.{right_ch} {right_vol}
}}

pcm.speaker_{room_id}_right {{
    type plug
    slave.pcm "_internal_{room_id}_right"
}}

# Combined device for testing (mono mix to left speaker only)
pcm.room_{room_id} {{
    type plug
    slave.pcm "_internal_{room_id}_left"
}}
"""


def generate_mono_config(room_id: str, speaker: dict, position: str) -> str:
    """Generate ALSA config for mono speaker (missing left or right)."""
    device = speaker["amplifier"]
    channel = speaker["channel"] - 1  # Convert to 0-based
    vol = speaker["volume"]

    # Use dmix to allow concurrent access from multiple snapclients
    # Note: internal routing device uses _internal_ prefix to avoid snapclient substring matching
    return f"""
#########
# room_{room_id} - Mono ({position} only on {device})
#########

pcm._internal_{room_id} {{
    type route
    slave.pcm "{device}_dmix"
    slave.channels 8
    ttable.0.{channel} {vol}
    ttable.1.{channel} {vol}
}}

pcm.room_{room_id} {{
    type plug
    slave.pcm "_internal_{room_id}"
}}
"""


def generate_all_rooms_config(rooms: dict) -> str:
    """Generate a combined stereo device that plays to all rooms."""
    if not rooms:
        return ""

    # Collect all unique devices and their channel mappings
    device_channels = defaultdict(list)
    for room_id, room in rooms.items():
        if room["left"]:
            device_channels[room["left"]["amplifier"]].append({
                "channel": room["left"]["channel"] - 1,
                "stereo_pos": 0
            })
        if room["right"]:
            device_channels[room["right"]["amplifier"]].append({
                "channel": room["right"]["channel"] - 1,
                "stereo_pos": 1
            })

    if len(device_channels) == 1:
        # All on one device - use route with dmix
        device = list(device_channels.keys())[0]
        channels = device_channels[device]

        ttable_lines = []
        for ch_info in channels:
            ttable_lines.append(f"    ttable.{ch_info['stereo_pos']}.{ch_info['channel']} 1")

        ttable = "\n".join(sorted(set(ttable_lines)))

        return f"""
#########
# all_rooms - Play stereo to all configured speakers
#########

pcm.all_rooms_raw {{
    type route
    slave.pcm "{device}_dmix"
    slave.channels 8
{ttable}
}}

pcm.all_rooms {{
    type plug
    slave.pcm "all_rooms_raw"
}}
"""
    else:
        # Multi-device setup with dmix for concurrent access
        slaves = []
        bindings = []
        binding_idx = 0

        for i, (device, channels) in enumerate(sorted(device_channels.items())):
            slave_letter = chr(ord('a') + i)
            slaves.append(f'    slaves.{slave_letter}.pcm "{device}_dmix"')
            slaves.append(f'    slaves.{slave_letter}.channels 8')

            for ch_info in channels:
                bindings.append(f'    bindings.{binding_idx}.slave {slave_letter}')
                bindings.append(f'    bindings.{binding_idx}.channel {ch_info["channel"]}')
                binding_idx += 1

        slaves_str = "\n".join(slaves)
        bindings_str = "\n".join(bindings)

        return f"""
#########
# all_rooms - Play stereo to all configured speakers (multi-device)
#########

pcm.all_rooms_multi {{
    type multi
{slaves_str}
{bindings_str}
}}

pcm.all_rooms {{
    type plug
    slave.pcm "all_rooms_multi"
}}
"""


def main():
    print("=" * 50, file=sys.stderr)
    print("ALSA CONFIGURATION GENERATOR", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    config = load_config()
    max_vol = get_max_volume(config)
    rooms = get_room_speakers(config, max_vol)

    if not rooms:
        print("No rooms configured!", file=sys.stderr)
        sys.exit(1)

    amplifiers = config.get("amplifiers", {})
    print(f"\nGenerating config for {len(amplifiers)} amplifier(s) and {len(rooms)} room(s)...", file=sys.stderr)
    print(f"Global max volume: {max_vol} ({max_vol*100:.0f}%)\n", file=sys.stderr)

    # Generate header
    output = """
#########################################
# AUTO-GENERATED WONDOM SPEAKER CONFIG
# Generated by generate_alsa_config.py
#########################################
"""

    # Generate amplifier definitions
    amp_config, amp_cards = generate_amplifier_config(config)
    output += amp_config
    for amp_name, alsa_card in amp_cards.items():
        print(f"  {amp_name}: hw:{alsa_card}", file=sys.stderr)

    output += """
#########################################
# ROOM DEFINITIONS
#########################################
"""

    # Generate config for each room
    for room_id in sorted(rooms.keys()):
        room = rooms[room_id]
        left = room["left"]
        right = room["right"]

        if left and right:
            if left["amplifier"] == right["amplifier"]:
                # Same device - use route plugin
                output += generate_same_device_config(room_id, left, right)
                print(f"  room_{room_id}: stereo on {left['amplifier']} (ch{left['channel']}, ch{right['channel']}) vol={left['volume']:.0%}/{right['volume']:.0%}", file=sys.stderr)
            else:
                # Different devices - use multi plugin
                output += generate_cross_device_config(room_id, left, right)
                print(f"  room_{room_id}: cross-device ({left['amplifier']}_ch{left['channel']} + {right['amplifier']}_ch{right['channel']}) vol={left['volume']:.0%}/{right['volume']:.0%}", file=sys.stderr)
        elif left:
            output += generate_mono_config(room_id, left, "left")
            print(f"  room_{room_id}: mono (left only on {left['amplifier']}_ch{left['channel']}) vol={left['volume']:.0%}", file=sys.stderr)
        elif right:
            output += generate_mono_config(room_id, right, "right")
            print(f"  room_{room_id}: mono (right only on {right['amplifier']}_ch{right['channel']}) vol={right['volume']:.0%}", file=sys.stderr)

    # Generate all_rooms combined output
    output += generate_all_rooms_config(rooms)
    print(f"  all_rooms: combined output to all speakers", file=sys.stderr)

    # Print to stdout
    print(output)

    print("\n" + "=" * 50, file=sys.stderr)
    print("USAGE:", file=sys.stderr)
    print("  Save to /etc/asound.conf:", file=sys.stderr)
    print("    sudo python3 generate_alsa_config.py > /etc/asound.conf", file=sys.stderr)
    print("\n  Or save to file:", file=sys.stderr)
    print("    python3 generate_alsa_config.py > wondom_rooms.conf", file=sys.stderr)
    print("\n  Test with:", file=sys.stderr)
    for room_id in sorted(rooms.keys()):
        print(f"    aplay -D room_{room_id} test.wav", file=sys.stderr)
    print(f"    aplay -D all_rooms test.wav", file=sys.stderr)
    print("\n  Note: Zones are managed by Snapcast, not ALSA.", file=sys.stderr)
    print("=" * 50, file=sys.stderr)


if __name__ == "__main__":
    main()
