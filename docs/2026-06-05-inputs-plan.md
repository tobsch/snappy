# Plan: Audio-Inputs in lox-audioserver einbinden

> **Status (2026-06-05): IMPLEMENTED (Phasen 1–3).** Generator emittiert
> `input_<id>`-Capture-PCMs, `lineinpipe`-Bridge + `lineinpipe@.service` laufen,
> Apply-Pipeline (`apply_inputs` / `affected_inputs`) reconciled die Services,
> REST-Endpoints `/api/config/inputs` + `/api/system/inputs` + `/api/test/input`,
> und die webui hat ein **INPUTS**-Rack-Modul mit Add/Test/Start-Stop/Delete.
> Verifiziert mit `linein` auf Karte `amp4` (C-Media USB) → lox:7080.
> Offen: Phase 4 (Auto-Mapping Zone→lox via lox-API).
>
> Abweichung ggü. Entwurf: Bridge gleich in **Python** (kein `ncat`-Dependency,
> sauberer Reconnect via `Restart=always`), und sie capturet bei lox' 44100/2ch
> (das `input_<id>`-`plug` resampled), sodass **keine** lox-seitige
> `ingest_sample_rate`-Konfiguration nötig ist.

Stand: 2026-06-05. Ziel: physische Audio-Quellen (Fernseher, USB-Capture, etc.) als
lox-audioserver `lineIn`-Sourcen verfügbar machen — konfigurierbar in
multiroom-tooling, gestreamt automatisch in lox.

## Befund (was lox-audioserver tatsächlich kann)

lox-audioserver hat den `linein`-Input-Adapter mit zwei Ingest-Pfaden in
`/app/dist/adapters/inputs/linein/`:

| Pfad | Datei | Port/Protokoll | Anforderung an den Client |
|------|-------|---------------|---------------------------|
| **TCP-Ingest** | `lineInIngestTcp.js` | TCP `127.0.0.1:7080` | öffnen → `<inputId>\n` schicken → roh-PCM s16le (default 44100 Hz / 2 ch) streamen |
| **Sendspin-Source** | `sendspinLineInService.js` | sendspin-WebSocket | Client der `@lox-audioserver/node-sendspin` `SourceControl`-Protokoll implementiert |

Beide Pfade sind **Push** — lox-audioserver liest selbst NICHT von ALSA.

### Warum nicht Sendspin-Source

Das python-`sendspin`-Paket hat keinen Push-Source-Client. `sendspin serve` ist
nur ein Datei/URL-Server, kein Source-Client gegen eine andere Sendspin-Instanz.
Einen eigenen Source-Client gegen das `@lox-audioserver/node-sendspin`-Protokoll
zu bauen wäre ein Riesenumweg ohne klaren Mehrwert.

### Entscheidung: TCP-Ingest

Asymmetrie zur Output-Seite (die nutzt sendspin) ist hinnehmbar — die simpelste
funktionierende Architektur gewinnt. Ein Bridge-Script + systemd-Template
reichen.

---

## Schema (`speaker_config.json`)

`inputs: {}` existiert schon — bekommt jetzt Inhalt:

```json
"inputs": {
  "fernseher": {
    "card": "fernseher",          // ALSA card-id (per udev rule benannt)
    "channels": 2,
    "sample_rate": 48000,         // Capture-Rate (was die Hardware liefert)
    "lox_input_id": "fernseher",  // ID die lox am TCP-Handshake erwartet
    "name": "Wohnzimmer TV",
    "autostart": true
  }
}
```

Felder:
- `card` — ALSA card-id (z.B. via `99-fernseher.rules` udev-Regel persistent gemacht)
- `channels` — 1 oder 2; lox erwartet i.d.R. stereo, mono wird hochgemixt
- `sample_rate` — was die Capture-Hardware liefert. Wenn ≠ 44100, resampled lox intern (sinc) — sauber konfiguriert über `inputs.<id>.source.ingest_sample_rate` auf der lox-Seite
- `lox_input_id` — die ID die der Bridge-Client als ersten Newline-terminierten String über den TCP-Socket schickt; lox verknüpft die per Zone-Config mit `inputs.lineIn.source.id`
- `name` — UI-Anzeige
- `autostart` — ob `lineinpipe@<id>.service` enabled wird

---

## Komponenten

### 1. ALSA-Generator

`generate_alsa_config.py` emittiert pro Input:

```
pcm.input_fernseher {
    type plug
    slave.pcm "hw:fernseher,0"
    slave.channels 2
    slave.rate 48000
}
```

`plug` puffert + resampled falls nötig (sollte aber 1:1 passen wenn rate aus der
config korrekt ist). Keine softvol — Gain regelt lox per Zone.

### 2. Bridge-Script (`/usr/local/bin/lineinpipe`)

Liest den Input aus `speaker_config.json` per ID, startet `arecord` und pipt in
TCP-Socket:

