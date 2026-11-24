# Plex Music v1.0.0 — Stream Plex Music to Alexa Echo's 🎵

Plex Music is a free, self-hosted Home Assistant custom integration that plays music from your Plex libraries on Amazon Echo devices through your own Alexa **Custom** skill. It uses Home Assistant, Plex and the official Alexa skill interfaces; no AWS hosting, additional music server or unofficial Alexa API client is required.

## Features

- Authorise a Plex account and choose Plex music libraries.
- Play or shuffle artists and albums, and play individual songs by voice.
- Recognise shortened album names and Roman/Arabic numerals: “Frozen 2” can match **Frozen II: Original Motion Picture Soundtrack**; “Paint the Sky With Stars” can match an extended album title.
- Play compatible MP3 tracks directly; ask Plex to transcode compatible other formats such as WMA and FLAC to MP3 for Echo playback.
- Keep queues, positions and recent-track history in Home Assistant's local SQLite database.
- Register and name multiple Echo devices, with per-device Home Assistant status and diagnostic sensors.
- Display Plex Music's track information, album artwork and playback status in Home Assistant.
- Pause, resume, stop, skip and go back through tracks.
- Ask which track is playing, or why a track failed.

## Requirements

- Home Assistant **2026.11.2** or newer.
- Plex Media Server with an accessible music library.
- An Amazon Echo device and an Alexa custom skill.
- A publicly reachable HTTPS Home Assistant address with a trusted TLS certificate for Alexa requests and streams.

**Security:** Do not post Plex account credentials, tokens, Alexa skill IDs or private endpoint details in logs, screenshots or issues.

## Installation and Plex configuration

