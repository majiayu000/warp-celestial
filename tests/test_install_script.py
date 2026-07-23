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
            support = home / "support"
            app_dir = home / "apps"
            app_path = app_dir / "Warp Celestial.app"
            cache = home / "cache"
            bin_dir = home / ".local" / "bin"
            settings = home / ".claude" / "settings.json"
            hook = support / "claude-token.py"
            state = support / "claude-settings-state.json"

            app_path.mkdir(parents=True)
            cache.mkdir(parents=True)
            bin_dir.mkdir(parents=True)
            support.mkdir(parents=True)
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
            support = home / "support"
            target = support / "target"
            target.mkdir(parents=True)
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


if __name__ == "__main__":
    unittest.main()
