import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY / "scripts" / "check_release_contract.py"
SPEC = importlib.util.spec_from_file_location("check_release_contract", MODULE_PATH)
assert SPEC and SPEC.loader
check_release_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_release_contract)


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.git("init", "-b", "main", str(self.repository), cwd=Path("/"))
        self.git("config", "user.name", "Release Contract Tests")
        self.git("config", "user.email", "tests@example.com")
        (self.repository / "VERSION").write_text("0.1.1\n", encoding="utf-8")
        self.git("add", "VERSION")
        self.git("commit", "-m", "initial")
        self.main_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("tag", "v0.1.1")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def git(self, *arguments, cwd=None, check=True):
        return subprocess.run(
            ["git"] + list(arguments),
            cwd=str(cwd or self.repository),
            text=True,
            capture_output=True,
            check=check,
        )

    def validate(self, tag="v0.1.1", commit=None, main_ref="refs/heads/main"):
        return check_release_contract.validate_release_contract(
            self.repository, tag, commit or self.main_commit, main_ref
        )

    def test_accepts_exact_tag_on_main(self):
        self.assertEqual(self.validate(), [])

    def test_accepts_annotated_tag_on_main(self):
        self.git("tag", "-d", "v0.1.1")
        self.git("tag", "-a", "v0.1.1", "-m", "release")
        tag_object = self.git("rev-parse", "v0.1.1").stdout.strip()

        self.assertEqual(self.validate(commit=tag_object), [])

    def test_rejects_missing_exact_tag_reference(self):
        self.git("tag", "-d", "v0.1.1")

        errors = self.validate()

        self.assertTrue(
            any(error.startswith("cannot resolve release tag") for error in errors)
        )

    def test_rejects_wrong_tag_for_version(self):
        errors = self.validate(tag="v0.1.0")

        self.assertIn("release tag is 'v0.1.0', expected 'v0.1.1'", errors)

    def test_rejects_version_that_does_not_match_tag(self):
        (self.repository / "VERSION").write_text("0.1.2\n", encoding="utf-8")

        errors = self.validate()

        self.assertIn("release tag is 'v0.1.1', expected 'v0.1.2'", errors)

    def test_rejects_tagged_commit_from_side_branch(self):
        self.git("tag", "-d", "v0.1.1")
        self.git("switch", "-c", "release-side")
        (self.repository / "side.txt").write_text("side\n", encoding="utf-8")
        self.git("add", "side.txt")
        self.git("commit", "-m", "side")
        side_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("tag", "v0.1.1")

        errors = self.validate(commit=side_commit)

        self.assertIn(
            f"release commit {side_commit} is not an ancestor of refs/heads/main",
            errors,
        )

    def test_rejects_unknown_main_reference(self):
        errors = self.validate(main_ref="refs/remotes/origin/missing")

        self.assertTrue(
            any(error.startswith("cannot resolve main reference") for error in errors)
        )

    def test_rejects_unknown_release_commit(self):
        errors = self.validate(commit="refs/heads/missing")

        self.assertTrue(
            any(error.startswith("cannot resolve release commit") for error in errors)
        )

    def test_rejects_tag_that_points_to_a_different_commit(self):
        (self.repository / "next.txt").write_text("next\n", encoding="utf-8")
        self.git("add", "next.txt")
        self.git("commit", "-m", "next")
        next_commit = self.git("rev-parse", "HEAD").stdout.strip()

        errors = self.validate(commit=next_commit)

        self.assertTrue(
            any("not requested commit" in error for error in errors), errors
        )

    def test_rejects_invalid_version_before_using_it_as_a_reference(self):
        (self.repository / "VERSION").write_text("../main\n", encoding="utf-8")

        self.assertEqual(
            self.validate(), ["VERSION must contain one valid semantic version"]
        )

    def test_accepts_semver_2_version_matrix(self):
        versions = (
            "0.1.1",
            "1.0.0-alpha-",
            "1.0.0-rc.1+build.01",
            "0.0.0",
            "1.2.3+001",
        )

        for version in versions:
            with self.subTest(version=version):
                (self.repository / "VERSION").write_text(
                    f"{version}\n", encoding="utf-8"
                )

                self.assertEqual(
                    check_release_contract.read_version(self.repository),
                    (version, []),
                )

    def test_rejects_non_semver_2_version_matrix(self):
        versions = (
            "1.0.0-01",
            "1.0.0-alpha..1",
            "1.0.0+build..1",
            "1.0.0-",
            "1.0.0+",
            "01.0.0",
            "1.01.0",
            "1.0.01",
        )

        for version in versions:
            with self.subTest(version=version):
                (self.repository / "VERSION").write_text(
                    f"{version}\n", encoding="utf-8"
                )

                self.assertEqual(
                    check_release_contract.read_version(self.repository),
                    (None, ["VERSION must contain one valid semantic version"]),
                )

    def test_rejects_non_repository_git_errors(self):
        other = Path(self.temporary_directory.name) / "not-a-repository"
        other.mkdir()
        (other / "VERSION").write_text("0.1.1\n", encoding="utf-8")

        errors = check_release_contract.validate_release_contract(
            other, "v0.1.1", self.main_commit, "refs/heads/main"
        )

        self.assertTrue(
            any(error.startswith("cannot resolve release tag") for error in errors)
        )
        self.assertTrue(
            any(error.startswith("cannot resolve release commit") for error in errors)
        )
        self.assertTrue(
            any(error.startswith("cannot resolve main reference") for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
