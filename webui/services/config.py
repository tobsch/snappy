"""Configuration service - loads and saves speaker_config.json"""

import json
from pathlib import Path
from typing import Any
import shutil
from datetime import datetime


class ConfigService:
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self._config: dict | None = None

    def load(self) -> dict:
        """Load config from file"""
        with open(self.config_file, 'r') as f:
            self._config = json.load(f)
        return self._config

    def save(self, config: dict | None = None) -> None:
        """Save config to file (creates backup first)"""
        if config is not None:
            self._config = config

        # Create backup
        backup_path = self.config_file.with_suffix('.json.bak')
        if self.config_file.exists():
            shutil.copy(self.config_file, backup_path)

        # Save config
        with open(self.config_file, 'w') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    @property
    def config(self) -> dict:
        """Get current config (loads if not cached)"""
        if self._config is None:
            self.load()
        return self._config

    def reload(self) -> dict:
        """Force reload from disk"""
        return self.load()

    # Amplifiers
    def get_amplifiers(self) -> dict:
        return self.config.get('amplifiers', {})

    def get_amplifier(self, amp_id: str) -> dict | None:
        return self.get_amplifiers().get(amp_id)

    # Speakers
    def get_speakers(self) -> dict:
        return self.config.get('speakers', {})

    def get_speaker(self, speaker_id: str) -> dict | None:
        return self.get_speakers().get(speaker_id)

    def update_speaker(self, speaker_id: str, data: dict) -> None:
        if 'speakers' not in self.config:
            self.config['speakers'] = {}
        self.config['speakers'][speaker_id] = data
        self.save()

    def delete_speaker(self, speaker_id: str) -> bool:
        if speaker_id in self.config.get('speakers', {}):
            del self.config['speakers'][speaker_id]
            self.save()
            return True
        return False

    # Rooms
    def get_rooms(self) -> dict:
        return self.config.get('rooms', {})

    def get_room(self, room_id: str) -> dict | None:
        return self.get_rooms().get(room_id)

    def create_room(self, room_id: str, data: dict) -> None:
        if 'rooms' not in self.config:
            self.config['rooms'] = {}
        self.config['rooms'][room_id] = data
        self.save()

    def update_room(self, room_id: str, data: dict) -> None:
        if 'rooms' not in self.config:
            self.config['rooms'] = {}
        self.config['rooms'][room_id] = data
        self.save()

    def delete_room(self, room_id: str) -> bool:
        if room_id in self.config.get('rooms', {}):
            del self.config['rooms'][room_id]
            self.save()
            return True
        return False

    # Zones
    def get_zones(self) -> dict:
        return self.config.get('zones', {})

    def get_zone(self, zone_id: str) -> dict | None:
        return self.get_zones().get(zone_id)

    def create_zone(self, zone_id: str, data: dict) -> None:
        if 'zones' not in self.config:
            self.config['zones'] = {}
        self.config['zones'][zone_id] = data
        self.save()

    def update_zone(self, zone_id: str, data: dict) -> None:
        if 'zones' not in self.config:
            self.config['zones'] = {}
        self.config['zones'][zone_id] = data
        self.save()

    def delete_zone(self, zone_id: str) -> bool:
        if zone_id in self.config.get('zones', {}):
            del self.config['zones'][zone_id]
            self.save()
            return True
        return False

    # Streams
    def get_streams(self) -> dict:
        return self.config.get('snapcast', {}).get('streams', {})

    def get_stream(self, stream_id: str) -> dict | None:
        return self.get_streams().get(stream_id)

    def update_stream(self, stream_id: str, data: dict) -> None:
        if 'snapcast' not in self.config:
            self.config['snapcast'] = {}
        if 'streams' not in self.config['snapcast']:
            self.config['snapcast']['streams'] = {}
        self.config['snapcast']['streams'][stream_id] = data
        self.save()

    def delete_stream(self, stream_id: str) -> bool:
        if stream_id in self.config.get('snapcast', {}).get('streams', {}):
            del self.config['snapcast']['streams'][stream_id]
            self.save()
            return True
        return False

    # Stream targets
    def get_stream_targets(self) -> dict:
        return self.config.get('snapcast', {}).get('stream_targets', {})

    def update_stream_targets(self, stream_id: str, data: dict) -> None:
        if 'snapcast' not in self.config:
            self.config['snapcast'] = {}
        if 'stream_targets' not in self.config['snapcast']:
            self.config['snapcast']['stream_targets'] = {}
        self.config['snapcast']['stream_targets'][stream_id] = data
        self.save()

    # Global settings
    def get_global(self) -> dict:
        return self.config.get('global', {})

    def update_global(self, data: dict) -> None:
        self.config['global'] = data
        self.save()

    def get_max_volume(self) -> float:
        return self.get_global().get('max_volume', 0.5)

    def set_max_volume(self, value: float) -> None:
        if 'global' not in self.config:
            self.config['global'] = {}
        self.config['global']['max_volume'] = value
        self.save()

    # Channel mapping helpers
    def get_channel_assignment(self, amp_id: str, channel: int) -> dict | None:
        """Find which speaker/room uses this channel"""
        for speaker_id, speaker in self.get_speakers().items():
            if speaker.get('amplifier') == amp_id and speaker.get('channel') == channel:
                # Find which room uses this speaker
                for room_id, room in self.get_rooms().items():
                    if room.get('left') == speaker_id:
                        return {'speaker': speaker_id, 'room': room_id, 'position': 'left', 'room_name': room.get('name', room_id)}
                    if room.get('right') == speaker_id:
                        return {'speaker': speaker_id, 'room': room_id, 'position': 'right', 'room_name': room.get('name', room_id)}
                return {'speaker': speaker_id, 'room': None, 'position': None, 'room_name': None}
        return None

    def get_rooms_in_zone(self, zone_id: str) -> list[str]:
        """Get all room IDs that belong to a zone"""
        zone = self.get_zone(zone_id)
        if zone and zone.get('include_all'):
            return list(self.get_rooms().keys())

        rooms = []
        for room_id, room in self.get_rooms().items():
            if zone_id in room.get('zones', []):
                rooms.append(room_id)
        return rooms
