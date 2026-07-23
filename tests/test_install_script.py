import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY / "install.sh"
CONFIGURATOR = REPOSITORY / "scripts" / "configure_claude.py"
BRIDGE = REPOSITORY / "claude-token.py"
MARKER_VERSION = "warp-celestial-managed-v1"


def write_marker(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".warp-celestial-managed").write_text(
        f"{MARKER_VERSION}\n{root.resolve()}\n", encoding="utf-8"
    )


class InstallScriptTests(unittest.TestCase):
    def test_rejects_conflicting_actions(self):
        result = subprocess.run(
            [str(INSTALLER), "--check", "--doctor"],
            cwd=REPOSITORY,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Choose only one", result.stderr)

    def test_uninstall_removes_managed_files_and_settings_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            support = home / ".local" / "share" / "warp-celestial"
            app_dir = home / "apps"
            app_path = app_dir / "Warp Celestial.app"
            cache = home / ".cache" / "warp" / "blackhole_contexts"
            bin_dir = home / ".local" / "bin"
            settings = home / ".claude" / "settings.json"
            hook = support / "claude-token.py"
            state = support / "claude-settings-state.json"

            app_path.mkdir(parents=True)
            write_marker(cache)
            bin_dir.mkdir(parents=True)
            write_marker(support)
            shutil.copy2(BRIDGE, hook)
            hook.chmod(0o755)
            shutil.copy2(BRIDGE, bin_dir / "warp-celestial")
            subprocess.run(
                [
                    "python3",
                    str(CONFIGURATOR),
                    str(settings),
                    str(hook),
                    str(state),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            configured = json.loads(settings.read_text(encoding="utf-8"))
            configured["theme"] = "dark"
            settings.write_text(json.dumps(configured), encoding="utf-8")

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "WARP_CELESTIAL_HOME": str(support),
                    "WARP_CELESTIAL_APP_DIR": str(app_dir),
                    "WARP_CELESTIAL_CACHE_DIR": str(cache),
                    "CLAUDE_SETTINGS_FILE": str(settings),
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--uninstall", "--yes"],
                cwd=REPOSITORY,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(app_path.exists())
            self.assertFalse((bin_dir / "warp-celestial").exists())
            self.assertFalse(cache.exists())
            self.assertFalse(support.exists())
            remaining = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(remaining, {"theme": "dark"})
            self.assertTrue(list(settings.parent.glob("settings.json.backup.*")))

    def test_clean_build_cache_preserves_support_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            support = home / ".local" / "share" / "warp-celestial"
            target = support / "target"
            target.mkdir(parents=True)
            write_marker(support)
            marker = support / "claude-token.py"
            marker.write_text("managed bridge\n", encoding="utf-8")

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "WARP_CELESTIAL_HOME": str(support),
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--clean-build-cache", "--yes"],
                cwd=REPOSITORY,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())
            self.assertTrue(marker.exists())

    def test_uninstall_rejects_broad_or_unowned_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()

            broad_environment = os.environ.copy()
            broad_environment.update(
                {
                    "HOME": str(home),
                    "WARP_CELESTIAL_HOME": "/Users",
                }
            )
            broad = subprocess.run(
                [str(INSTALLER), "--uninstall", "--yes"],
                cwd=REPOSITORY,
                env=broad_environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(broad.returncode, 1)
            self.assertIn("must end in warp-celestial", broad.stderr)

            unowned = home / "Documents" / "warp-celestial"
            sentinel = unowned / "do-not-delete.txt"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("user data\n", encoding="utf-8")
            unowned_environment = os.environ.copy()
            unowned_environment.update(
                {
                    "HOME": str(home),
                    "WARP_CELESTIAL_HOME": str(unowned),
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--uninstall", "--yes"],
                cwd=REPOSITORY,
                env=unowned_environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("without a managed marker", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user data\n")

    def test_uninstall_refuses_to_delete_a_still_referenced_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            support = home / ".local" / "share" / "warp-celestial"
            settings = home / ".claude" / "settings.json"
            hook = support / "claude-token.py"
            state = support / "claude-settings-state.json"
            write_marker(support)
            shutil.copy2(BRIDGE, hook)
            hook.chmod(0o755)

            command = str(hook.resolve())
            settings.parent.mkdir(parents=True)
            settings.write_text(
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
                            for event in ("SessionStart", "SessionEnd")
                        },
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "python3",
                    str(CONFIGURATOR),
                    str(settings),
                    str(hook),
                    str(state),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "WARP_CELESTIAL_HOME": str(support),
                    "CLAUDE_SETTINGS_FILE": str(settings),
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--uninstall", "--yes"],
                cwd=REPOSITORY,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("still references the bridge", result.stderr)
            self.assertTrue(hook.exists())
            self.assertTrue(support.exists())

    def test_uninstall_refuses_user_edited_wrapper_referencing_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            support = home / ".local" / "share" / "warp-celestial"
            settings = home / ".claude" / "settings.json"
            hook = support / "claude-token.py"
            state = support / "claude-settings-state.json"
            write_marker(support)
            shutil.copy2(BRIDGE, hook)
            hook.chmod(0o755)

            subprocess.run(
                [
                    "python3",
                    str(CONFIGURATOR),
                    str(settings),
                    str(hook),
                    str(state),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            configured = json.loads(settings.read_text(encoding="utf-8"))
            configured["statusLine"] = {
                "type": "command",
                "command": f"python3 '{hook.resolve()}' --compact",
            }
            settings.write_text(json.dumps(configured), encoding="utf-8")

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "WARP_CELESTIAL_HOME": str(support),
                    "CLAUDE_SETTINGS_FILE": str(settings),
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--uninstall", "--yes"],
                cwd=REPOSITORY,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("still references the bridge", result.stderr)
            self.assertTrue(hook.exists())
            self.assertTrue(support.exists())
            remaining = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(remaining["statusLine"], configured["statusLine"])


if __name__ == "__main__":
    unittest.main()
