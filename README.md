# Plex Music

**Plex Music v1.0.0** — a fresh release of the self-hosted Home Assistant integration for playing Plex music on Amazon Echo devices with your own Alexa custom skill.

This repository has a **new GitHub identity and clean release history**. Version 1.0.0 is based on the previously tested stable playback functionality, with a new manifest, documentation and release baseline. Historical releases and development experiments are preserved separately in [Plex-Music-Archive](https://github.com/SRJHomeAssistant/Plex-Music-Archive).

## Features

- Play and shuffle Plex tracks, artists and albums using Alexa
- Match shortened album titles and Roman/Arabic numerals, including “Frozen 2” and “Frozen II”
- Stream MP3 directly and use Plex MP3 transcoding for compatible other formats, including WMA and FLAC
- Pause, resume, skip tracks and retain playback queues and recent-track history in local SQLite storage
- Register Echo devices and view music status, title, artist, album and artwork in Home Assistant
- No AWS hosting, unofficial Alexa API client, paid service or separate music server

## Requirements

Home Assistant **2026.11.2+**, Plex Media Server with a music library, Amazon Echo, an Alexa **Custom** skill and a publicly accessible HTTPS endpoint with a trusted TLS certificate.

## Install

1. In Home Assistant Marketplace add `https://github.com/SRJHomeAssistant/Plex-Music` as a custom **Integration** repository.
2. Install stable **v1.0.0** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Plex Music**.
4. Follow Plex authorisation and select music libraries under **Plex Music → Configure**.
5. Use **Plex Music → Configure → Alexa skill setup** to configure your Alexa custom skill.

Back up Home Assistant before installing. The previous repo was renamed, and this is a new installation identity in Marketplace, although the Home Assistant integration domain remains `plex_music`.

## Alexa skill setup

1. Create a **Custom** skill in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask), using **English (UK)**.
2. Copy the Alexa interaction model JSON from the Home Assistant wizard or [this file](alexa/interaction_model_en_GB.json), then paste it into the console's JSON Editor, save and build the model.
3. Enable **Audio Player** under **Interfaces**.
4. Set the skill's HTTPS endpoint to the URL shown by the wizard. Use a trusted TLS certificate.
5. Enter the Alexa skill ID into Plex Music's settings.
6. Say **“Alexa, ask Plex Music to identify this device”** on each Echo, then register/name it in Home Assistant.

The wizard assists with setup but does not deploy or host an Alexa skill.

## Voice examples

- “Alexa, ask Plex Music to play album Frozen 2”
- “Alexa, ask Plex Music to shuffle album Paint the Sky With Stars”
- “Alexa, ask Plex Music to play artist Enya”
- “Alexa, ask Plex Music to play song Heartlines”
- “Alexa, ask Plex Music what's playing”
- “Alexa, ask Plex Music to pause” / “resume music” / “next track” / “stop”

## Release workflow

| Branch | Purpose |
| --- | --- |
| `main` | Stable releases |
| `development` | Beta development and testing |

The maintainer publishes tags and releases manually. Start with **v1.0.0**, targeting `main` and **not** marking it as a prerelease. Once stable playback is verified, test new Alexa diagnostics and compatibility features on `development`.

## Security and compatibility

Never share Plex tokens, Alexa skill IDs or private endpoint details. Native Alexa app/Alexa Media Player “Playing” display is not guaranteed for custom skills and is not part of this stable release.

MIT licence. The **original copyright notice is preserved unchanged** in [LICENSE](LICENSE). Plex Music is an independent community project, not an official Plex or Amazon product.
