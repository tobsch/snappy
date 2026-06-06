"""Apply pipeline: regenerate ALSA config + restart affected sendspin services.

Pipeline (after the new speaker_config.json has been written to disk):
  1. Run generate_alsa_config.py → capture stdout
  2. Compare to current /etc/asound.conf; if changed, sudo-write new file
  3. Seed every per-speaker softvol with its volume via amixer (so the live
     control reflects the saved value after install)
  4. Determine which sendspin@room_<id> services need restarting based on
     channel/speaker changes between old and new room configs
  5. systemctl restart those services (in parallel)
"""

import asyncio
import math
import tempfile
from pathlib import Path


ROOM_SIDES = ("left", "right", "sub", "mono")


def affected_rooms(old_config: dict, new_config: dict) -> list[str]:
    """Return room ids whose effective channel mapping changed.

    A room is affected if its left/right/sub/mono speaker assignment changed,
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
        for side in ROOM_SIDES:
            if channel_of(old_speakers, old.get(side)) != channel_of(new_speakers, new.get(side)):
                affected.append(rid)
                break
        else:
            # Also restart if room id existed before but is gone now (cleanup)
            if rid in old_rooms and rid not in new_rooms:
                affected.append(rid)
    return sorted(affected)


# Fields whose change requires the lineinpipe bridge to restart (the capture
# format / target changed). `autostart` is handled separately (start vs stop).
INPUT_FIELDS = ("card", "channels", "sample_rate", "lox_input_id")


def affected_inputs(old_config: dict, new_config: dict) -> list[str]:
    """Return input ids whose bridge needs reconciling (added, removed, or any
    capture/target field or autostart flag changed)."""
    old = old_config.get("inputs", {})
    new = new_config.get("inputs", {})
    affected: list[str] = []
    for iid in set(old) | set(new):
        o, n = old.get(iid), new.get(iid)
        if o is None or n is None:
            affected.append(iid)
            continue
        if any(o.get(f) != n.get(f) for f in INPUT_FIELDS) or \
                bool(o.get("autostart", True)) != bool(n.get("autostart", True)):
            affected.append(iid)
    return sorted(affected)


async def reconcile_input_services(old_config: dict, new_config: dict) -> dict[str, str]:
    """Start/restart lineinpipe@<id> for affected autostart inputs, stop+disable
    the rest. Newly-added and changed inputs both go through enable + restart so
    the running bridge always reflects the current config."""
    new = new_config.get("inputs", {})
    to_start: list[str] = []
    to_stop: list[str] = []
    for iid in affected_inputs(old_config, new_config):
        unit = f"lineinpipe@{iid}.service"
        n = new.get(iid)
        if n and n.get("autostart", True):
            to_start.append(unit)
        else:
            to_stop.append(unit)

    results: dict[str, str] = {}
    if to_start:
        # enable creates the wants-symlink (idempotent); restart starts-or-restarts.
        await systemctl_action("enable", to_start)
        results.update(await systemctl_action("restart", to_start))
    if to_stop:
        results.update(await systemctl_action("disable --now", to_stop))
    return results


async def apply_inputs(project_dir: Path, old_config: dict, new_config: dict) -> dict:
    """Apply pipeline for input changes: regenerate ALSA (input_<id> PCMs now
    differ) and reconcile lineinpipe services. Lighter than apply_config — no
    softvol seeding or sendspin restarts, since inputs don't touch rooms."""
    alsa = await regenerate_alsa(project_dir)
    alsa_changed = await write_asound_conf(alsa)
    input_services = await reconcile_input_services(old_config, new_config)
    return {"alsa_changed": alsa_changed, "input_services": input_services}


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
    """Run a single systemctl action against the given units in parallel.

    `action` may be a single verb ("restart") or a verb + flag sequence
    ("enable --now") — it's shell-split into separate argv tokens so multi-word
    forms work without invoking a shell.
    """
    if not units:
        return {}

    action_args = action.split()

    async def one(unit: str) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "systemctl", *action_args, unit,
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
    for side in ROOM_SIDES:
        if room.get(side):
            return True
    return False


