# Scrobbled scrobbler plugin for Navidrome
#
# Scrobbles Navidrome playback to a self-hosted Scrobbled (Last.fm-compatible)
# server (see https://scrobbled.uk and the ScrobblingService source).
#
# Build with:
#   extism-py plugin/__init__.py -o dist/plugin.wasm
#
# There is no Python PDK for Navidrome plugins, so host functions are called
# directly via the extism:host/user namespace, following the pattern used by
# Navidrome's own nowplaying-py / coverartarchive-py example plugins.

import base64
import json

import extism

try:
    from hashlib import md5 as _hashlib_md5
except ImportError:  # pragma: no cover - depends on the extism-py runtime
    _hashlib_md5 = None

try:
    from urllib.parse import urlencode as _urllib_urlencode
except ImportError:  # pragma: no cover - depends on the extism-py runtime
    _urllib_urlencode = None


# =============================================================================
# Constants
# =============================================================================

# Excluded from the Last.fm-style request signature, per ScrobblingService's
# src/scrobbler/lastfm/signature.py::UNSIGNED_PARAMS.
UNSIGNED_PARAMS = frozenset({"format", "callback", "api_sig"})

# Navidrome's ScrobblerError sentinel strings (plugins/pdk/go/scrobbler/scrobbler.go).
# Raising an Exception with exactly one of these messages tells Navidrome how
# to treat the failure (retry, mark unauthorized, or give up).
ERR_NOT_AUTHORIZED = "scrobbler(not_authorized)"
ERR_RETRY_LATER = "scrobbler(retry_later)"
ERR_UNRECOVERABLE = "scrobbler(unrecoverable)"
KNOWN_SCROBBLER_ERRORS = frozenset({ERR_NOT_AUTHORIZED, ERR_RETRY_LATER, ERR_UNRECOVERABLE})

SESSION_KEY_CACHE_KEY = "sk"

CONFIG_REQUIRED_KEYS = (
    "server_url",
    "api_key",
    "shared_secret",
    "scrobbled_username",
    "scrobbled_password",
)


class ConfigError(Exception):
    """Raised locally when required plugin configuration is missing."""


# =============================================================================
# Raw host function imports
# =============================================================================
# These are custom host functions provided by Navidrome. We import them using
# the extism:host/user namespace. Do not call these directly - use the
# wrapper functions below, which handle JSON marshalling and memory management.


@extism.import_fn("extism:host/user", "http_send")
def _http_send(offset: int) -> int: ...


@extism.import_fn("extism:host/user", "kvstore_get")
def _kvstore_get(offset: int) -> int: ...


@extism.import_fn("extism:host/user", "kvstore_set")
def _kvstore_set(offset: int) -> int: ...


@extism.import_fn("extism:host/user", "kvstore_delete")
def _kvstore_delete(offset: int) -> int: ...


# =============================================================================
# Host function wrappers
# =============================================================================


def _host_call(raw_fn, request_obj: dict) -> dict:
    """Shared JSON-over-memory envelope for calling a raw host function."""
    request_bytes = json.dumps(request_obj).encode("utf-8")
    request_mem = extism.memory.alloc(request_bytes)
    response_offset = raw_fn(request_mem.offset)
    response_mem = extism.memory.find(response_offset)
    response = json.loads(extism.memory.string(response_mem))

    if response.get("error"):
        raise Exception(f"host call failed: {response['error']}")

    return response


def http_send(request: dict) -> dict:
    """Send an HTTP request via Navidrome's http host service.

    Returns the parsed `result` object: {"statusCode": int, "headers": {...},
    "body": "<base64>"}.
    """
    response = _host_call(_http_send, {"request": request})
    return response["result"]


def kv_get(key: str) -> str | None:
    """Get a string value from the plugin's persistent KVStore, or None.

    KVStoreGetResponse.Value is a Go []byte, which Go's encoding/json
    marshals as a base64 string - decode it back to text here.
    """
    response = _host_call(_kvstore_get, {"key": key})
    if not response.get("exists"):
        return None
    return base64.b64decode(response["value"]).decode("utf-8")


