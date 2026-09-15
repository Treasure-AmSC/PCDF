"""Tests for generated local input-manifest tooling."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from ntuple_wizard_core import WizardState, write_bundle


class ManifestHelperTest(unittest.TestCase):
    def test_directory_mode_writes_local_root_paths(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "download"
            root.mkdir()
            input_file = root / "DAOD_JETM16.1.pool.root"
            input_file.write_bytes(b"x" * 1025)
            manifest = Path(temporary) / "inputs.txt"

            result = subprocess.run(
                [sys.executable, "-B", str(helper)],
                check=False,
                text=True,
                capture_output=True,
                input=f"1\n{root}\n{manifest}\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(manifest.read_text(), f"{input_file}\n")

    def test_bundle_contains_manifest_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, bundle = write_bundle(WizardState(), Path(temporary))
            with tarfile.open(bundle) as archive:
                self.assertIn("make-manifest.py", archive.getnames())
                self.assertIn("run-pcdf.sh", archive.getnames())
                self.assertIn("run-pcdf.py", archive.getnames())
                helper = archive.extractfile("make-manifest.py")
                self.assertIsNotNone(helper)
                self.assertIn(b'"rich", "rucio-clients"', helper.read())

    def test_rucio_mode_strips_the_proxy_from_replica_pfns(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            package = workspace / "rucio"
            package.mkdir()
            (workspace / "rucio" / "__init__.py").write_text("")
            (package / "client.py").write_text(
                "import os\n"
                "class Client:\n"
                "    def list_replicas(self, dids, rse_expression):\n"
                "        assert dids == [{'scope': 'user.alice', 'name': 'dataset'}]\n"
                "        assert rse_expression == 'NERSC_LOCALGROUPDISK'\n"
                "        assert os.environ['RUCIO_CONFIG'].endswith('current/etc/rucio.cfg')\n"
                "        assert os.environ['RUCIO_AUTH_TYPE'] == 'x509_proxy'\n"
                "        assert os.environ['RUCIO_CLIENT_PROXY'] == os.environ['X509_USER_PROXY']\n"
                "        assert os.environ['X509_CERT_DIR'].endswith('grid-security-emi/certificates')\n"
                "        return iter([{'pfns': {'root://slac-proxy.example:1094//global/cfs/cdirs/m1234/atlas/file.root': {}}}])\n"
            )
            manifest = workspace / "inputs.txt"
            proxy = workspace / "x509up"
            proxy.write_text("test proxy")
            environment = {
                "PYTHONPATH": str(workspace),
                "PYTHONDONTWRITEBYTECODE": "1",
                "X509_USER_PROXY": str(proxy),
            }

            result = subprocess.run(
                [sys.executable, "-B", str(helper)],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                input=f"2\nuser.alice:dataset\n{manifest}\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(manifest.read_text(), "/global/cfs/cdirs/m1234/atlas/file.root\n")

    def test_rucio_mode_explains_how_to_create_a_missing_proxy(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            environment = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "X509_USER_PROXY": str(Path(temporary) / "missing-proxy"),
            }

            result = subprocess.run(
                [sys.executable, "-B", str(helper)],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                input="2\nuser.alice:dataset\nn\n",
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("lsetup emi", result.stdout)
            self.assertIn("voms-proxy-init -voms atlas", result.stdout)
            self.assertNotIn("lsetup rucio", result.stdout)

    def test_rucio_mode_preserves_existing_authentication_configuration(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            package = workspace / "rucio"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "client.py").write_text(
                "import os\n"
                "class Client:\n"
                "    def list_replicas(self, dids, rse_expression):\n"
                "        assert os.environ['RUCIO_AUTH_TYPE'] == 'oidc'\n"
                "        assert os.environ['RUCIO_ACCOUNT'] == 'alice'\n"
                "        return iter([{'pfns': {'root://proxy//global/cfs/file.root': {}}}])\n"
            )
            manifest = workspace / "inputs.txt"
            environment = {
                "PYTHONPATH": str(workspace),
                "PYTHONDONTWRITEBYTECODE": "1",
                "RUCIO_AUTH_TYPE": "oidc",
                "RUCIO_ACCOUNT": "alice",
            }

            result = subprocess.run(
                [sys.executable, "-B", str(helper)],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                input=f"2\nuser.alice:dataset\n{manifest}\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(manifest.read_text(), "/global/cfs/file.root\n")

    def test_rucio_mode_creates_a_proxy_with_a_child_scratch_directory(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            atlas_root = workspace / "atlas"
            config = atlas_root / "x86_64" / "rucio-clients" / "current" / "etc" / "rucio.cfg"
            config.parent.mkdir(parents=True)
            config.write_text("[client]\n")
            initializer = atlas_root / "wrappers" / "gridMW" / "voms-proxy-init"
            initializer.parent.mkdir(parents=True)
            initializer.write_text(
                "#!/bin/sh\n"
                "test -n \"$ALRB_tmpScratch\" || exit 19\n"
                ": > \"$X509_USER_PROXY\"\n"
            )
            initializer.chmod(0o755)
            package = workspace / "rucio"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "client.py").write_text(
                "class Client:\n"
                "    def list_replicas(self, dids, rse_expression):\n"
                "        return iter([{'pfns': {'root://proxy//global/cfs/file.root': {}}}])\n"
            )
            proxy = workspace / "x509up"
            manifest = workspace / "inputs.txt"
            environment = {
                "ATLAS_LOCAL_ROOT_BASE": str(atlas_root),
                "PYTHONPATH": str(workspace),
                "PYTHONDONTWRITEBYTECODE": "1",
                "X509_USER_PROXY": str(proxy),
            }

            result = subprocess.run(
                [sys.executable, "-B", str(helper)],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                input=f"2\nuser.alice:dataset\ny\n{manifest}\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(manifest.read_text(), "/global/cfs/file.root\n")


if __name__ == "__main__":
    unittest.main()