# softvol uses a dB scale; ALSA's amixer percentage maps linearly across
# [min_dB..max_dB]. We want the slider's 0–100 to feel linear in amplitude:
#   gain = (slider/100) * max_volume        (saved scale 0..1)
#   dB   = 20 * log10(gain)                 (with gain==0 → silent)
#   pct  = (dB - MIN) / (MAX - MIN) * 100   (clamped 0..100)
SOFTVOL_MIN_DB = -60.0
SOFTVOL_MAX_DB = 0.0


def linear_to_amixer_pct(slider_pct: float, max_volume: float = 1.0) -> int:
    s = max(0.0, min(100.0, float(slider_pct)))
    gain = (s / 100.0) * float(max_volume or 1.0)
    if gain <= 0:
        return 0
    db = 20.0 * math.log10(gain)
    if db <= SOFTVOL_MIN_DB:
        return 0
    if db >= SOFTVOL_MAX_DB:
        return 100
    return int(round((db - SOFTVOL_MIN_DB) / (SOFTVOL_MAX_DB - SOFTVOL_MIN_DB) * 100))


async def amixer_set(card: str, control: str, percent: int) -> bool:
    """Set softvol value via amixer. Returns True on success."""
    pct = max(0, min(100, int(percent)))
    proc = await asyncio.create_subprocess_exec(
        "amixer", "-c", card, "sset", control, f"{pct}%",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def prime_softvol_pcm(pcm_name: str) -> None:
    """Open a softvol-wrapped PCM very briefly so its kernel control element
    gets created. Without this, amixer can't find the control until the first
    real consumer (e.g. sendspin) opens the device.

    aplay's -d only takes whole seconds; instead we pipe a tiny chunk of
    silence from /dev/zero (200 bytes = 100 frames of mono S16 @ 48kHz ≈ 2ms),
    which causes aplay to open + play + exit cleanly.
    """
    # Pipe from /dev/zero with bounded size, into aplay.
    cmd = (
        f"head -c 200 /dev/zero | "
        f"aplay -D {pcm_name} -t raw -f S16_LE -r 48000 -c 1 - "
        f">/dev/null 2>&1 || true"
    )
    proc = await asyncio.create_subprocess_shell(cmd)
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            proc.kill()


async def seed_softvols(config: dict) -> dict[str, str]:
    """For each room with speakers, prime the softvol PCM (so the kernel
    control element exists) and then set the value matching the saved
    volume. Control names are vol_<room>_<side>; card is the speaker's amp."""
    speakers = config.get("speakers", {})
    rooms = config.get("rooms", {})
    global_max = config.get("global", {}).get("max_volume", 1.0)

    targets = []
    for rid, room in rooms.items():
        # per-room max_volume caps this room independently; falls back to global
        room_max = room.get("max_volume", global_max)
        for side in ROOM_SIDES:
            spk_id = room.get(side)
            if not spk_id:
                continue
            spk = speakers.get(spk_id)
            if not spk:
                continue
            card = spk.get("amplifier")
            if not card:
                continue
            ctrl = f"vol_{rid}_{side}"
            pct = linear_to_amixer_pct(spk.get("volume", 100), room_max)
            targets.append((card, ctrl, pct))

    # Prime each softvol PCM in parallel so kernel controls come into existence
    await asyncio.gather(*(prime_softvol_pcm(ctrl) for _, ctrl, _ in targets))

    # Now amixer-set each
    results: dict[str, str] = {}
    outs = await asyncio.gather(*(amixer_set(c, ctrl, pct) for c, ctrl, pct in targets))
    for (_, ctrl, _), ok in zip(targets, outs):
        results[ctrl] = "ok" if ok else "failed"
    return results


async def seed_room_softvols(config: dict, room_id: str) -> dict[str, str]:
    """Re-seed a single room's softvols to its (possibly per-room) max_volume.
    Live amixer only — no ALSA regen, no sendspin restart. Used by the per-room
    max-volume slider."""
    speakers = config.get("speakers", {})
    room = config.get("rooms", {}).get(room_id)
    if not room:
        return {}
    global_max = config.get("global", {}).get("max_volume", 1.0)
    room_max = room.get("max_volume", global_max)

    targets = []
    for side in ROOM_SIDES:
        spk_id = room.get(side)
        if not spk_id:
            continue
        spk = speakers.get(spk_id)
        if not spk:
            continue
        card = spk.get("amplifier")
        if not card:
            continue
        ctrl = f"vol_{room_id}_{side}"
        pct = linear_to_amixer_pct(spk.get("volume", 100), room_max)
        targets.append((card, ctrl, pct))

    await asyncio.gather(*(prime_softvol_pcm(ctrl) for _, ctrl, _ in targets))
    results: dict[str, str] = {}
    outs = await asyncio.gather(*(amixer_set(c, ctrl, pct) for c, ctrl, pct in targets))
    for (_, ctrl, _), ok in zip(targets, outs):
        results[ctrl] = "ok" if ok else "failed"
    return results


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

    # 2.5: seed every per-speaker softvol via amixer so live values match the
    # newly persisted config. Idempotent — controls already exist after the
    # asound.conf is parsed.
    result["softvol_seed"] = await seed_softvols(new_config)

    # 3: split affected rooms into "still has speakers" (restart) vs "no
    # longer has any speaker / removed entirely" (stop). Keeping a sendspin
    # service running for a room with no ALSA device just produces a crash
    # loop because the device doesn't exist in the regenerated asound.conf.
    new_rooms = new_config.get("rooms", {})
    affected = affected_rooms(old_config, new_config)

    # If global settings (max_volume etc.) changed, every device's ttable
    # coefficients are rewritten — restart every room that still has any
    # speaker so the running sendspin picks up the new gain.
    old_global = old_config.get("global", {})
    new_global = new_config.get("global", {})
    if old_global != new_global:
        affected = sorted(set(affected) | {
            rid for rid, r in new_rooms.items() if room_has_speakers(r)
        })

    # If /etc/asound.conf actually changed on disk, the room device's PCM
    # chain may have been restructured (e.g. softvol added). Already-open
    # sendspin streams hold the old chain — force-restart every room that
    # still has speakers so the new chain is picked up. Volume-only edits
    # don't trigger this (softvol values change via amixer, not asound.conf).
    if result["alsa_changed"]:
        affected = sorted(set(affected) | {
            rid for rid, r in new_rooms.items() if room_has_speakers(r)
        })

    to_restart: list[str] = []
    to_stop: list[str] = []
    for rid in affected:
        unit = f"sendspin@room_{rid}.service"
        if room_has_speakers(new_rooms.get(rid)):
            to_restart.append(unit)
        else:
            to_stop.append(unit)

    # `is-active` returns "active"/"inactive"/"failed" for known instances and
    # "unknown" for ones that have never been enabled. We split on that so a
    # newly-added room (no systemd instance yet) goes through `enable --now`
    # instead of being silently dropped.
    async def partition_by_state(units: list[str]) -> tuple[list[str], list[str]]:
        known: list[str] = []
        unknown: list[str] = []
        for unit in units:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "is-active", unit,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            state = out.decode().strip()
            (known if state and state != "unknown" else unknown).append(unit)
        return known, unknown

    restart_real, enable_real = await partition_by_state(to_restart)
    stop_real, _ = await partition_by_state(to_stop)  # only stop what exists

    restart_results = await systemctl_action("restart", restart_real)
    # `enable --now` both creates the systemd-wants symlink and starts the unit
    # in one go — so a newly-added room is fully wired without manual setup.
    enable_results = await systemctl_action("enable --now", enable_real) if enable_real else {}
    stop_results = await systemctl_action("stop", stop_real)

    result["services_restarted"] = restart_real
    result["services_enabled"] = enable_real
    result["services_stopped"] = stop_real
    result["service_results"] = {**restart_results, **enable_results, **stop_results}
    return result
