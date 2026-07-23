import errno
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-token.py"
SPEC = importlib.util.spec_from_file_location("claude_token", MODULE_PATH)
assert SPEC and SPEC.loader
claude_token = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(claude_token)


class ContextDirectoryTests(unittest.TestCase):
    def test_explicit_cache_directory_takes_precedence(self):
        with mock.patch.dict(
            os.environ,
            {"BLACKHOLE_CONTEXT_DIR": "/tmp/explicit-blackhole-contexts"},
            clear=True,
        ):
            self.assertEqual(
                claude_token.configured_context_dir(),
                Path("/tmp/explicit-blackhole-contexts"),
            )

    def test_installed_cache_directory_is_loaded_from_managed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "context-cache-dir"
            configured_path = Path(directory) / "blackhole_contexts"
            config_path.write_text(f"{configured_path}\n", encoding="utf-8")
            with mock.patch.object(
                claude_token, "CONTEXT_CONFIG_PATH", config_path
            ), mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    claude_token.configured_context_dir(), configured_path
                )

    def test_relative_installed_cache_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "context-cache-dir"
            config_path.write_text("relative/cache\n", encoding="utf-8")
            with mock.patch.object(
                claude_token, "CONTEXT_CONFIG_PATH", config_path
            ), mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    RuntimeError, "invalid context cache configuration"
                ):
                    claude_token.configured_context_dir()


class ContextFillTests(unittest.TestCase):
    def test_prefers_used_percentage_and_clamps_it(self):
        self.assertEqual(
            claude_token.context_fill(
                {
                    "context_window": {
                        "used_percentage": 125,
                        "total_input_tokens": 1,
                        "context_window_size": 100,
                    }
                }
            ),
            1.0,
        )

    def test_falls_back_to_token_ratio(self):
        self.assertEqual(
            claude_token.context_fill(
                {
                    "context_window": {
                        "total_input_tokens": 42,
                        "context_window_size": 100,
                    }
                }
            ),
            0.42,
        )

    def test_uses_legacy_limit_signal(self):
        self.assertEqual(claude_token.context_fill({"exceeds_200k_tokens": True}), 1.0)

    def test_missing_data_is_zero(self):
        self.assertEqual(claude_token.context_fill({}), 0.0)


