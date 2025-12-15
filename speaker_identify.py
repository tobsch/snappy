#!/usr/bin/env python3
"""
Speaker Identification Tool for Wondom GAB8 Devices

Plays a test tone on each channel and asks for room/position identification.
Saves the mapping to ../speaker_config.json for use with generate_alsa_config.py.
"""

import argparse
import json
import subprocess
import re
import os
import sys
import tempfile
import threading
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "speaker_config.json"

# Expected card names for Wondom GAB8 devices
# These are set via udev rules in /etc/udev/rules.d/99-wondom-gab8.rules
GAB8_CARD_NAMES = ["amp1", "amp2", "amp3"]


def discover_devices():
    """Discover available Wondom GAB8 devices and their hardware addresses."""
    try:
        result = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, check=True
        )
        available = {}
        # Parse output to find card numbers for GAB8 devices
        # Example line: "card 2: GAB8 [WONDOM GAB8], device 0: USB Audio [USB Audio]"
        for line in result.stdout.split('\n'):
            match = re.match(r'^card (\d+): (\S+) \[', line)
            if match:
                card_num = match.group(1)
                card_name = match.group(2)
                if card_name in GAB8_CARD_NAMES:
                    device_name = f"amp{len(available) + 1}"
                    available[device_name] = {
                        "card": card_name,
                        "hw": f"hw:{card_num}",
                        "channels": 8
                    }
                    print(f"  Found {device_name}: {card_name} at hw:{card_num}")
        return available
    except subprocess.CalledProcessError as e:
        print(f"Error discovering devices: {e}")
        return {}


def generate_tts_wav(text: str, amplitude: int = 200) -> str:
    """Generate a WAV file with German TTS and return the path."""
    fd, path = tempfile.mkstemp(suffix='.wav')
    os.close(fd)

    try:
        subprocess.run(
            ["espeak-ng", "-v", "de", "-a", str(amplitude), "-w", path, text],
            check=True,
            capture_output=True
        )
        return path
    except subprocess.CalledProcessError as e:
        print(f"  TTS error: {e}")
        os.unlink(path)
        return None
    except FileNotFoundError:
        print("  espeak-ng not found. Install with: sudo apt install espeak-ng")
        os.unlink(path)
        return None