```bash
#!/usr/bin/env bash
# Usage: lineinpipe <input_id>
set -euo pipefail
INPUT_ID="$1"
SPEAKER_CONFIG="/home/tobias/multiroom-tooling/speaker_config.json"
LOX_HOST="127.0.0.1"
LOX_PORT="7080"

read -r CARD CHANNELS RATE LOX_ID < <(python3 - "$SPEAKER_CONFIG" "$INPUT_ID" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
i = c.get("inputs", {}).get(sys.argv[2])
if not i:
    sys.exit(f"input {sys.argv[2]} not found")
print(i["card"], i.get("channels", 2), i.get("sample_rate", 44100), i.get("lox_input_id", sys.argv[2]))
PY
)

# Newline-terminated input-id, dann roh-PCM
{ printf '%s\n' "$LOX_ID"
  exec arecord -D "input_$INPUT_ID" -f S16_LE -c "$CHANNELS" -r "$RATE" -t raw -
} | exec ncat "$LOX_HOST" "$LOX_PORT"
```

Notizen:
- Falls `ncat` zu fragil → Python-Variante mit sauberer Reconnect-Logik
- `arecord` schreibt continuous; `ncat` schickt durch. Wenn lox kaputt geht
  oder die Verbindung abreißt, terminiert die pipe und systemd restartet.

### 3. systemd-Template (`services/lineinpipe@.service`)

```ini
[Unit]
Description=Line-in pipe %i → lox-audioserver
After=network-online.target lox-audioserver.service
PartOf=lox-audioserver.service

[Service]
Type=simple
User=tobias
ExecStart=/usr/local/bin/lineinpipe %i
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Pro konfiguriertem Input mit `autostart: true` läuft ein `lineinpipe@<id>.service`.

### 4. apply-Pipeline (`webui/services/apply.py`)

Analog zu `affected_rooms` brauchen wir `affected_inputs`:
- bei Änderung von `inputs.<id>.{card,channels,sample_rate,lox_input_id}` → restart
- neu mit `autostart: true` → `enable --now`
- aus config entfernt → `stop` + `disable`

### 5. webui

Neue Sektion "Inputs" (parallel zu Rooms im Rack-UI):
- Liste mit Status: bytes/s flow (aus `ss -tpi dst :7080`), lox-input-id, ALSA-card
- "Add Input"-Modal — picked aus `detect_cards()` mit `capture_channels > 0`
  (das `_stream_channels`-Helper haben wir vor zwei Commits gerade dafür gebaut)
- Test-Button: kurze Capture-Probe (`arecord -d 3`) → playback in beliebigen Raum
- Per-Input edit: rate / lox-id ändern, autostart toggle

### 6. lox-config (manuell, nicht in unserem Tool)

Pro Zone in lox-admin-UI:
- `inputs.lineIn.source.id` = `<lox_input_id>` aus unserer config
- Optional `inputs.lineIn.source.ingest_sample_rate` falls ≠ 44100

Können wir später automatisieren über lox's Config-API; nicht in Phase 1.

---

## Phasen

**Phase 1 — Minimal lauffähig** (Backend only):
1. ALSA-Generator: `input_<name>` capture PCM
2. Bridge-Script + systemd-Template
3. Schema im `speaker_config.json` (manuell editieren reicht für Test)
4. Verifizieren mit Fernseher-Capture → lox-zone → Lautsprecher

**Phase 2 — Apply-Pipeline:**
1. `affected_inputs` in apply.py
2. enable/restart/stop von `lineinpipe@<id>` durch Apply
3. apply auch wenn nur Inputs sich geändert haben

**Phase 3 — webui:**
1. Inputs-Sektion mit Liste + Status
2. Add-Input-Modal (Pick aus Capture-Cards)
3. Edit/Test

**Phase 4 — Optional:**
1. Auto-Mapping Zone → lox-input über lox-API
2. Capture-Card-Health (offline/online im Status)
3. Bridge in Python statt bash (besseres Logging, Reconnect-Strategien)

---

## Caveats

- **Sample-Rate-Mismatch**: lox default 44100, GAB8-USB-Audio macht 48000.
  Wenn Capture-Card 48000 schickt und wir das in `sample_rate` setzen, muss lox
  intern resamplen. Auf der lox-Zone den `ingest_sample_rate` mitziehen,
  damit lox weiß was reinkommt.
- **TCP-Bridge ohne Heartbeat**: roh-PCM hat kein keepalive. Wenn lox neu
  startet, terminiert die Verbindung — `Restart=always` im systemd-Service
  fängt's auf.
- **`ncat`-Dependency**: ist nicht standard auf Pi OS. Entweder als
  prerequisite dokumentieren (`apt install ncat`) oder die Bridge gleich
  in Python schreiben.
- **Mehrere Inputs auf einer Capture-Card**: Falls eine USB-Card 4ch hat und
  wir die in 2× stereo splitten wollen, brauchen wir per-input ttable
  (ähnlich wie bei den Speakern auf den GAB8). Aktuell nicht eingeplant —
  1 card = 1 input.
- **Latency**: arecord → TCP → lox → sendspin → ALSA → amp ist eine lange
  Kette. Für TV-Sound sollte alles unter ~150ms bleiben; messen wenn's
  läuft.

---

## Was außerhalb des Plans bleibt

- Bluetooth-Audio Input (eigener bluez-A2DP-sink → arecord-Loop) — separates Thema
- AirPlay als Input (lox kann das bereits selbst)
- Spotify Connect (lox kann das selbst über librespot)
- Music Assistant (lox kann das selbst über das `musicassistant`-Input)

Wir bauen also nur das, was lox NICHT selbst kann: lokale ALSA-Captures
einspeisen.
