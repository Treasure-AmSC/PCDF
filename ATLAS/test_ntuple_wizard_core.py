"""Tests for generated local input-manifest tooling."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from ntuple_wizard_core import (
    BUNDLE_ROOT_NAME,
    WizardState,
    build_condor,
    build_python,
    write_bundle,
)


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
                readme = archive.extractfile("pcdf-ntuple/README_SUBMIT.md")
                self.assertIsNotNone(readme)
                self.assertIn(b"downloaded through a NERSC DTN", readme.read())
                launcher = archive.extractfile("pcdf-ntuple/code/run-pcdf.py")
                self.assertIsNotNone(launcher)
                launcher_text = launcher.read()
                self.assertIn(b'manifest_scheduler = "condor"', launcher_text)
                self.assertIn(b'"--scheduler", manifest_scheduler', launcher_text)

    def test_bundle_archive_does_not_include_existing_runtime_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            runtime_output = output_dir / BUNDLE_ROOT_NAME / "output"
            runtime_output.mkdir(parents=True)
            (runtime_output / "previous.parquet").write_bytes(b"old result")

            _, _, bundle = write_bundle(WizardState(), output_dir)

            with tarfile.open(bundle) as archive:
                self.assertNotIn("pcdf-ntuple/output/previous.parquet", archive.getnames())

    def test_bundle_ships_the_configured_output_directory(self) -> None:
        cases = {
            "./results/run1": ("pcdf-ntuple/results/run1/", True),
            "../elsewhere": (None, False),
            "/scratch/out": (None, False),
        }
        for output_base, (expected, _) in cases.items():
            with self.subTest(output_base=output_base), tempfile.TemporaryDirectory() as temporary:
                _, _, bundle = write_bundle(WizardState(output_base=output_base), Path(temporary))
                with tarfile.open(bundle) as archive:
                    names = archive.getnames()
                    self.assertNotIn("pcdf-ntuple/output/", names)
                    if expected:
                        self.assertIn(expected.rstrip("/"), names)
                    readme = archive.extractfile("pcdf-ntuple/README_SUBMIT.md").read().decode()
                self.assertIn(f"- {expected.removeprefix('pcdf-ntuple/') if expected else output_base}", readme)

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
                readme = archive.extractfile("pcdf-ntuple/README_SUBMIT.md")
                self.assertIsNotNone(readme)
                self.assertNotIn(b"downloaded through a NERSC DTN", readme.read())

    def test_htcondor_bundle_runs_conversions_locally(self) -> None:
        state = WizardState(scheduler="condor", manifest="./inputs.txt", condor_cpus=1)
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            write_bundle(state, temporary_path)
            bundle = temporary_path / BUNDLE_ROOT_NAME
            inputs = temporary_path / "download"
            inputs.mkdir()
            for number in (1, 2):
                (inputs / f"DAOD_JETM16.1._00000{number}.pool.root.1").write_bytes(b"x" * 1025)

            # A stand-in uv writes the manifest in place of the interactive
            # helper, which has its own tests, and records every other command
            # instead of converting anything.
            listing = "".join(f"{path}\\n" for path in sorted(inputs.iterdir()))
            fake_bin = temporary_path / "bin"
            fake_bin.mkdir()
            uv_log = temporary_path / "uv.log"
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/bin/bash\n"
                'if [[ "$2" == *make-manifest.py ]]; then '
                f"printf '{listing}' > inputs.txt; exit 0; fi\n"
                f'echo "$*" >> {uv_log}\n'
            )
            fake_uv.chmod(0o755)
            environment = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}

            result = subprocess.run(
                [sys.executable, "-B", str(bundle / "code" / "run-pcdf.py"), "--local"],
                check=False,
                text=True,
                capture_output=True,
                cwd=bundle,
                env=environment,
                input="y\n2\n",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = uv_log.read_text().splitlines()
            self.assertIn("run ./code/ntuple-maker-jetm16.py --help", calls)
            conversions = sorted(call for call in calls if not call.endswith("--help"))
            self.assertEqual(
                conversions,
                [
                    f"run ./code/ntuple-maker-jetm16.py {inputs}/DAOD_JETM16.1._00000{number}.pool.root.1 -o output"
                    for number in (1, 2)
                ],
            )
            self.assertEqual(len(list((bundle / "logs").glob("pcdf-ntuple-local-*.out"))), 2)

    def test_htcondor_requirements_are_optional(self) -> None:
        submit_text = build_condor(WizardState(scheduler="condor"), Path("."))
        self.assertNotIn("requirements =", submit_text)

    def test_htcondor_default_memory_is_two_gibibytes_per_file(self) -> None:
        submit_text = build_condor(WizardState(scheduler="condor"), Path("."))
        self.assertIn("request_memory = 2048 MB", submit_text)

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

    def test_slurm_mode_can_download_a_dataset_through_a_dtn(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            home = workspace / "home"
            scratch = workspace / "scratch"
            atlas_root = workspace / "atlas"
            binary_directory = workspace / "bin"
            for directory in (home, scratch, binary_directory):
                directory.mkdir()

            initializer = atlas_root / "wrappers" / "gridMW" / "voms-proxy-init"
            proxy_info = atlas_root / "wrappers" / "gridMW" / "voms-proxy-info"
            initializer_log = workspace / "proxy-initializer-arguments.txt"
            initializer.parent.mkdir(parents=True)
            initializer.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$@\" > {initializer_log}\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = -out ]; then shift; proxy=$1; fi\n"
                "  shift\n"
                "done\n"
                ": > \"$proxy\"\n"
            )
            proxy_info.write_text(
                "#!/bin/sh\n"
                "case \" $* \" in\n"
                "  *\" -vo \"*) echo atlas;;\n"
                "  *\" -timeleft \"*) echo 86400;;\n"
                "esac\n"
            )
            initializer.chmod(0o755)
            proxy_info.chmod(0o755)

            ssh_log = workspace / "ssh-arguments.txt"
            downloaded = scratch / "pcdf-rucio" / "user.alice.dataset" / "DAOD_JETM16.test.pool.root"
            ssh = binary_directory / "ssh"
            ssh.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$@\" > {ssh_log}\n"
                f"mkdir -p {downloaded.parent}\n"
                f"dd if=/dev/zero of={downloaded} bs=1025 count=1 status=none\n"
            )
            ssh.chmod(0o755)

            manifest = workspace / "inputs.txt"
            environment = {
                "ATLAS_LOCAL_ROOT_BASE": str(atlas_root),
                "HOME": str(home),
                "PATH": f"{binary_directory}:{os.environ['PATH']}",
                "PYTHONDONTWRITEBYTECODE": "1",
                "SCRATCH": str(scratch),
            }
            result = subprocess.run(
                [sys.executable, "-B", str(helper), "--scheduler", "slurm"],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                input=(
                    "3\n"
                    "user.alice:user.alice.dataset\n"
                    "alice\n"
                    "\n"
                    "\n"
                    "\n"
                    "y\n"
                    f"{manifest}\n"
                ),
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(manifest.read_text(), f"{downloaded}\n")
            proxy = home / ".cache" / "pcdf" / "credentials" / f"x509up_u{os.getuid()}"
            self.assertTrue(proxy.is_file())
            self.assertEqual(proxy.stat().st_mode & 0o777, 0o600)
            initializer_arguments = initializer_log.read_text()
            self.assertIn("-voms\natlas\n-valid\n12:00\n-out\n", initializer_arguments)
            self.assertIn(str(proxy), initializer_arguments)
            ssh_arguments = ssh_log.read_text()
            self.assertIn("dtn01.nersc.gov", ssh_arguments)
            self.assertIn("user.alice:user.alice.dataset", ssh_arguments)
            self.assertIn("alice", ssh_arguments)
            self.assertIn(str(proxy), ssh_arguments)

    def test_condor_mode_does_not_offer_dtn_download(self) -> None:
        helper = Path(__file__).parent / "templates" / "make-manifest.template.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "download"
            root.mkdir()
            input_file = root / "DAOD_JETM16.1.pool.root"
            input_file.write_bytes(b"x" * 1025)
            manifest = Path(temporary) / "inputs.txt"

            result = subprocess.run(
                [sys.executable, "-B", str(helper), "--scheduler", "condor"],
                check=False,
                text=True,
                capture_output=True,
                input=f"1\n{root}\n{manifest}\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("NERSC DTN", result.stdout)


if __name__ == "__main__":
    unittest.main()
