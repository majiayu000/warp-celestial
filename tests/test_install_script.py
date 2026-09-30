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

    def test_uninstall_rejects_symlink_roots_before_mutation(self):
        for root_name, layout in (
            ("support", "direct"), ("cache", "direct"),
            ("support", "dangling"), ("cache", "dangling"),
            ("support", "parent_dotdot"), ("cache", "parent_dotdot"),
        ):
            for suffix in ("", "/", "//", "/."):
                with self.subTest(root=root_name, layout=layout, suffix=suffix):
                    with tempfile.TemporaryDirectory() as directory:
                        home = Path(directory) / "home"
                        support = home / ".local/share/warp-celestial"
                        cache = home / ".cache/warp/blackhole_contexts"
                        app_dir = home / "apps"
                        app_path = app_dir / "Warp Celestial.app"
                        launcher = home / ".local/bin/warp-celestial"
                        settings = home / ".claude/settings.json"
                        for root in (support, cache):
                            write_marker(root)
                            (root / "sentinel").write_text("keep\n", encoding="utf-8")
                        app_path.mkdir(parents=True)
                        launcher.parent.mkdir(parents=True)
                        launcher.write_text("keep\n", encoding="utf-8")
                        settings.parent.mkdir(parents=True)
                        settings.write_text('{"theme": "dark"}\n', encoding="utf-8")
                        root = support if root_name == "support" else cache
                        link = home / "managed-alias"
                        configured = str(link)
                        if layout == "parent_dotdot":
                            parent = home / "nested/child"
                            parent.mkdir(parents=True)
                            alias = home / "parent-alias"
                            alias.symlink_to(parent, target_is_directory=True)
                            link = parent.parent / root.name
                            configured = str(alias) + "/../" + root.name
                            # Match the marker written by the existing installer.
                            (root / ".warp-celestial-managed").write_text(
                                f"{MARKER_VERSION}\n"
                                f"{os.path.realpath(os.path.abspath(configured))}\n",
                                encoding="utf-8",
                            )
                        link.symlink_to(
                            home / "missing" if layout == "dangling" else root,
                            target_is_directory=True,
                        )
                        environment = os.environ.copy()
                        environment.update(
                            {
                                "HOME": str(home),
                                "WARP_CELESTIAL_HOME": str(support),
                                "WARP_CELESTIAL_CACHE_DIR": str(cache),
                                "WARP_CELESTIAL_APP_DIR": str(app_dir),
                                "CLAUDE_SETTINGS_FILE": str(settings),
                            }
                        )
                        key = (
                            "WARP_CELESTIAL_HOME" if root_name == "support"
                            else "WARP_CELESTIAL_CACHE_DIR"
                        )
                        environment[key] = configured + suffix
                        markers = {
                            root: (root / ".warp-celestial-managed").read_bytes()
                            for root in (support, cache)
                        }
                        result = subprocess.run(
                            [str(INSTALLER), "--uninstall", "--yes"],
                            cwd=REPOSITORY,
                            env=environment,
                            text=True,
                            capture_output=True,
                            check=False,
                        )

                        self.assertEqual(result.returncode, 1, result.stdout)
                        self.assertIn("must not be a symbolic link", result.stderr)
                        self.assertNotIn("was uninstalled", result.stdout)
                        self.assertTrue(link.is_symlink())
                        for root in (support, cache):
                            self.assertEqual(
                                (root / "sentinel").read_text(encoding="utf-8"), "keep\n"
                            )
                            self.assertEqual(
                                (root / ".warp-celestial-managed").read_bytes(), markers[root]
                            )
                        self.assertTrue(app_path.is_dir())
                        self.assertEqual(launcher.read_text(encoding="utf-8"), "keep\n")
                        self.assertEqual(
                            settings.read_text(encoding="utf-8"), '{"theme": "dark"}\n'
                        )

    def test_install_preparation_rejects_symlink_roots(self):
        for prepare, variable, basename in (
            ("prepare_install_root", "INSTALL_ROOT", "warp-celestial"),
            ("prepare_context_root", "CONTEXT_DIR", "blackhole_contexts"),
        ):
            for marked, layout in (
                (False, "direct"), (True, "direct"),
                (False, "parent_dotdot"), (True, "parent_dotdot"),
            ):
                with self.subTest(prepare=prepare, marked=marked, layout=layout):
                    with tempfile.TemporaryDirectory() as directory:
                        home = Path(directory) / "home"
                        root = home / "canonical" / basename
                        root.mkdir(parents=True)
                        if marked:
                            write_marker(root)
                        link = home / "managed-alias"
                        configured = str(link)
                        if layout == "parent_dotdot":
                            parent = home / "nested/child"
                            parent.mkdir(parents=True)
                            alias = home / "parent-alias"
                            alias.symlink_to(parent, target_is_directory=True)
                            link = parent.parent / basename
                            configured = str(alias) + "/../" + basename
                        link.symlink_to(root, target_is_directory=True)
                        before = sorted(path.name for path in root.iterdir())
                        environment = os.environ.copy()
                        environment.update(
                            {
                                "HOME": str(home),
                                variable: configured,
                                "INSTALL_MARKER": configured + "/.warp-celestial-managed",
                                "CACHE_MARKER": configured + "/.warp-celestial-managed",
                                "SOURCE_DIR": configured + "/warp",
                                "MANAGED_MARKER_VERSION": MARKER_VERSION,
                            }
                        )
                        result = subprocess.run(
                            [
                                "bash", "-c",
                                'set -Eeuo pipefail; '
                                'fail() { printf "%s\\n" "$*" >&2; exit 1; }; '
                                'check_command() { command -v "$1" >/dev/null; }; '
                                'source "$1"; "$2"',
                                "test-install-preparation",
                                str(REPOSITORY / "scripts/install_safety.sh"),
                                prepare,
                            ],
                            cwd=REPOSITORY,
                            env=environment,
                            text=True,
                            capture_output=True,
                            check=False,
                        )

                        self.assertEqual(result.returncode, 1, result.stdout)
                        self.assertIn("must not be a symbolic link", result.stderr)
                        self.assertTrue(link.is_symlink())
                        self.assertEqual(sorted(path.name for path in root.iterdir()), before)

    def test_preflight_rejects_cache_symlinks_before_installation(self):
        for action in ("check", "install"):
            for dangling in (False, True):
                with self.subTest(action=action, dangling=dangling):
                    with tempfile.TemporaryDirectory() as directory:
                        home = Path(directory) / "home"
                        home.mkdir()
                        support = home / "support/warp-celestial"
                        cache = home / "cache/blackhole_contexts"
                        if not dangling:
                            write_marker(cache)
                            (cache / "sentinel").write_text("keep\n", encoding="utf-8")
                        link = home / "cache-alias"
                        link.symlink_to(cache, target_is_directory=True)
                        if action == "check":
                            write_marker(support)
                            bundle = support / "cargo-bundle"
                            (bundle / "bin").mkdir(parents=True)
                            executable = bundle / "bin/cargo-bundle"
                            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                            executable.chmod(0o755)
                            (bundle / ".warp-celestial-revision").write_text(
                                "739f92c37c789b5511a448a389cbc76fcebd99df\n",
                                encoding="utf-8",
                            )
                        tools = home / "tools"
                        tools.mkdir()
                        trace = home / "build-commands"
                        stubs = {
                            "uname": "echo Darwin",
                            "df": "printf 'Filesystem blocks Used Available Capacity Mounted\\nfixture 999999999 0 999999999 0%% /\\n'",
                            "git": 'echo git >> "$BUILD_TRACE"; exit 91',
                            "cargo": 'echo cargo >> "$BUILD_TRACE"; exit 91',
                            "rustc": "exit 91",
                            "xcode-select": "exit 0",
                            "xcrun": "exit 0",
                            "xcodebuild": "exit 0",
                            "ditto": 'echo ditto >> "$BUILD_TRACE"; exit 91',
                            "jq": "exit 0",
                        }
                        for name, body in stubs.items():
                            executable = tools / name
                            executable.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
                            executable.chmod(0o755)
                        developer = home / "developer"
                        (developer / "usr/bin").mkdir(parents=True)
                        shutil.copy2(tools / "xcodebuild", developer / "usr/bin/xcodebuild")
                        environment = os.environ.copy()
                        environment.update({
                            "HOME": str(home),
                            "PATH": str(tools) + os.pathsep + environment["PATH"],
                            "DEVELOPER_DIR": str(developer),
                            "WARP_CELESTIAL_HOME": str(support),
                            "WARP_CELESTIAL_CACHE_DIR": str(link) + "/.",
                            "BUILD_TRACE": str(trace),
                        })
                        arguments = ["--check"] if action == "check" else ["--yes", "--no-launch"]
                        result = subprocess.run(
                            [str(INSTALLER)] + arguments,
                            cwd=REPOSITORY, env=environment, text=True,
                            capture_output=True, check=False,
                        )

                        self.assertEqual(result.returncode, 1, result.stdout)
                        self.assertIn("must not be a symbolic link", result.stderr)
                        self.assertNotIn("Preflight check passed", result.stdout)
                        self.assertFalse(trace.exists(), result.stdout)
                        self.assertTrue(link.is_symlink())
                        if action == "install":
                            self.assertFalse(support.exists())
                        if not dangling:
                            self.assertEqual((cache / "sentinel").read_text(encoding="utf-8"), "keep\n")
                            self.assertTrue((cache / ".warp-celestial-managed").is_file())
                        else:
                            self.assertFalse(cache.exists())

    def test_install_and_uninstall_allow_parent_symlink_with_dotdot(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            parent = home / "nested/child"
            parent.mkdir(parents=True)
            alias = home / "parent-alias"
            alias.symlink_to(parent, target_is_directory=True)
            support = parent.parent / "warp-celestial"
            cache = parent.parent / "blackhole_contexts"
            configured_support = str(alias) + "/../warp-celestial"
            configured_cache = str(alias) + "/../blackhole_contexts"
            environment = os.environ.copy()
            environment.update({
                "HOME": str(home),
                "INSTALL_ROOT": configured_support,
                "CONTEXT_DIR": configured_cache,
                "INSTALL_MARKER": configured_support + "/.warp-celestial-managed",
                "CACHE_MARKER": configured_cache + "/.warp-celestial-managed",
                "SOURCE_DIR": configured_support + "/warp",
                "MANAGED_MARKER_VERSION": MARKER_VERSION,
                "WARP_CELESTIAL_HOME": configured_support,
                "WARP_CELESTIAL_CACHE_DIR": configured_cache,
                "WARP_CELESTIAL_APP_DIR": str(home / "apps"),
                "CLAUDE_SETTINGS_FILE": str(home / "settings.json"),
            })
            prepared = subprocess.run(
                [
                    "bash", "-c",
                    'set -Eeuo pipefail; '
                    'fail() { printf "%s\\n" "$*" >&2; exit 1; }; '
                    'check_command() { command -v "$1" >/dev/null; }; '
                    'source "$1"; prepare_install_root; prepare_context_root',
                    "test-parent-symlink", str(REPOSITORY / "scripts/install_safety.sh"),
                ],
                cwd=REPOSITORY, env=environment, text=True, capture_output=True, check=False,
            )
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            for root in (support, cache):
                self.assertEqual(
                    (root / ".warp-celestial-managed").read_text(encoding="utf-8"),
                    f"{MARKER_VERSION}\n{root.resolve()}",
                )
                (root / "sentinel").write_text("managed\n", encoding="utf-8")
            removed = subprocess.run(
                [str(INSTALLER), "--uninstall", "--yes"],
                cwd=REPOSITORY, env=environment, text=True, capture_output=True, check=False,
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(support.exists())
            self.assertFalse(cache.exists())
            self.assertTrue(alias.is_symlink())
            self.assertTrue(parent.is_dir())

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
