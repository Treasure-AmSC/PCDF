"""Tests for generated local input-manifest tooling."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from ntuple_wizard_core import BUNDLE_ROOT_NAME, WizardState, build_condor, build_python, write_bundle


class ManifestHelperTest(unittest.TestCase):
    def test_generated_converter_uses_local_reader_and_splits_constituents(self) -> None:
        source = build_python(WizardState())

        self.assertIn('handler=up.source.file.MemmapSource', source)
        self.assertIn('aliases.pop("Const", None)', source)

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
                names = archive.getnames()
                self.assertIn("pcdf-ntuple/code/make-manifest.py", names)
                self.assertIn("pcdf-ntuple/run-pcdf.sh", names)
                self.assertIn("pcdf-ntuple/code/run-pcdf.py", names)
                for directory in ("code", "output", "logs"):
                    self.assertIn(f"pcdf-ntuple/{directory}", names)
                self.assertNotIn("pcdf-ntuple/input", names)
                helper = archive.extractfile("pcdf-ntuple/code/make-manifest.py")
                self.assertIsNotNone(helper)
                self.assertIn(b'"rich", "rucio-clients"', helper.read())

    def test_bundle_archive_does_not_include_existing_runtime_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            runtime_output = output_dir / BUNDLE_ROOT_NAME / "output"
            runtime_output.mkdir(parents=True)
            (runtime_output / "previous.parquet").write_bytes(b"old result")

            _, _, bundle = write_bundle(WizardState(), output_dir)

            with tarfile.open(bundle) as archive:
                self.assertNotIn("pcdf-ntuple/output/previous.parquet", archive.getnames())

    def test_htcondor_bundle_queues_one_shared_filesystem_job_per_input(self) -> None:
        state = WizardState(
            scheduler="condor",
            manifest="./inputs.txt",
            output_base="./output",
            condor_cpus=2,
            condor_memory_mb=6144,
            condor_disk_mb=8192,
            condor_requirements='OpSysAndVer == "AlmaLinux9"',
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            _, submit_file, bundle = write_bundle(state, output_dir)
            submit_text = submit_file.read_text()
            self.assertEqual(submit_file.name, "submit-pcdf-ntuple.condor")
            self.assertIn("request_cpus = 2", submit_text)
            self.assertIn("request_memory = 6144 MB", submit_text)
            self.assertIn("request_disk = 8192 MB", submit_text)
            self.assertIn('requirements = OpSysAndVer == "AlmaLinux9"', submit_text)
            self.assertIn('queue input_file from "inputs.txt"', submit_text)
            self.assertIn("should_transfer_files = NO", submit_text)
            with tarfile.open(bundle) as archive:
                names = archive.getnames()
                self.assertIn("pcdf-ntuple/code/submit-pcdf-ntuple.condor", names)
                self.assertIn("pcdf-ntuple/code/run-pcdf-condor-job.sh", names)
                self.assertNotIn("pcdf-ntuple/code/submit-pcdf-ntuple.slurm", names)

    def test_htcondor_requirements_are_optional(self) -> None:
        submit_text = build_condor(WizardState(scheduler="condor"), Path("."))
        self.assertNotIn("requirements =", submit_text)

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
