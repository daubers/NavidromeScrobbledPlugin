# Scrobbled Navidrome Plugin

A [Navidrome](https://www.navidrome.org/) scrobbler plugin that sends now-playing
updates and scrobbles to a self-hosted [Scrobbled](https://scrobbled.uk) server
(a Last.fm Audioscrobbler 2.0-compatible service).

It's a WebAssembly plugin built with [Extism](https://extism.org/), written in
Python. Navidrome has no first-class Python SDK for plugins ("no Python PDK"),
so this plugin calls Navidrome's host services directly, following the pattern
used by Navidrome's own [`nowplaying-py`](https://github.com/navidrome/navidrome/tree/master/plugins/examples/nowplaying-py)
and [`coverartarchive-py`](https://github.com/navidrome/navidrome/tree/master/plugins/examples/coverartarchive-py)
example plugins.

## How it works

Navidrome calls this plugin's four `nd_scrobbler_*` exports as users play
music. The plugin translates each call into a signed, session-authenticated
request against Scrobbled's `/2.0/` Last.fm-compatible API:

- `nd_scrobbler_is_authorized` — a fast local check (no network call) that the
  plugin is configured and, if `navidrome_username` is set, that the request
  is for that user.
- `nd_scrobbler_now_playing` → `track.updateNowPlaying`
- `nd_scrobbler_scrobble` → `track.scrobble`
- `nd_scrobbler_playback_report` — required by Navidrome's Scrobbler
  capability, but implemented as a no-op since Scrobbled has no playback-state
  concept beyond now-playing/scrobble.

The Scrobbled session key (`sk`), obtained once via the `auth.getMobileSession`
handshake, is cached in Navidrome's per-plugin KVStore so it isn't re-derived
from the configured password on every call. If Scrobbled reports the cached
session key as invalid, the plugin re-authenticates once and retries.

This is a single-account plugin: one Navidrome user's plays scrobble to one
Scrobbled account, configured directly in the plugin's config.

## Configuration

Set these via the Navidrome admin UI (Plugins page) or
`navidrome plugin edit <id> --config '...'`:

| Key | Required | Description |
| --- | --- | --- |
| `server_url` | yes | Base URL of your Scrobbled instance, e.g. `https://scrobbled.uk` |
| `api_key` | yes | API key from a Scrobbled "app" you create in its web UI |
| `shared_secret` | yes | Shared secret paired with the API key |
| `scrobbled_username` | yes | Your Scrobbled account username |
| `scrobbled_password` | yes | Your Scrobbled account password (used only for the session handshake, never sent on scrobble calls) |
| `navidrome_username` | no | If set, only this Navidrome username is treated as authorized |

You also need to assign the plugin to the relevant Navidrome user(s), e.g.:

```sh
navidrome plugin edit navidrome-scrobbled --users <your-navidrome-username>
```

## Building

Requires [`extism-py`](https://github.com/extism/python-pdk) and
[Binaryen](https://github.com/WebAssembly/binaryen) (`wasm-opt`/`wasm-merge`)
on `PATH`. The official installer fetches both:

```sh
curl -fsSL https://raw.githubusercontent.com/extism/python-pdk/main/install.sh | bash

make build      # compiles plugin/__init__.py -> dist/plugin.wasm
make package    # packages manifest.json + dist/plugin.wasm -> dist/navidrome-scrobbled.ndp
make validate   # navidrome plugin validate dist/navidrome-scrobbled.ndp (needs a navidrome binary on PATH)
```

## Testing

```sh
make test   # or: python3 -m unittest discover -s tests -v
```

`tests/test_logic.py` exercises the plugin's pure business logic (request
signing, form-encoding, track-field mapping) under plain CPython, using a
minimal fake `extism` module (`tests/stubs/extism.py`) — no wasm toolchain
required. If a checkout of the `ScrobblingService` server source is available
on the same machine, it also cross-checks the signing algorithm against that
project's own implementation.

## Installing

Copy the built `.ndp` file into your Navidrome plugins folder (or install it
via whatever mechanism your Navidrome deployment provides for plugin files),
then configure and assign users as described above.

## CI/CD

Gitea Actions (`.gitea/workflows/ci.yml`) lints and tests every push and pull
request, builds, packages and validates the `.ndp` on every push, and — on
pushes to `main` or `v*` tags — publishes the built artifact both to this
repo's own Gitea package registry and to the same
[pkgs.daubney.dev](https://pkgs.daubney.dev) ProGet asset feed used by
`ScrobblingService`, under the `navidrome-scrobbled` content path.

## License

BSD 3-Clause. See [LICENSE](LICENSE).
