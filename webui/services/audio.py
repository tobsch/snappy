"""Audio service - speaker testing via TTS and chime, with optional gain.

When a `gain` (0..1) is provided, the audio is piped through `sox … vol G` so
the volume slider in the UI takes effect immediately on test playback without
requiring an Apply round-trip (which would rewrite /etc/asound.conf and
restart sendspin services).
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional


class AudioService:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.chime_path = project_dir / "webui" / "static" / "sounds" / "test_chime.wav"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _gain_or_none(volume_pct: Optional[int]) -> Optional[float]:
        """Convert 0..100 percent to a 0..1 gain. None / 100 → None (no scaling)."""
        if volume_pct is None:
            return None
        v = max(0, min(100, int(volume_pct)))
        if v == 100:
            return None
        return v / 100.0

    @staticmethod
    async def _ensure_amp_on(amp: str) -> None:
        """Power the target amplifier on AND restore its PCM mixer before a test sound.

        Test chimes/TTS are played via aplay directly, which bypasses sendspin's
        WebSocket — so the external powermanager.sh (bytes-flow detector) never
        wakes the amp and the test is silent. Calling `ampctl on` here makes the
        test audible; the powermanager's normal idle-timeout then powers the amp
        back off shortly after the test ends.

        We also reset the USB-Audio PCM mixer to 100%: it can drift to its
        hardware default (~57% / -18 dB on the WONDOM GAB8) after a power cycle
        if the `99-amp-volume.rules` udev rule misses the reconnect, leaving the
        test audibly attenuated. amixer -c <amp> sset PCM 100% is a few ms and
        idempotent when already at 100%.

        Best-effort: if ampctl or amixer are missing or fail, we still try to
        play (degrades to silent rather than erroring out).
        """
        for cmd in (
            ["ampctl", "on", amp],
            ["amixer", "-c", amp, "sset", "PCM", "100%"],
        ):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception:
                pass

    # Brief settle so the amp mute-release completes before the first sample.
    _AMP_SETTLE_SEC = 0.1

    async def _play_file(self, device: str, source_path: Path, gain: Optional[float]) -> bool:
        """Play a wav file through `aplay -D <device>`, optionally pre-scaled by sox.

        Uses an OS pipe (sox stdout fd → aplay stdin fd) so the two processes
        stream like a shell pipe; asyncio's PIPE-wrapped StreamReader can't be
        passed directly as another subprocess's stdin.
        """
        try:
            if gain is None:
                proc = await asyncio.create_subprocess_exec(
                    "aplay", "-D", device, str(source_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                return proc.returncode == 0

            r_fd, w_fd = os.pipe()
            try:
                sox = await asyncio.create_subprocess_exec(
                    "sox", str(source_path), "-t", "wav", "-", "vol", f"{gain:.4f}",
                    stdout=w_fd,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                # Close write end in this process so sox is the only writer
                os.close(w_fd)
                w_fd = -1
                aplay = await asyncio.create_subprocess_exec(
                    "aplay", "-D", device,
                    stdin=r_fd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                os.close(r_fd)
                r_fd = -1
                await aplay.wait()
                await sox.wait()
                return aplay.returncode == 0
            finally:
                if w_fd != -1:
                    try: os.close(w_fd)
                    except OSError: pass
                if r_fd != -1:
                    try: os.close(r_fd)
                    except OSError: pass
        except Exception:
            return False

    async def _generate_tts(self, text: str) -> Optional[str]:
        """Generate a temp WAV via espeak-ng and return its path, or None on failure."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
            proc = await asyncio.create_subprocess_exec(
                "espeak-ng", "-v", "de", "-w", temp_path, text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                Path(temp_path).unlink(missing_ok=True)
                return None
            return temp_path
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def play_chime(self, amplifier: str, channel: int, volume_pct: Optional[int] = None) -> bool:
        device = f"{amplifier}_ch{channel}"
        await self._ensure_amp_on(amplifier)
        await asyncio.sleep(self._AMP_SETTLE_SEC)
        return await self._play_file(device, self.chime_path, self._gain_or_none(volume_pct))

    async def play_tts(self, amplifier: str, channel: int, volume_pct: Optional[int] = None) -> bool:
        text = f"Verstärker {amplifier[-1]}, Kanal {channel}"
        device = f"{amplifier}_ch{channel}"
        temp_path = await self._generate_tts(text)
        if not temp_path:
            return False
        try:
            await self._ensure_amp_on(amplifier)
            await asyncio.sleep(self._AMP_SETTLE_SEC)
            return await self._play_file(device, Path(temp_path), self._gain_or_none(volume_pct))
        finally:
            Path(temp_path).unlink(missing_ok=True)

    async def play_room_stereo(
        self,
        left_amp: Optional[str], left_ch: Optional[int], left_volume_pct: Optional[int],
        right_amp: Optional[str], right_ch: Optional[int], right_volume_pct: Optional[int],
        sound: str = "chime",
        text: Optional[str] = None,
    ) -> bool:
        """Play stereo test by fanning out to per-channel devices in parallel.

        Each side gets its own gain so the live slider values are honored
        without touching /etc/asound.conf. If a side has no speaker, it's
        silently skipped.
        """
        # Generate the source file once
        source: Optional[Path] = None
        cleanup = False
        if sound == "tts":
            speak = text or "Test"
            tmp = await self._generate_tts(speak)
            if not tmp:
                return False
            source = Path(tmp)
            cleanup = True
        else:
            source = self.chime_path

        try:
            # Power on every distinct amp involved in this room (handles
            # cross-device stereo where left/right live on different amps).
            amps_to_wake = {a for a in (left_amp, right_amp) if a}
            if amps_to_wake:
                await asyncio.gather(*(self._ensure_amp_on(a) for a in amps_to_wake))
                await asyncio.sleep(self._AMP_SETTLE_SEC)

            tasks = []
            if left_amp and left_ch:
                tasks.append(self._play_file(f"{left_amp}_ch{left_ch}", source, self._gain_or_none(left_volume_pct)))
            if right_amp and right_ch:
                tasks.append(self._play_file(f"{right_amp}_ch{right_ch}", source, self._gain_or_none(right_volume_pct)))
            if not tasks:
                return True  # nothing to play is not an error — user just hasn't wired the room yet
            results = await asyncio.gather(*tasks)
            return all(results)
        finally:
            if cleanup and source:
                source.unlink(missing_ok=True)
