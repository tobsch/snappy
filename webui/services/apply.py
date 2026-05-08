"""Apply pipeline: regenerate ALSA config + restart affected sendspin services.

Pipeline (after the new speaker_config.json has been written to disk):
  1. Run generate_alsa_config.py → capture stdout
  2. Compare to current /etc/asound.conf; if changed, sudo-write new file
  3. Determine which sendspin@room_<id> services need restarting based on
     channel/speaker changes between old and new room configs
  4. systemctl restart those services (in parallel)
"""

import asyncio
import tempfile
from pathlib import Path


def affected_rooms(old_config: dict, new_config: dict) -> list[str]:
    """Return room ids whose effective channel mapping changed.

    A room is affected if its left/right/sub speaker assignment changed,
    or any of those speakers' (amp, channel) changed.
    """
    old_speakers = old_config.get("speakers", {})
    new_speakers = new_config.get("speakers", {})
    old_rooms = old_config.get("rooms", {})
    new_rooms = new_config.get("rooms", {})

    def channel_of(speakers: dict, spk_id: str | None):
        if not spk_id:
            return None
        s = speakers.get(spk_id)
        if not s:
            return None
        return (s.get("amplifier"), s.get("channel"))

    affected: list[str] = []
    room_ids = set(old_rooms) | set(new_rooms)
    for rid in room_ids:
        old = old_rooms.get(rid, {})
        new = new_rooms.get(rid, {})
        for side in ("left", "right", "sub"):
            if channel_of(old_speakers, old.get(side)) != channel_of(new_speakers, new.get(side)):
                affected.append(rid)
                break
        else:
            # Also restart if room id existed before but is gone now (cleanup)
            if rid in old_rooms and rid not in new_rooms:
                affected.append(rid)
    return sorted(affected)


async def regenerate_alsa(project_dir: Path) -> str:
    """Run generate_alsa_config.py and return its stdout."""
    proc = await asyncio.create_subprocess_exec(
        "python3", str(project_dir / "generate_alsa_config.py"),
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"generate_alsa_config.py failed: {stderr.decode().strip()}")
    return stdout.decode()


async def write_asound_conf(content: str, target: str = "/etc/asound.conf") -> bool:
    """Write content to /etc/asound.conf via sudo. Returns True if file changed."""
    target_path = Path(target)
    current = target_path.read_text() if target_path.exists() else ""
    if current == content:
        return False

    # Write to a temp file we own, then sudo cp into place
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
        f.write(content)
        tmp = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "cp", tmp, target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"sudo cp failed: {stderr.decode().strip()}")
    finally:
        Path(tmp).unlink(missing_ok=True)
    return True


async def systemctl_action(action: str, units: list[str]) -> dict[str, str]:
    """Run a single systemctl action against the given units in parallel."""
    if not units:
        return {}

    async def one(unit: str) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "systemctl", action, unit,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            return unit, "ok"
        return unit, f"failed: {stderr.decode().strip()}"

    return dict(await asyncio.gather(*(one(u) for u in units)))


async def restart_services(units: list[str]) -> dict[str, str]:
    return await systemctl_action("restart", units)


def room_has_speakers(room: dict | None) -> bool:
    if not room:
        return False
    for side in ("left", "right", "sub"):
        if room.get(side):
            return True
    return False


async def apply_config(project_dir: Path, old_config: dict, new_config: dict) -> dict:
    """Run the full apply pipeline.

    Returns a structured result describing each step so the UI can show progress.
    Raises RuntimeError on hard failure (callers translate to HTTP 500).
    """
    result: dict = {
        "alsa_changed": False,
        "services_restarted": [],
        "services_stopped": [],
        "service_results": {},
    }

    # 1+2: regenerate ALSA config and install
    alsa = await regenerate_alsa(project_dir)
    result["alsa_changed"] = await write_asound_conf(alsa)

    # 3: split affected rooms into "still has speakers" (restart) vs "no
    # longer has any speaker / removed entirely" (stop). Keeping a sendspin
    # service running for a room with no ALSA device just produces a crash
    # loop because the device doesn't exist in the regenerated asound.conf.
    new_rooms = new_config.get("rooms", {})
    affected = affected_rooms(old_config, new_config)

    to_restart: list[str] = []
    to_stop: list[str] = []
    for rid in affected:
        unit = f"sendspin@room_{rid}.service"
        if room_has_speakers(new_rooms.get(rid)):
            to_restart.append(unit)
        else:
            to_stop.append(unit)

    # Only act on units that have a loaded instance. `list-unit-files` doesn't
    # cover template instances; `is-active` returns "active"/"inactive"/"failed"
    # for known instances and "unknown" otherwise.
    async def known(units: list[str]) -> list[str]:
        keep = []
        for unit in units:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "is-active", unit,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            state = out.decode().strip()
            if state and state != "unknown":
                keep.append(unit)
        return keep

    restart_real = await known(to_restart)
    stop_real = await known(to_stop)

    restart_results = await systemctl_action("restart", restart_real)
    stop_results = await systemctl_action("stop", stop_real)

    result["services_restarted"] = restart_real
    result["services_stopped"] = stop_real
    result["service_results"] = {**restart_results, **stop_results}
    return result