1. Add [SRJHomeAssistant/Plex-Music](https://github.com/SRJHomeAssistant/Plex-Music) to Home Assistant Marketplace as a custom **Integration** repository, if it isn't already listed.
2. Install Plex Music, then restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Plex Music**.
4. Enter your Plex server's private IPv4 address (the default Plex port is **32400**), follow the Plex sign-in link and authorise access.
5. Open **Plex Music → Configure** and select the Plex music libraries to use.

This repository is a new GitHub repository and Marketplace installation source. The earlier repository and its historical releases are preserved in [Plex-Music-Archive](https://github.com/SRJHomeAssistant/Plex-Music-Archive).

## Set up the Alexa custom skill

1. In **Plex Music → Configure**, open the Alexa skill setup wizard.
2. Create a **Custom** skill in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) using **English (UK)**.
3. On the wizard's **Copy your Alexa skill configuration** screen, copy the complete interaction model JSON. Alternatively, use the [en-GB interaction model](alexa/interaction_model_en_GB.json) and GitHub's **Copy raw file** option.
4. Paste the JSON into **Interaction Model → JSON Editor**, save it and build the model. Under **Interfaces**, enable **Audio Player**.
5. Set the skill's HTTPS endpoint to the URL shown in the Plex Music wizard. It must be reachable from Amazon and use trusted TLS.
6. Enter the skill ID in Plex Music's Alexa setup options.
7. On each Echo, say **“Alexa, ask Plex Music to identify this device”**. In **Plex Music → Configure**, register the identified device and assign it a friendly name.

If your existing Alexa skill uses an older interaction model, paste and rebuild the current model to enable the explicit song/album/artist and shuffle-album commands. The integration does **not** create or deploy the Alexa skill automatically.

## Alexa voice commands

Examples may vary depending on the Alexa interaction model. For native playback controls during music, say **“next track”** and **“previous track”**, rather than simply “next” and “previous”.

| What you want | What to say |
| --- | --- |
| Play an artist | “Alexa, ask Plex Music to play Enya.” |
| Play a specific album | “Alexa, ask Plex Music to play album Paint the Sky With Stars.” |
| Play a specific song | “Alexa, ask Plex Music to play song Heartlines.” |
| Shuffle an artist | “Alexa, ask Plex Music to shuffle Enya.” |
| Shuffle an album | “Alexa, ask Plex Music to shuffle album Paint the Sky With Stars.” |
| Check the current song | “Alexa, ask Plex Music what's playing.” |
| Explain a playback failure | “Alexa, ask Plex Music why did that song not play?” |
| Pause | “Alexa, ask Plex Music to pause.” |
| Resume | “Alexa, ask Plex Music to resume music.” |
| Next track | “Alexa, ask Plex Music to play the next track.” |
| Skip a track | “Alexa, ask Plex Music to skip this song.” |
| Previous track | “Alexa, ask Plex Music to play the previous track.” |
| Stop | “Alexa, ask Plex Music to stop.” |
| Identify an Echo | “Alexa, ask Plex Music to identify this device.” |

Native Alexa controls such as **“Alexa, pause”**, **“Alexa, resume”**, **“Alexa, stop”**, **“Alexa, next track”** and **“Alexa, previous track”** were also tested with the archived stable implementation.

## Playback and shuffle behaviour

**Play** retains the Plex-selected track order. Artist results follow Plex's album listing order, which may not be the chronological release order. **Shuffle** randomises the selected artist or album queue once and preserves that order during playback.

The integration remembers up to 100 recently started distinct track IDs per installation in local SQLite. It prefers less recently played tracks when starting a shuffle, including across registered Echo devices. The archived notes describe this behaviour but note that the cross-device scenario was not exhaustively verified.

**Multi-room playback:** Synchronised audio playback across an Echo speaker group is not supported. Playback commands affect the Echo that invoked the skill.

## Playback status, artwork and controls

The Plex Music Home Assistant status sensors report playback events received by the custom skill. They can show **Playing** and display track details/artwork while its queue is playing. As a queued track finishes, the next queued track should be able to start without a brief Idle transition. Stopping playback returns the Plex Music status to **Idle**.

**Important:** These are **Plex Music's own Home Assistant sensors**, not the separate **Alexa Media Player** integration or the Alexa phone app. The official custom skill's `AudioPlayer.Play` directive does **not** guarantee that those two products display the session as Playing.

Ask **“Alexa, ask Plex Music what's playing”** to hear the current song, artist and album for the Echo making the request. It also works for a paused queue.

## Playback format compatibility and troubleshooting

Compatible MP3 files stream directly from Plex. Other source formats, including previously tested WMA and FLAC, can be requested from Plex as MP3 transcodes. Home Assistant logs provide the source codec, container, playback path, HTTP response information and Alexa-reported errors to help diagnose failures.

If a track fails, say **“Alexa, ask Plex Music why did that song not play?”** on that Echo. The skill can report the last failure observed since Home Assistant started, including the Echo name, song, artist, album (when available) and source file type. The source file type by itself does not prove what caused the failure. The archived documentation verified the no-failure response, but not every real failure-event spoken response.

If an Echo cannot access audio or artwork, verify that the Home Assistant stream and artwork URLs are externally accessible through HTTPS with a trusted certificate, and consult Home Assistant logs for actual playback errors. Do not expose Plex or Home Assistant credentials in support requests.

## Resume and recover after Home Assistant restarts

Plex Music saves each Echo's queue, playback offset, pause state and queue identifier to a local SQLite database in the Home Assistant configuration directory: `plex_music_playback.sqlite3`.

- **Paused queues:** Pause music, restart Home Assistant and ask Plex Music to resume on the same Echo. Paused playback information can be restored from saved state.
- **Album and artist queues:** If Home Assistant restarts during music playback, the current stream may continue. Saved queue identifiers let subsequent next-track commands continue against the restored queue. The archived stable implementation was tested for next-track playback and automatic progression after a restart.
- **Stop versus Pause:** Stop ends the active queue. Use Pause when you intend to resume later.
- **Diagnostics:** The **Last Called** sensor shows a fixed date/time in Home Assistant's local timezone.

## Registered Echo devices and voice aliases

Register and name Echos from **Plex Music → Configure** after saying **“Alexa, ask Plex Music to identify this device”** on each speaker. If several unidentified devices appear together, identify and register them one at a time to match friendly names to the correct physical Echos.

Plex Music also supports voice recognition overrides for artist, song or album names Alexa frequently mishears.

## Releases and support

| Branch | Purpose |
| --- | --- |
| [main](../../tree/main) | Stable public releases |
| [development](../../tree/development) | Beta development and testing |

The maintainer creates tags and GitHub releases manually. Stable release: **v1.0.0**. Use the [GitHub releases page](../../releases) to choose an available release, and enable Marketplace pre-releases when testing betas.

- [Report a bug or request a feature](../../issues)
- [Alexa interaction model](alexa/interaction_model_en_GB.json)
- [Historical development archive](https://github.com/SRJHomeAssistant/Plex-Music-Archive)

Plex Music is an independent community project, not an official Plex or Amazon product. Distributed under the [MIT licence](LICENSE), preserving the original copyright notice.
