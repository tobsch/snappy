"""Audio service - speaker testing via TTS and chime"""

import asyncio
import subprocess
import tempfile
from pathlib import Path


class AudioService:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.chime_path = project_dir / "webui" / "static" / "sounds" / "test_chime.wav"

    async def play_tts(self, amplifier: str, channel: int) -> bool:
        """Play TTS announcement on a specific channel"""
        # Generate TTS audio
        text = f"Verstärker {amplifier[-1]}, Kanal {channel}"
        device = f"{amplifier}_ch{channel}"

        try:
            # Generate TTS to temp file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                temp_path = f.name

            # espeak-ng generates wav file
            proc = await asyncio.create_subprocess_exec(
                'espeak-ng', '-v', 'de', '-w', temp_path, text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

            if proc.returncode != 0:
                return False

            # Play via ALSA
            proc = await asyncio.create_subprocess_exec(
                'aplay', '-D', device, temp_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

            # Cleanup
            Path(temp_path).unlink(missing_ok=True)

            return proc.returncode == 0
        except Exception:
            return False

    async def play_chime(self, amplifier: str, channel: int) -> bool:
        """Play chime sound on a specific channel"""
        device = f"{amplifier}_ch{channel}"

        try:
            proc = await asyncio.create_subprocess_exec(
                'aplay', '-D', device, str(self.chime_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    async def play_room_test(self, room_id: str, position: str = 'stereo') -> bool:
        """Play test on a room (stereo, left, or right)"""
        if position == 'stereo':
            device = f"room_{room_id}"
        else:
            device = f"room_{room_id}"  # For now, use stereo device

        try:
            proc = await asyncio.create_subprocess_exec(
                'aplay', '-D', device, str(self.chime_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    async def play_chime_on_rooms(self, room_ids: list[str]) -> dict[str, bool]:
        """Play chime on multiple rooms concurrently"""
        tasks = []
        for room_id in room_ids:
            tasks.append(self._play_room_with_id(room_id))

        results = await asyncio.gather(*tasks)
        return dict(results)

    async def _play_room_with_id(self, room_id: str) -> tuple[str, bool]:
        """Helper to return room_id with result"""
        result = await self.play_room_test(room_id)
        return (room_id, result)
