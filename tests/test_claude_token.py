import importlib.util
import tempfile
import unittest
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
    def test_write_fill_replaces_the_file_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            context_file = Path(directory) / "nested" / "blackhole_context"
            original_path = claude_token.CONTEXT_FILE
            claude_token.CONTEXT_FILE = context_file
            try:
                claude_token.write_fill(0.625)
                self.assertEqual(context_file.read_text(encoding="utf-8"), "0.625000\n")
                self.assertEqual(list(context_file.parent.glob(".blackhole_context.*")), [])
            finally:
                claude_token.CONTEXT_FILE = original_path

    def test_remove_fill_accepts_a_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            original_path = claude_token.CONTEXT_FILE
            claude_token.CONTEXT_FILE = Path(directory) / "missing"
            try:
                claude_token.remove_fill()
            finally:
                claude_token.CONTEXT_FILE = original_path


if __name__ == "__main__":
    unittest.main()
