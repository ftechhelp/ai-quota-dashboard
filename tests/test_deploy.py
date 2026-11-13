import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "deploy").mkdir()
        source = Path(__file__).resolve().parents[1] / "deploy" / "deploy.sh"
        (self.root / "deploy" / "deploy.sh").write_text(source.read_text())
        (self.root / "tests").mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "docker.log"
        docker = self.bin / "docker"
        docker.write_text("""#!/bin/bash
echo "${DASHBOARD_IMAGE:-} $*" >> "$DOCKER_LOG"
if [[ "$1" == inspect ]]; then echo sha256:previous; exit 0; fi
if [[ "$*" == *' build dashboard' && "${FAIL_BUILD:-}" == 1 ]]; then exit 1; fi
if [[ "$1" == run && "${FAIL_TEST:-}" == 1 ]]; then exit 1; fi
if [[ "$*" == *' up '* && "${FAIL_UP:-}" == 1 &&
      "$DASHBOARD_IMAGE" != sha256:previous ]]; then exit 1; fi
""")
        docker.chmod(0o755)
        self.sha = "a" * 40
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "DOCKER_LOG": str(self.log), "GITHUB_SHA": self.sha}

    def run_deploy(self):
        return subprocess.run(["bash", "deploy/deploy.sh"], cwd=self.root,
                              env=self.env, text=True, capture_output=True)

    def test_success_builds_and_tests_before_up(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertLess(log.index(" build dashboard"), log.index(" run --rm"))
        self.assertLess(log.index(" run --rm"), log.index(" up -d"))

    def test_failed_deploy_restores_previous_image(self):
        self.env["FAIL_UP"] = "1"
        result = self.run_deploy()
        self.assertNotEqual(result.returncode, 0)
        lines = self.log.read_text().splitlines()
        self.assertTrue(any(
            line.startswith("sha256:previous compose") and " up " in line
            for line in lines
        ))

    def test_failed_build_does_not_replace_container(self):
        self.env["FAIL_BUILD"] = "1"
        self.assertNotEqual(self.run_deploy().returncode, 0)
        self.assertNotIn(" up ", self.log.read_text())

    def test_failed_tests_do_not_replace_container(self):
        self.env["FAIL_TEST"] = "1"
        self.assertNotEqual(self.run_deploy().returncode, 0)
        self.assertNotIn(" up ", self.log.read_text())

    def test_invalid_commit_does_not_invoke_docker(self):
        self.env["GITHUB_SHA"] = "invalid"
        self.assertNotEqual(self.run_deploy().returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
