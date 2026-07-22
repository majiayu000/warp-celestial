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


if __name__ == "__main__":
    unittest.main()
