import importlib.util
import json
import shlex
import subprocess
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
            hook_path = Path(directory) / "hook scripts" / "claude token.py"
            hook_path.parent.mkdir()
            hook_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            hook_path.chmod(0o755)

            changed, backup = configure_claude.configure(settings_path, hook_path)

            self.assertTrue(changed)
            self.assertIsNone(backup)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            command = shlex.quote(str(hook_path.resolve()))
            self.assertEqual(
                settings["statusLine"], {"type": "command", "command": command}
            )
            self.assertEqual(
                subprocess.run(["/bin/sh", "-c", command], check=False).returncode,
                0,
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

    def test_unconfigure_restores_previous_status_line_and_preserves_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            state_path = Path(directory) / "install-state.json"
            hook_path = Path(directory) / "claude-token.py"
            original = {
                "theme": "dark",
                "statusLine": {"type": "command", "command": "my-status"},
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "existing-hook"}]}
                    ]
                },
            }
            settings_path.write_text(json.dumps(original), encoding="utf-8")

            configure_claude.configure(settings_path, hook_path, state_path)
            changed, backup = configure_claude.unconfigure(
                settings_path, hook_path, state_path
            )

            self.assertTrue(changed)
            self.assertIsNotNone(backup)
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")), original
            )

    def test_unconfigure_preserves_status_line_changed_after_install(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            state_path = Path(directory) / "install-state.json"
            hook_path = Path(directory) / "claude-token.py"
            settings_path.write_text(
                json.dumps(
                    {"statusLine": {"type": "command", "command": "original-status"}}
                ),
                encoding="utf-8",
            )
            configure_claude.configure(settings_path, hook_path, state_path)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["statusLine"] = {"type": "command", "command": "new-user-status"}
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            configure_claude.unconfigure(settings_path, hook_path, state_path)

            updated = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["statusLine"],
                {"type": "command", "command": "new-user-status"},
            )
            self.assertNotIn("hooks", updated)

    def test_reinstall_restores_the_latest_user_status_line_on_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            state_path = Path(directory) / "install-state.json"
            hook_path = Path(directory) / "claude-token.py"
            settings_path.write_text(
                json.dumps(
                    {"statusLine": {"type": "command", "command": "before-install"}}
                ),
                encoding="utf-8",
            )

            configure_claude.configure(settings_path, hook_path, state_path)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["statusLine"] = {
                "type": "command",
                "command": "changed-after-install",
            }
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            configure_claude.configure(settings_path, hook_path, state_path)
            configure_claude.unconfigure(settings_path, hook_path, state_path)

            updated = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["statusLine"],
                {"type": "command", "command": "changed-after-install"},
            )

    def test_matching_configuration_without_state_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            state_path = Path(directory) / "install-state.json"
            hook_path = Path(directory) / "claude-token.py"
            command = shlex.quote(str(hook_path.resolve()))
            settings_path.write_text(
                json.dumps(
                    {
                        "statusLine": {"type": "command", "command": command},
                        "hooks": {
                            event: [
                                {
                                    "hooks": [
                                        {"type": "command", "command": command}
                                    ]
                                }
                            ]
                            for event in configure_claude.LIFECYCLE_EVENTS
                        },
                    }
                ),
                encoding="utf-8",
            )

            changed, backup = configure_claude.configure(
                settings_path, hook_path, state_path
            )
            removed, _ = configure_claude.unconfigure(
                settings_path, hook_path, state_path
            )

            self.assertFalse(changed)
            self.assertIsNone(backup)
            self.assertFalse(removed)
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                {
                    "statusLine": {"type": "command", "command": command},
                    "hooks": {
                        event: [
                            {
                                "hooks": [
                                    {"type": "command", "command": command}
                                ]
                            }
                        ]
                        for event in configure_claude.LIFECYCLE_EVENTS
                    },
                },
            )

    def test_unconfigure_does_not_remove_preexisting_matching_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            state_path = Path(directory) / "install-state.json"
            hook_path = Path(directory) / "claude-token.py"
            command = shlex.quote(str(hook_path.resolve()))
            original = {
                "statusLine": {"type": "command", "command": command},
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": command}]}
                    ],
                    "SessionEnd": [
                        {"hooks": [{"type": "command", "command": command}]}
                    ],
                },
            }
            settings_path.write_text(json.dumps(original), encoding="utf-8")

            configure_claude.configure(settings_path, hook_path, state_path)
            changed, _ = configure_claude.unconfigure(
                settings_path, hook_path, state_path
            )

            self.assertFalse(changed)
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")), original
            )

    def test_legacy_unconfigure_removes_only_exact_managed_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            hook_path = Path(directory) / "claude-token.py"
            command = shlex.quote(str(hook_path.resolve()))
            settings_path.write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "statusLine": {"type": "command", "command": command},
                        "hooks": {
                            "SessionStart": [
                                {
                                    "hooks": [
                                        {"type": "command", "command": command},
                                        {"type": "command", "command": "keep-me"},
                                    ]
                                }
                            ],
                            "SessionEnd": [
                                {"hooks": [{"type": "command", "command": command}]}
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            changed, _ = configure_claude.unconfigure(settings_path, hook_path)

            self.assertTrue(changed)
            updated = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["theme"], "dark")
            self.assertNotIn("statusLine", updated)
            self.assertEqual(
                updated["hooks"]["SessionStart"],
                [{"hooks": [{"type": "command", "command": "keep-me"}]}],
            )
            self.assertNotIn("SessionEnd", updated["hooks"])


if __name__ == "__main__":
    unittest.main()