def play_tts_on_channel(device_name: str, channel: int, text: str) -> bool:
    """Play TTS audio on a specific channel using per-channel ALSA device."""
    wav_path = generate_tts_wav(text)
    if not wav_path:
        return False

    try:
        # Use per-channel ALSA device (e.g., amp1_ch3)
        alsa_device = f"{device_name}_ch{channel}"
        subprocess.run(
            ["aplay", "-D", alsa_device, wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Playback error on {alsa_device}: {e}")
        return False
    except subprocess.TimeoutExpired:
        return True
    finally:
        os.unlink(wav_path)


class RepeatingAnnouncement:
    """Plays a TTS announcement repeatedly in the background until stopped."""

    def __init__(self, device_name: str, channel: int, text: str, interval: float = 4.0):
        self.device_name = device_name
        self.channel = channel
        self.text = text
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def _loop(self):
        """Loop that plays announcement repeatedly."""
        while not self._stop_event.is_set():
            play_tts_on_channel(self.device_name, self.channel, self.text)
            # Wait for interval or until stopped
            self._stop_event.wait(self.interval)

    def start(self):
        """Start playing the announcement repeatedly."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the repeating announcement."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)


def get_room_name(existing_rooms: list) -> str:
    """Prompt user for room name with suggestions."""
    if existing_rooms:
        print(f"  Existing rooms: {', '.join(sorted(existing_rooms))}")

    while True:
        room = input("  Room name (or Enter to skip, 'quit' to save and exit): ").strip().lower()

        if room == "quit":
            return "quit"
        if room == "skip" or not room:
            return "skip"

        # Normalize room name: replace spaces with underscores
        room = re.sub(r'\s+', '_', room)
        room = re.sub(r'[^a-z0-9_]', '', room)

        if not room:
            print("  Invalid room name. Use letters, numbers, and underscores.")
            continue

        return room


def get_position() -> str:
    """Prompt user for left/right position."""
    while True:
        pos = input("  Position [l]eft/[r]ight: ").strip().lower()
        if pos in ("l", "left"):
            return "left"
        if pos in ("r", "right"):
            return "right"
        print("  Please enter 'l' or 'r'.")


def get_zones(existing_zones: list, room_name: str) -> list:
    """Prompt user for zone assignments."""
    if existing_zones:
        print(f"  Available zones: {', '.join(sorted(existing_zones))}")

    while True:
        zones_input = input(f"  Zones for {room_name} (comma-separated, or Enter to skip): ").strip().lower()

        if not zones_input:
            return []

        zones = [z.strip() for z in zones_input.split(',') if z.strip()]
        # Normalize zone names
        zones = [re.sub(r'[^a-z0-9_]', '', re.sub(r'\s+', '_', z)) for z in zones]
        zones = [z for z in zones if z]  # Remove empty strings

        return zones


def load_config() -> dict:
    """Load existing configuration if present."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
                # Check if it's the new format
                if config.get("version") == "2.0":
                    return config
                # Migrate old format
                return migrate_old_config(config)
        except (json.JSONDecodeError, IOError):
            pass
    return create_empty_config()


def create_empty_config() -> dict:
    """Create an empty v2.0 configuration."""
    return {
        "version": "2.0",
        "amplifiers": {},
        "speakers": {},
        "rooms": {},
        "zones": {
            "alle": {"name": "Uberall", "include_all": True}
        },
        "snapcast": {
            "server": "localhost",
            "streams": {
                "default": {
                    "type": "pipe",
                    "path": "/tmp/snapfifo",
                    "sampleformat": "48000:16:2",
                    "codec": "flac"
                }
            },
            "stream_targets": {
                "default": {"zones": ["alle"]}
            }
        }
    }


def migrate_old_config(old_config: dict) -> dict:
    """Migrate v1.0 config to v2.0 format."""
    new_config = create_empty_config()

    # Extract amplifier info and speakers
    for speaker_name, info in old_config.get("speakers", {}).items():
        device = info.get("device", "")
        card = info.get("card", "")
        channel = info.get("channel", 0)

        # Add amplifier if not exists
        if device and device not in new_config["amplifiers"]:
            new_config["amplifiers"][device] = {
                "card": card,
                "channels": 8
            }

        # Add speaker in new format
        new_config["speakers"][speaker_name] = {
            "amplifier": device,
            "channel": channel,
            "volume": 100,
            "latency": 0
        }

    # Create rooms from speaker names
    for speaker_name in old_config.get("speakers", {}).keys():
        if speaker_name.endswith("_left"):
            room_id = speaker_name[:-5]
            position = "left"
        elif speaker_name.endswith("_right"):
            room_id = speaker_name[:-6]
            position = "right"
        else:
            continue

        if room_id not in new_config["rooms"]:
            new_config["rooms"][room_id] = {
                "name": room_id.replace("_", " ").title(),
                "left": None,
                "right": None,
                "zones": []
            }

        new_config["rooms"][room_id][position] = speaker_name

    return new_config


def save_config(config: dict, quiet: bool = False):
    """Save configuration to JSON file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    if not quiet:
        print(f"\nConfiguration saved to {CONFIG_FILE}")


def find_speaker_for_channel(config: dict, device_name: str, channel: int) -> tuple:
    """Find existing speaker and room for a device/channel combo."""
    for speaker_name, info in config["speakers"].items():
        if info["amplifier"] == device_name and info["channel"] == channel:
            # Find which room it belongs to
            for room_id, room_info in config["rooms"].items():
                if room_info.get("left") == speaker_name:
                    return speaker_name, room_id, "left"
                if room_info.get("right") == speaker_name:
                    return speaker_name, room_id, "right"
            return speaker_name, None, None
    return None, None, None


def print_summary(config: dict):
    """Print a summary of identified speakers."""
    print("\n" + "=" * 50)
    print("SPEAKER CONFIGURATION SUMMARY")
    print("=" * 50)

    if not config["rooms"]:
        print("No rooms configured.")
        return

    for room_id in sorted(config["rooms"].keys()):
        room = config["rooms"][room_id]
        print(f"\n{room.get('name', room_id)}:")

        for pos in ["left", "right"]:
            speaker_name = room.get(pos)
            if speaker_name and speaker_name in config["speakers"]:
                speaker = config["speakers"][speaker_name]
                amp = speaker["amplifier"]
                ch = speaker["channel"]
                print(f"  {pos}: {amp} ch{ch}")
            else:
                print(f"  {pos}: (not configured)")

        zones = room.get("zones", [])
        if zones:
            print(f"  zones: {', '.join(zones)}")


def main():
    parser = argparse.ArgumentParser(
        description="Identify and configure speakers connected to Wondom GAB8 devices"
    )
    parser.add_argument(
        "--announce-rooms", "-r",
        action="store_true",
        help="Announce existing room names via TTS instead of amplifier/channel"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Announce all channels, including those already mapped"
    )
    args = parser.parse_args()

    print("=" * 50)
    print("WONDOM SPEAKER IDENTIFICATION TOOL")
    print("=" * 50)
    print("\nThis tool will announce each speaker channel using TTS.")
    print("Listen for the announcement and enter the room name and position.\n")

    print("Discovering devices...")
    devices = discover_devices()

    if not devices:
        print("No Wondom devices found!")
        sys.exit(1)

    total_channels = sum(d["channels"] for d in devices.values())
    print(f"\nFound {len(devices)} devices with {total_channels} total channels.\n")

    # Load existing config
    config = load_config()

    # Update amplifiers from discovered devices
    for device_name, device_info in devices.items():
        config["amplifiers"][device_name] = {
            "card": device_info["card"],
            "channels": device_info["channels"]
        }

    # Get existing rooms for suggestions
    existing_rooms = set(config["rooms"].keys())
    existing_zones = set(config["zones"].keys())

    if config["speakers"]:
        print(f"Loaded existing config with {len(config['speakers'])} speakers.")
        response = input("Continue from where you left off? [Y/n]: ").strip().lower()
        if response == "n":
            config = create_empty_config()
            # Re-add discovered amplifiers
            for device_name, device_info in devices.items():
                config["amplifiers"][device_name] = {
                    "card": device_info["card"],
                    "channels": device_info["channels"]
                }
            existing_rooms = set()
            existing_zones = set(config["zones"].keys())

    print("\nStarting identification...\n")
    print("Commands: Enter room name, 'skip' to skip channel, 'quit' to save and exit\n")

    quit_requested = False
    channel_num = 0

    for device_name in sorted(devices.keys()):
        device_info = devices[device_name]

        for channel in range(1, device_info["channels"] + 1):
            channel_num += 1

            # Check if already configured
            existing_speaker, existing_room, existing_pos = find_speaker_for_channel(
                config, device_name, channel
            )

            print("-" * 40)
            print(f"Channel {channel_num}/{total_channels}: {device_name} channel {channel}")

            # Skip already-mapped channels unless --all is specified
            if existing_speaker and existing_room and not args.all:
                print(f"  Already mapped to: {existing_room} ({existing_pos}) - skipping")
                continue

            # Build TTS announcement text in German
            if existing_speaker and existing_room:
                print(f"  Currently mapped to: {existing_room} ({existing_pos})")
                if args.announce_rooms:
                    # Announce existing room/position
                    pos_de = "links" if existing_pos == "left" else "rechts"
                    tts_text = f"{existing_room.replace('_', ' ')} {pos_de}"
                else:
                    # Default: announce device and channel
                    amp_num = device_name.replace("amp", "")
                    tts_text = f"Verstarker {amp_num}, Kanal {channel}"
            else:
                # No existing mapping - announce device and channel in German
                amp_num = device_name.replace("amp", "")
                tts_text = f"Verstarker {amp_num}, Kanal {channel}"

            print(f"  Playing announcement: \"{tts_text}\" (repeats every 4 seconds)...")

            # Start repeating TTS announcement in background
            announcement = RepeatingAnnouncement(device_name, channel, tts_text)
            announcement.start()

            try:
                # For existing mappings, ask if user wants to remap
                if existing_speaker:
                    response = input("  Remap? [y/N]: ").strip().lower()
                    if response != "y":
                        print("  Keeping existing mapping.")
                        continue
                    # Remove old mapping
                    if existing_speaker in config["speakers"]:
                        del config["speakers"][existing_speaker]
                    if existing_room and existing_room in config["rooms"]:
                        config["rooms"][existing_room][existing_pos] = None
                        # Clean up empty rooms
                        room_info = config["rooms"][existing_room]
                        if not room_info.get("left") and not room_info.get("right"):
                            del config["rooms"][existing_room]
                            existing_rooms.discard(existing_room)

                # Get room name while announcement repeats
                room = get_room_name(list(existing_rooms))

                if room == "quit":
                    quit_requested = True
                    break
                if room == "skip":
                    print("  Skipped.")
                    continue

                # Get position while announcement still repeats
                position = get_position()

            finally:
                announcement.stop()

            # Create speaker entry
            speaker_name = f"{room}_{position}"

            # Check for conflicts
            if speaker_name in config["speakers"]:
                old = config["speakers"][speaker_name]
                print(f"  Warning: {speaker_name} already mapped to {old['amplifier']} ch{old['channel']}")
                response = input("  Replace? [y/N]: ").strip().lower()
                if response != "y":
                    continue

            # Add speaker
            config["speakers"][speaker_name] = {
                "amplifier": device_name,
                "channel": channel,
                "volume": 100,
                "latency": 0
            }

            # Add/update room
            if room not in config["rooms"]:
                # New room - ask for zones
                zones = get_zones(list(existing_zones), room)
                # Add any new zones
                for z in zones:
                    if z not in config["zones"]:
                        config["zones"][z] = {"name": z.replace("_", " ").title()}
                        existing_zones.add(z)

                config["rooms"][room] = {
                    "name": room.replace("_", " ").title(),
                    "left": None,
                    "right": None,
                    "zones": zones
                }
                existing_rooms.add(room)

            config["rooms"][room][position] = speaker_name
            print(f"  Mapped: {speaker_name} -> {device_name} ch{channel}")

            # Save immediately after each mapping so progress is never lost
            save_config(config, quiet=True)

        if quit_requested:
            break

    # Save and show summary
    save_config(config)
    print_summary(config)

    print("\nNext steps:")
    print("  1. Run 'python3 generate_alsa_config.py' to generate ALSA configuration")
    print("  2. Run 'python3 generate_snapserver_conf.py' to generate Snapcast configuration")


if __name__ == "__main__":
    main()
