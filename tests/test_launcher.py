import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "warp_celestial_launcher.py"
)
SPEC = importlib.util.spec_from_file_location("warp_celestial_launcher", MODULE_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_normal_launch_defaults_and_quality(self):
        self.assertEqual(
            launcher.parse_arguments([]),
            launcher.LaunchConfig("blackhole", "auto", None),
        )
        self.assertEqual(
            launcher.parse_arguments(["sun", "low"]),
            launcher.LaunchConfig("sun", "low", None),
        )
        self.assertEqual(
            launcher.parse_arguments(["sun"]),
            launcher.LaunchConfig("sun", "auto", None),
        )
        self.assertEqual(
            launcher.parse_arguments(["blackhole", "balanced"]),
            launcher.LaunchConfig("blackhole", "balanced", None),
        )

    def test_demo_selects_effect_quality_and_fill(self):
        self.assertEqual(
            launcher.parse_arguments(["--demo", "sun", "high", "0.9"]),
            launcher.LaunchConfig("sun", "high", 0.9),
        )
        self.assertEqual(
            launcher.parse_arguments(["--demo", "low"]),
            launcher.LaunchConfig("blackhole", "low", 0.65),
        )
        self.assertEqual(
            launcher.parse_arguments(["--demo"]),
            launcher.LaunchConfig("blackhole", "high", 0.65),
        )

    def test_demo_rejects_invalid_fill_and_extra_arguments(self):
        for arguments in (
            ["--demo", "1.1"],
            ["--demo", "sun", "fast"],
            ["--demo", "sun", "high", "0.8", "extra"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    launcher.parse_arguments(arguments)

    def test_main_uses_array_arguments_without_a_shell(self):
        with mock.patch.object(
            launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run:
            result = launcher.main(
                ["/tmp/Warp Celestial.app", "--demo", "sun", "balanced", "0.75"]
            )

        self.assertEqual(result, 0)
        run.assert_called_once_with(
            [
                "/usr/bin/open",
                "-na",
                "/tmp/Warp Celestial.app",
                "--env",
                "WARP_CELESTIAL=sun",
                "--env",
                "WARP_CELESTIAL_QUALITY=balanced",
                "--env",
                "WARP_CELESTIAL_DEMO=0.750000",
            ],
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
