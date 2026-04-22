# Bug: Corrupt FLAC stream after client reconnect

## Problem

When a sendspin client reconnects during active FLAC playback, lox-audioserver starts sending FLAC chunks without the STREAMINFO header. The sendspin FLAC decoder fails on every chunk:

```
WARNING:sendspin.decoder:FLAC decode error: [Errno 1094995529] Invalid data found when processing input: 'avcodec_send_packet()'
```

This floods the log and no audio plays. Restarting the sendspin service does not help — the server keeps sending headerless FLAC data. Only restarting lox-audioserver resolves it.

## How to reproduce

1. Play Spotify (FLAC codec) to a zone with a sendspin client
2. Restart the sendspin client: `sudo systemctl restart sendspin@room_esszimmer`
3. Client reconnects, receives `Stream started with codec flac`
4. All subsequent FLAC chunks fail to decode

## Root cause

This is a **lox-audioserver bug**. When the stream pipeline is rebuilt after reconnect, `sendspinOutput.ts` calls `engine.createStream(zoneId, profile, { primeWithBuffer: true })` to get a new stream. The FLAC header/codec info IS correctly sent in the `stream_start` message (the sendspin decoder initializes successfully), but the actual FLAC audio frames from the engine are corrupt.

The engine joins the ongoing FLAC encoding session mid-stream via `createStream()` with `primeWithBuffer: true`. This likely provides buffered FLAC frames that are not aligned to FLAC frame boundaries, or belong to a different encoder state than what was communicated in the codec header. The FLAC decoder receives frames it cannot parse, causing continuous `avcodec_send_packet()` errors.

The sequence observed:
1. Client reconnects after restart
2. `Stream started with codec flac` — received correctly
3. `FLAC decoder initialized for 48000Hz/24-bit/2ch` — header parsed OK
4. No successful audio decode (no "Stream STARTED" log)
5. ~2 minutes later: flood of `FLAC decode error: Invalid data found when processing input`

The 2-minute delay before errors suggests the buffered/primed data was silently dropped, and the errors start when live FLAC frames arrive that are misaligned with the decoder state.

**Key observation:** PCM streams work fine after reconnect. Only FLAC is broken. When lox-audioserver happens to send PCM instead of FLAC after reconnect, audio plays normally. This confirms the issue is specific to the FLAC encoding pipeline not resetting for new stream consumers.

## Expected behavior

When a new stream is created for a reconnecting client, lox-audioserver should either:
- Re-send the FLAC STREAMINFO header before audio chunks
- Or restart the FLAC encoder so the stream begins with a fresh header

## Workaround

Restart lox-audioserver: `sudo docker restart lox-audioserver`

This forces all streams to restart from scratch with proper headers.

## Environment

- lox-audioserver: beta-latest
- sendspin: 7.0.0
- Audio source: Spotify Connect (FLAC codec)

## Tracking

- **Issue**: lox-audioserver/lox-audioserver#235
- **Fix PR**: lox-audioserver/lox-audioserver#236

## Related

- lox-audioserver/lox-audioserver#233 — Sendspin client not receiving audio after reconnect
- lox-audioserver/lox-audioserver#234 — Fix for stream reuse on reconnect (triggers this bug when stream is rebuilt with FLAC)