def kv_set(key: str, value: str) -> None:
    """Store a string value in the plugin's persistent KVStore.

    KVStoreSetRequest.Value is a Go []byte, which Go's encoding/json expects
    as a base64 string on the wire.
    """
    encoded_value = base64.b64encode(value.encode("utf-8")).decode("ascii")
    _host_call(_kvstore_set, {"key": key, "value": encoded_value})


def kv_delete(key: str) -> None:
    """Delete a value from the plugin's persistent KVStore."""
    _host_call(_kvstore_delete, {"key": key})


# =============================================================================
# MD5 signing
# =============================================================================


def _md5_fallback_hex(data: bytes) -> str:
    """Pure-Python MD5, used only if hashlib.md5 isn't available in the
    extism-py runtime."""

    def left_rotate(x: int, amount: int) -> int:
        x &= 0xFFFFFFFF
        return ((x << amount) | (x >> (32 - amount))) & 0xFFFFFFFF

    s = [
        7,
        12,
        17,
        22,
        7,
        12,
        17,
        22,
        7,
        12,
        17,
        22,
        7,
        12,
        17,
        22,
        5,
        9,
        14,
        20,
        5,
        9,
        14,
        20,
        5,
        9,
        14,
        20,
        5,
        9,
        14,
        20,
        4,
        11,
        16,
        23,
        4,
        11,
        16,
        23,
        4,
        11,
        16,
        23,
        4,
        11,
        16,
        23,
        6,
        10,
        15,
        21,
        6,
        10,
        15,
        21,
        6,
        10,
        15,
        21,
        6,
        10,
        15,
        21,
    ]
    k = [int(abs(__import__("math").sin(i + 1)) * 2**32) & 0xFFFFFFFF for i in range(64)]

    a0, b0, c0, d0 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476

    original_len_bits = (len(data) * 8) & 0xFFFFFFFFFFFFFFFF
    data = data + b"\x80"
    while len(data) % 64 != 56:
        data += b"\x00"
    data += original_len_bits.to_bytes(8, byteorder="little")

    for chunk_start in range(0, len(data), 64):
        chunk = data[chunk_start : chunk_start + 64]
        m = [int.from_bytes(chunk[i : i + 4], byteorder="little") for i in range(0, 64, 4)]

        a, b, c, d = a0, b0, c0, d0

        for i in range(64):
            if i < 16:
                f = (b & c) | (~b & d)
                g = i
            elif i < 32:
                f = (d & b) | (~d & c)
                g = (5 * i + 1) % 16
            elif i < 48:
                f = b ^ c ^ d
                g = (3 * i + 5) % 16
            else:
                f = c ^ (b | ~d)
                g = (7 * i) % 16

            f = (f + a + k[i] + m[g]) & 0xFFFFFFFF
            a = d
            d = c
            c = b
            b = (b + left_rotate(f, s[i])) & 0xFFFFFFFF

        a0 = (a0 + a) & 0xFFFFFFFF
        b0 = (b0 + b) & 0xFFFFFFFF
        c0 = (c0 + c) & 0xFFFFFFFF
        d0 = (d0 + d) & 0xFFFFFFFF

    digest = b"".join(x.to_bytes(4, byteorder="little") for x in (a0, b0, c0, d0))
    return digest.hex()


def _md5_hex(data: bytes) -> str:
    if _hashlib_md5 is not None:
        return _hashlib_md5(data).hexdigest()
    return _md5_fallback_hex(data)


