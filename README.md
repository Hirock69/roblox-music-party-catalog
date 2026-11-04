# Music Party catalog delivery

Public music metadata, numeric analysis and the scheduled updater only. Roblox gameplay source remains in the private game repository. No raw audio is published or committed.

GitHub Actions refreshes the official Top40 daily at 18:17 UTC (03:17 JST), on policy/updater changes, and on manual dispatch. It filters the Human-maintained selection-policy.json, downloads official public audio temporarily, hashes it, reuses matching numeric analysis, analyzes new audio before activation, and deploys a complete validated generation through GitHub Pages. Failed generations leave the prior site intact.

The game checks for completed generations every 6 hours and adopts them only between rounds. It validates metadata and every profile before switching. No Lua source or executable payload is fetched. Unknown formats, invalid profiles, inaccessible audio and empty pools fail or exclude with a report. A previous in-memory catalog and the bundled catalog remain available if delivery fails.

The updater uses Python 3.11, NumPy/librosa and ffmpeg/ffprobe. Long audio is analyzed only through the first 300 seconds; the full duration remains in metadata. Profiles are immutable by SHA-256 filename. Current and two prior generations are retained in each deployment. Source metadata: https://apis.roblox.com/music-discovery/v1/top-songs?pageToken=0&limit=40 .

The private repository's catalog-service directory is the updater source. Copy only its contents here. Never copy .git, Studio files, raw recordings/audio, credentials or game Luau source. Policy updates must update the private canonical list and this public mirror together. Successful deployments record last-refresh.json on the default branch, keeping real catalog update activity visible. GitHub schedules may be delayed; workflow failures remain visible in Actions and the last successful health.json.
