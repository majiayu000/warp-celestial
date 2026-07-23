import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY / "scripts" / "check_compatibility.py"
SPEC = importlib.util.spec_from_file_location("check_compatibility", MODULE_PATH)
assert SPEC and SPEC.loader
check_compatibility = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_compatibility)


class CompatibilityTests(unittest.TestCase):
    def test_repository_manifest_matches_installer_and_patch(self):
        self.assertEqual(check_compatibility.validate_repository(REPOSITORY), [])

    def test_detects_patch_digest_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "repository"
            shutil.copytree(REPOSITORY, copy, ignore=shutil.ignore_patterns(".git", "target"))
            manifest_path = copy / "COMPATIBILITY.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["warp"]["patch_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors = check_compatibility.validate_repository(copy)

            self.assertIn(
                "renderer patch SHA-256 does not match the manifest", errors
            )

    def test_detects_installer_pin_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "repository"
            shutil.copytree(REPOSITORY, copy, ignore=shutil.ignore_patterns(".git", "target"))
            installer_path = copy / "install.sh"
            installer = installer_path.read_text(encoding="utf-8")
            installer_path.write_text(
                installer.replace(
                    'WARP_COMMIT="69ce3728acae0b01c2f457b65a90c144664686aa"',
                    f'WARP_COMMIT="{"1" * 40}"',
                ),
                encoding="utf-8",
            )

            errors = check_compatibility.validate_repository(copy)

            self.assertIn(
                "WARP_COMMIT disagrees with COMPATIBILITY.json", errors
            )


if __name__ == "__main__":
    unittest.main()