def compute_api_sig(params: dict, secret: str) -> str:
    """Last.fm-style request signature, ported verbatim from ScrobblingService's
    src/scrobbler/lastfm/signature.py::sign: sort every param except
    format/callback/api_sig by key, concatenate key+value pairs, append the
    shared secret, and md5-hex the result."""
    payload = "".join(
        f"{name}{params[name]}" for name in sorted(params) if name not in UNSIGNED_PARAMS
    )
    return _md5_hex((payload + secret).encode("utf-8"))


# =============================================================================
# Form encoding
# =============================================================================


def _percent_encode(value: str) -> str:
    unreserved = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
    out = []
    for byte in value.encode("utf-8"):
        char = chr(byte)
        if char in unreserved:
            out.append(char)
        elif char == " ":
            out.append("+")
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


def _fallback_urlencode(params: dict) -> str:
    return "&".join(
        f"{_percent_encode(str(k))}={_percent_encode(str(v))}" for k, v in params.items()
    )


def encode_form_body(params: dict) -> str:
    if _urllib_urlencode is not None:
        return _urllib_urlencode(params)
    return _fallback_urlencode(params)


def _encode_body_b64(params: dict) -> str:
    """Form-encode params and base64-encode the result, since Navidrome's
    HTTPRequest.Body is a Go []byte, which Go's encoding/json expects as a
    base64 string on the wire."""
    return base64.b64encode(encode_form_body(params).encode("utf-8")).decode("ascii")


# =============================================================================
# Configuration
# =============================================================================


def _read_config() -> dict:
    cfg = {}
    for key in CONFIG_REQUIRED_KEYS:
        value = extism.Config.get_str(key)
        if not value:
            raise ConfigError(f"missing required config: {key}")
        cfg[key] = value
    cfg["navidrome_username"] = extism.Config.get_str("navidrome_username") or None
    return cfg


# =============================================================================
# Scrobbled (Last.fm-compatible) API client
# =============================================================================


def _api_url(server_url: str) -> str:
    return server_url.rstrip("/") + "/2.0/"