class ContextFileTests(unittest.TestCase):
    def test_context_record_is_scoped_to_pane_and_hashed_session(self):
        with tempfile.TemporaryDirectory() as directory:
            original_dir = claude_token.CONTEXT_DIR
            claude_token.CONTEXT_DIR = Path(directory)
            try:
                with mock.patch.dict(
                    os.environ,
                    {"WARP_TERMINAL_SESSION_UUID": "550E8400E29B41D4A716446655440000"},
                ):
                    record = claude_token.context_record({"session_id": "claude/session"})
                self.assertIsNotNone(record)
                assert record is not None
                self.assertEqual(record.parent.name, "550e8400e29b41d4a716446655440000")
                self.assertEqual(record.suffix, ".context")
                self.assertNotIn("claude", record.name)
            finally:
                claude_token.CONTEXT_DIR = original_dir

    def test_context_record_requires_valid_pane_and_session_ids(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(claude_token.context_record({"session_id": "session"}))
        with mock.patch.dict(os.environ, {"WARP_TERMINAL_SESSION_UUID": "../unsafe"}):
            self.assertIsNone(claude_token.context_record({"session_id": "session"}))
        with mock.patch.dict(
            os.environ,
            {"WARP_TERMINAL_SESSION_UUID": "550e8400e29b41d4a716446655440000"},
        ):
            self.assertIsNone(claude_token.context_record({}))

    def test_write_fill_replaces_the_file_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            context_file = Path(directory) / "nested" / "session.context"
            claude_token.write_fill(context_file, 0.625, updated_at=1234.5)
            self.assertEqual(
                json.loads(context_file.read_text(encoding="utf-8")),
                {"version": 1, "fill": 0.625, "updated_at": 1234.5},
            )
            self.assertEqual(list(context_file.parent.glob(".session.context.*")), [])

    def test_write_fill_rejects_invalid_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            context_file = Path(directory) / "pane" / "session.context"
            for timestamp in (-1.0, float("nan"), float("inf")):
                with self.subTest(timestamp=timestamp):
                    with self.assertRaisesRegex(ValueError, "timestamp"):
                        claude_token.write_fill(
                            context_file, 0.625, updated_at=timestamp
                        )

    def test_remove_fill_only_removes_the_selected_session(self):
        with tempfile.TemporaryDirectory() as directory:
            pane_dir = Path(directory) / "pane"
            first = pane_dir / "first.context"
            second = pane_dir / "second.context"
            claude_token.write_fill(first, 0.8)
            claude_token.write_fill(second, 0.2)

            claude_token.remove_fill(first)

            self.assertFalse(first.exists())
            self.assertEqual(
                json.loads(second.read_text(encoding="utf-8"))["fill"], 0.2
            )

    def test_remove_fill_accepts_a_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            claude_token.remove_fill(Path(directory) / "missing" / "session.context")

    def test_pane_fill_uses_maximum_session_and_empty_pane_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            pane = Path(directory) / "pane"
            first = pane / "first.context"
            second = pane / "second.context"
            claude_token.write_fill(first, 0.8)
            claude_token.write_fill(second, 0.2)

            self.assertEqual(claude_token.pane_fill(first), 0.8)
            claude_token.remove_fill(first)
            self.assertEqual(claude_token.pane_fill(second), 0.2)
            claude_token.remove_fill(second)
            self.assertIsNone(claude_token.pane_fill(second))

    def test_pane_fill_removes_expired_versioned_records(self):
        with tempfile.TemporaryDirectory() as directory:
            pane = Path(directory) / "pane"
            stale = pane / "stale.context"
            live = pane / "live.context"
            expiry = claude_token.CONTEXT_RECORD_TTL_SECONDS
            claude_token.write_fill(stale, 0.9, updated_at=100.0)
            claude_token.write_fill(live, 0.3, updated_at=100.0 + expiry)

            self.assertEqual(
                claude_token.pane_fill(live, current_time=101.0 + expiry),
                0.3,
            )
            self.assertFalse(stale.exists())
            self.assertTrue(live.exists())

    def test_pane_fill_accepts_fresh_legacy_float_records(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "pane" / "legacy.context"
            record.parent.mkdir()
            record.write_text("0.75\n", encoding="utf-8")
            os.utime(record, (1000.0, 1000.0))

            self.assertEqual(
                claude_token.pane_fill(record, current_time=1001.0), 0.75
            )

    def test_pane_fill_expires_legacy_records_by_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "pane" / "legacy.context"
            record.parent.mkdir()
            record.write_text("0.75\n", encoding="utf-8")
            os.utime(record, (1000.0, 1000.0))

            self.assertIsNone(
                claude_token.pane_fill(
                    record,
                    current_time=1001.0 + claude_token.CONTEXT_RECORD_TTL_SECONDS,
                )
            )
            self.assertFalse(record.exists())

    def test_pane_fill_reports_stale_record_cleanup_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "pane" / "stale.context"
            claude_token.write_fill(record, 0.9, updated_at=100.0)

            with mock.patch.object(
                Path, "unlink", side_effect=PermissionError("permission denied")
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "unable to aggregate context records"
                ):
                    claude_token.pane_fill(
                        record,
                        current_time=101.0
                        + claude_token.CONTEXT_RECORD_TTL_SECONDS,
                    )

    def test_pane_fill_rejects_malformed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "pane" / "broken.context"
            record.parent.mkdir()
            record.write_text('{"version":1,"fill":"high"}\n', encoding="utf-8")

            with self.assertRaisesRegex(
                RuntimeError, "unable to aggregate context records"
            ):
                claude_token.pane_fill(record)

    def test_session_start_refreshes_current_record_and_cleans_stale_records(self):
        with tempfile.TemporaryDirectory() as directory:
            context_dir = Path(directory) / "blackhole_contexts"
            pane_id = "550e8400e29b41d4a716446655440000"
            pane = context_dir / pane_id
            pane.mkdir(parents=True)
            stale = pane / "stale.context"
            stale.write_text("0.95\n", encoding="utf-8")
            os.utime(stale, (100.0, 100.0))
            observed_at = 101.0 + claude_token.CONTEXT_RECORD_TTL_SECONDS
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "new-session",
            }

            with mock.patch.object(
                claude_token, "CONTEXT_DIR", context_dir
            ), mock.patch.dict(
                os.environ, {"WARP_TERMINAL_SESSION_UUID": pane_id}, clear=True
            ), mock.patch.object(
                sys, "stdin", io.StringIO(json.dumps(event))
            ), mock.patch.object(
                claude_token.time, "time", return_value=observed_at
            ), mock.patch.object(
                claude_token, "emit_cursor", return_value=True
            ):
                self.assertEqual(claude_token.main(), 0)

            records = list(pane.glob("*.context"))
            self.assertEqual(len(records), 1)
            self.assertNotEqual(records[0], stale)
            self.assertEqual(
                json.loads(records[0].read_text(encoding="utf-8"))["fill"],
                0.0,
            )

    def test_session_end_removes_current_record_and_resets_empty_pane(self):
        with tempfile.TemporaryDirectory() as directory:
            context_dir = Path(directory) / "blackhole_contexts"
            pane_id = "550e8400e29b41d4a716446655440000"
            event = {
                "hook_event_name": "SessionEnd",
                "session_id": "ending-session",
            }
            with mock.patch.object(
                claude_token, "CONTEXT_DIR", context_dir
            ), mock.patch.dict(
                os.environ, {"WARP_TERMINAL_SESSION_UUID": pane_id}, clear=True
            ):
                record = claude_token.context_record(event)
                assert record is not None
                claude_token.write_fill(record, 0.8)
                with mock.patch.object(
                    sys, "stdin", io.StringIO(json.dumps(event))
                ), mock.patch.object(
                    claude_token, "emit_cursor", return_value=True
                ) as emit_cursor:
                    self.assertEqual(claude_token.main(), 0)

            self.assertFalse(record.exists())
            emit_cursor.assert_called_once_with(None)

    def test_cache_operations_take_and_release_an_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            original_dir = claude_token.CONTEXT_DIR
            claude_token.CONTEXT_DIR = Path(directory)
            record = Path(directory) / "pane" / "session.context"
            try:
                with mock.patch.object(claude_token.fcntl, "flock") as flock:
                    claude_token.write_fill(record, 0.5)

                self.assertEqual(
                    [call.args[1] for call in flock.call_args_list],
                    [claude_token.fcntl.LOCK_EX, claude_token.fcntl.LOCK_UN],
                )
            finally:
                claude_token.CONTEXT_DIR = original_dir

    def test_sync_cursor_publishes_while_holding_the_pane_lock(self):
        events = []

        @claude_token.contextmanager
        def observed_lock(_record):
            events.append("locked")
            try:
                yield
            finally:
                events.append("unlocked")

        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "pane" / "session.context"
            record.parent.mkdir()
            record.write_text("0.75\n", encoding="utf-8")
            with mock.patch.object(claude_token, "cache_lock", observed_lock):
                with mock.patch.object(
                    claude_token,
                    "emit_cursor",
                    side_effect=lambda fill: events.append(("emit", fill)) or True,
                ):
                    self.assertTrue(claude_token.sync_cursor(record))

        self.assertEqual(events, ["locked", ("emit", 0.75), "unlocked"])

    def test_remove_fill_does_not_hide_unexpected_directory_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            original_dir = claude_token.CONTEXT_DIR
            claude_token.CONTEXT_DIR = Path(directory)
            record = Path(directory) / "pane" / "session.context"
            claude_token.write_fill(record, 0.5)
            try:
                with mock.patch.object(
                    Path,
                    "rmdir",
                    side_effect=OSError(errno.EACCES, "permission denied"),
                ):
                    with self.assertRaises(PermissionError):
                        claude_token.remove_fill(record)
            finally:
                claude_token.CONTEXT_DIR = original_dir


class CursorChannelTests(unittest.TestCase):
    def test_cursor_sequence_round_trips_fill_and_checksum(self):
        sequence = claude_token.cursor_sequence(0.8)
        prefix = b"\033]12;#"
        self.assertTrue(sequence.startswith(prefix))
        self.assertTrue(sequence.endswith(b"\007"))
        encoded = sequence[len(prefix) : -1]
        red, green, blue = bytes.fromhex(encoded.decode("ascii"))
        high = green & 0xF
        low = blue & 0xF

        self.assertEqual(red >> 4, 0xF)
        self.assertEqual(green >> 4, 0xB)
        self.assertEqual(blue >> 4, 0x0)
        self.assertEqual(red & 0xF, high ^ low ^ 0x5)
        self.assertAlmostEqual(((high << 4) | low) / 250.0, 0.8)

    def test_cursor_sequence_resets_when_no_session_remains(self):
        self.assertEqual(claude_token.cursor_sequence(None), b"\033]112\007")

    def test_emit_cursor_uses_controlling_tty_without_process_scan(self):
        terminal = mock.mock_open()
        with mock.patch.object(Path, "open", terminal):
            with mock.patch.object(claude_token, "session_tty") as session_tty:
                self.assertTrue(claude_token.emit_cursor(0.5))

        session_tty.assert_not_called()
        terminal().write.assert_called_once_with(claude_token.cursor_sequence(0.5))


if __name__ == "__main__":
    unittest.main()
