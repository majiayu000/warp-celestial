import errno
import importlib.util
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-token.py"
SPEC = importlib.util.spec_from_file_location("claude_token", MODULE_PATH)
assert SPEC and SPEC.loader
claude_token = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(claude_token)


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
            claude_token.write_fill(context_file, 0.625)
            self.assertEqual(context_file.read_text(encoding="utf-8"), "0.625000\n")
            self.assertEqual(list(context_file.parent.glob(".session.context.*")), [])

    def test_remove_fill_only_removes_the_selected_session(self):
        with tempfile.TemporaryDirectory() as directory:
            pane_dir = Path(directory) / "pane"
            first = pane_dir / "first.context"
            second = pane_dir / "second.context"
            claude_token.write_fill(first, 0.8)
            claude_token.write_fill(second, 0.2)

            claude_token.remove_fill(first)

            self.assertFalse(first.exists())
            self.assertEqual(second.read_text(encoding="utf-8"), "0.200000\n")

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
