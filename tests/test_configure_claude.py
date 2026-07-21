import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "configure_claude.py"
SPEC = importlib.util.spec_from_file_location("configure_claude", MODULE_PATH)
assert SPEC and SPEC.loader
configure_claude = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure_claude)


class ConfigureClaudeTests(unittest.TestCase):
    def test_creates_status_line_and_lifecycle_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / ".claude" / "settings.json"
            hook_path = Path(directory) / "claude-token.py"

            changed, backup = configure_claude.configure(settings_path, hook_path)

            self.assertTrue(changed)
            self.assertIsNone(backup)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            command = str(hook_path.resolve())
            self.assertEqual(
                settings["statusLine"], {"type": "command", "command": command}
            )
            for event in configure_claude.LIFECYCLE_EVENTS:
                self.assertEqual(
                    settings["hooks"][event],
                    [{"hooks": [{"type": "command", "command": command}]}],
                )

    def test_preserves_existing_settings_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            original = {
                "theme": "dark",
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "existing-hook"}]}
                    ]
                },
            }
            settings_path.write_text(json.dumps(original), encoding="utf-8")

            changed, backup = configure_claude.configure(
                settings_path, Path(directory) / "claude-token.py"
            )

            self.assertTrue(changed)
            self.assertIsNotNone(backup)
            assert backup
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), original)
            updated = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["theme"], "dark")
            self.assertEqual(
                updated["hooks"]["SessionStart"][0], original["hooks"]["SessionStart"][0]
            )

    def test_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            hook_path = Path(directory) / "claude-token.py"
            configure_claude.configure(settings_path, hook_path)

            changed, backup = configure_claude.configure(settings_path, hook_path)

            self.assertFalse(changed)
            self.assertIsNone(backup)
            self.assertEqual(list(Path(directory).glob("settings.json.backup.*")), [])

    def test_rejects_an_invalid_hooks_shape(self):
        with self.assertRaisesRegex(ValueError, "hooks setting must be a JSON object"):
            configure_claude.ensure_lifecycle_hook({"hooks": []}, "SessionStart", "hook")


if __name__ == "__main__":
    unittest.main()