def _decode_json_body(result: dict) -> dict:
    body_bytes = base64.b64decode(result.get("body", "") or "")
    try:
        return json.loads(body_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Exception(ERR_UNRECOVERABLE) from exc


def _raise_for_lastfm_error(status_code: int, parsed: dict) -> None:
    code = parsed.get("error")
    if status_code >= 500 or code == 29:
        raise Exception(ERR_RETRY_LATER)
    if code == 4:
        raise Exception(ERR_NOT_AUTHORIZED)
    raise Exception(ERR_UNRECOVERABLE)


def get_session_key(cfg: dict, force_reauth: bool = False) -> str:
    """Return a cached Scrobbled session key, performing the auth.getMobileSession
    handshake (and caching the result) if none is cached yet or force_reauth is set."""
    if not force_reauth:
        cached = kv_get(SESSION_KEY_CACHE_KEY)
        if cached:
            return cached

    params = {
        "method": "auth.getMobileSession",
        "api_key": cfg["api_key"],
        "username": cfg["scrobbled_username"],
        "password": cfg["scrobbled_password"],
        "format": "json",
    }
    params["api_sig"] = compute_api_sig(params, cfg["shared_secret"])

    try:
        result = http_send(
            {
                "method": "POST",
                "url": _api_url(cfg["server_url"]),
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "body": _encode_body_b64(params),
            }
        )
    except Exception as exc:
        raise Exception(ERR_RETRY_LATER) from exc

    parsed = _decode_json_body(result)

    if "error" in parsed:
        _raise_for_lastfm_error(result.get("statusCode", 0), parsed)

    sk = parsed["session"]["key"]
    kv_set(SESSION_KEY_CACHE_KEY, sk)
    return sk


def call_lastfm(
    method: str, params: dict, cfg: dict | None = None, allow_reauth: bool = True
) -> dict:
    """Call a session-authenticated, signed Scrobbled/Last.fm method."""
    if cfg is None:
        cfg = _read_config()

    sk = get_session_key(cfg)

    full_params = dict(params)
    full_params["method"] = method
    full_params["api_key"] = cfg["api_key"]
    full_params["sk"] = sk
    full_params["format"] = "json"
    full_params["api_sig"] = compute_api_sig(full_params, cfg["shared_secret"])

    try:
        result = http_send(
            {
                "method": "POST",
                "url": _api_url(cfg["server_url"]),
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "body": _encode_body_b64(full_params),
            }
        )
    except Exception as exc:
        raise Exception(ERR_RETRY_LATER) from exc

    parsed = _decode_json_body(result)

    if "error" not in parsed:
        return parsed

    code = parsed["error"]
    status_code = result.get("statusCode", 0)

    if status_code >= 500 or code == 29:
        raise Exception(ERR_RETRY_LATER)

    if code == 9:
        # Invalid session key: drop the cached one, re-authenticate once, and
        # retry the call exactly once with the fresh session key.
        if allow_reauth:
            kv_delete(SESSION_KEY_CACHE_KEY)
            get_session_key(cfg, force_reauth=True)
            return call_lastfm(method, params, cfg=cfg, allow_reauth=False)
        raise Exception(ERR_NOT_AUTHORIZED)

    if code == 4:
        raise Exception(ERR_NOT_AUTHORIZED)

    raise Exception(ERR_UNRECOVERABLE)


# =============================================================================
# Track mapping
# =============================================================================


def build_track_params(track: dict) -> dict:
    """Map a Navidrome TrackInfo dict onto Last.fm/Scrobbled request params."""
    params = {
        "artist": track["artist"],
        "track": track["title"],
    }
    if track.get("album"):
        params["album"] = track["album"]
    if track.get("albumArtist"):
        params["albumArtist"] = track["albumArtist"]
    if track.get("duration"):
        params["duration"] = str(round(track["duration"]))
    if track.get("trackNumber"):
        params["trackNumber"] = str(track["trackNumber"])
    if track.get("mbzRecordingId"):
        params["mbid"] = track["mbzRecordingId"]
    return params


# =============================================================================
# Plugin exports
# =============================================================================


def _log_and_reraise(exc: Exception, context: str) -> None:
    extism.log(extism.LogLevel.Error, f"{context}: {exc}")
    if str(exc) in KNOWN_SCROBBLER_ERRORS:
        raise exc
    raise Exception(ERR_UNRECOVERABLE)


@extism.plugin_fn
def nd_scrobbler_is_authorized():
    """Fast local check - no network call. True if the plugin is fully
    configured and (if navidrome_username is set) the request matches it."""
    input_data = extism.input_json()
    username = input_data.get("username", "")

    try:
        cfg = _read_config()
    except ConfigError as exc:
        extism.log(extism.LogLevel.Error, f"is_authorized: {exc}")
        extism.output_str(json.dumps(False))
        return

    authorized = bool(username) and (
        not cfg["navidrome_username"] or username == cfg["navidrome_username"]
    )
    extism.output_str(json.dumps(authorized))


@extism.plugin_fn
def nd_scrobbler_now_playing():
    input_data = extism.input_json()
    try:
        call_lastfm("track.updateNowPlaying", build_track_params(input_data["track"]))
    except Exception as exc:
        _log_and_reraise(exc, "now_playing")


@extism.plugin_fn
def nd_scrobbler_scrobble():
    input_data = extism.input_json()
    try:
        params = build_track_params(input_data["track"])
        params["timestamp"] = input_data["timestamp"]
        call_lastfm("track.scrobble", params)
    except Exception as exc:
        _log_and_reraise(exc, "scrobble")


@extism.plugin_fn
def nd_scrobbler_playback_report():
    # Required export, but Scrobbled has no playback-state concept beyond
    # now-playing/scrobble, so this is a deliberate no-op.
    try:
        input_data = extism.input_json()
        extism.log(
            extism.LogLevel.Info,
            f"playback_report state={input_data.get('state')} (no-op)",
        )
    except Exception:
        pass
