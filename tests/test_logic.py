"""Pure-logic tests for plugin/__init__.py.

These exercise only the business logic that has no dependency on the real
extism-py/wasm runtime (signing, form-encoding, track-field mapping), so they
run under plain python3/uv, with no wasm toolchain installed.
"""

import os
import sys
import unittest
from urllib.parse import parse_qs

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs")

# The stub `extism` module must be importable before `plugin` is, and take
# priority over any real `extism` package that happens to be installed.
sys.path.insert(0, STUBS_DIR)
sys.path.insert(0, REPO_ROOT)

import plugin  # noqa: E402  (import after sys.path setup, by design)

SCROBBLING_SERVICE_SRC = "/Users/matt/PycharmProjects/ScrobblingService/src"
try:
    sys.path.insert(0, SCROBBLING_SERVICE_SRC)
    from scrobbler.lastfm import signature as scrobbling_service_signature
except ImportError:
    scrobbling_service_signature = None


class ComputeApiSigTests(unittest.TestCase):
    def test_matches_known_fixture(self):
        params = {
            "method": "auth.getMobileSession",
            "api_key": "k",
            "username": "alice",
            "password": "p",
            "format": "json",
        }
        # Hand-computed per the documented algorithm: sort keys (excluding
        # format/callback/api_sig), concatenate key+value, append secret, md5-hex.
        payload = "api_keykmethodauth.getMobileSessionpasswordpusernamealice"
        expected = plugin._md5_hex((payload + "secret").encode("utf-8"))
        self.assertEqual(plugin.compute_api_sig(params, "secret"), expected)

    def test_excludes_unsigned_params(self):
        with_format = {"a": "1", "format": "json"}
        without_format = {"a": "1"}
        self.assertEqual(
            plugin.compute_api_sig(with_format, "secret"),
            plugin.compute_api_sig(without_format, "secret"),
        )

    @unittest.skipUnless(
        scrobbling_service_signature is not None,
        "ScrobblingService repo not available on this machine",
    )
    def test_matches_scrobbling_service_signature(self):
        params = {
            "method": "track.scrobble",
            "api_key": "abc123",
            "sk": "sesskey",
            "artist": "Boards of Canada",
            "track": "Roygbiv",
            "timestamp": "1700000000",
            "format": "json",
        }
        expected = scrobbling_service_signature.sign(params, "shh")
        self.assertEqual(plugin.compute_api_sig(params, "shh"), expected)


class Md5Tests(unittest.TestCase):
    def test_known_vectors(self):
        self.assertEqual(plugin._md5_hex(b""), "d41d8cd98f00b204e9800998ecf8427e")
        self.assertEqual(plugin._md5_hex(b"abc"), "900150983cd24fb0d6963f7d28e17f72")

    def test_fallback_matches_hashlib(self):
        data = b"the quick brown fox jumps over the lazy dog, 123456789"
        self.assertEqual(plugin._md5_fallback_hex(data), plugin._md5_hex(data))


class EncodeFormBodyTests(unittest.TestCase):
    def test_round_trips_special_characters(self):
        params = {"a": "1 2", "b": "x&y", "c": "h=llo"}
        body = plugin.encode_form_body(params)
        parsed = {k: v[0] for k, v in parse_qs(body).items()}
        self.assertEqual(parsed, params)

    def test_fallback_matches_urllib(self):
        # Cross-check the hand-rolled fallback encoder against the real stdlib
        # urlencode, since it must behave identically when it's the one used
        # (i.e. when the extism-py runtime lacks urllib.parse).
        from urllib.parse import urlencode as real_urlencode

        params = {"a": "1 2", "b": "x&y=z", "c": "héllo"}
        self.assertEqual(plugin._fallback_urlencode(params), real_urlencode(params))


class BuildTrackParamsTests(unittest.TestCase):
    def test_required_fields_only(self):
        track = {"artist": "Artist", "title": "Title"}
        self.assertEqual(plugin.build_track_params(track), {"artist": "Artist", "track": "Title"})

    def test_optional_fields_included_when_present(self):
        track = {
            "artist": "Artist",
            "title": "Title",
            "album": "Album",
            "albumArtist": "Album Artist",
            "duration": 123.6,
            "trackNumber": 4,
            "mbzRecordingId": "mbid-123",
        }
        params = plugin.build_track_params(track)
        self.assertEqual(
            params,
            {
                "artist": "Artist",
                "track": "Title",
                "album": "Album",
                "albumArtist": "Album Artist",
                "duration": "124",
                "trackNumber": "4",
                "mbid": "mbid-123",
            },
        )

    def test_falsy_optional_fields_omitted(self):
        track = {
            "artist": "Artist",
            "title": "Title",
            "album": "",
            "albumArtist": None,
            "duration": 0,
            "trackNumber": 0,
            "mbzRecordingId": "",
        }
        self.assertEqual(plugin.build_track_params(track), {"artist": "Artist", "track": "Title"})


if __name__ == "__main__":
    unittest.main()
