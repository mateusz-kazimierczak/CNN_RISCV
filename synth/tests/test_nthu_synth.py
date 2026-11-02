"""Offline tests: real POSIX worker with fake DC; no network/licenses needed."""
import argparse
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("nthu_synth", ROOT / "tools/nthu_synth.py")
nthu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nthu)
JOB = "20261018T010203Z-123456abcdef"


def fixture(directory, error=False):
    for name in ("reports", "outputs", "logs", "status", "scripts"):
        (directory / name).mkdir(parents=True, exist_ok=True)
    for name in ("reference", "check_design", "check_timing", "qor", "library"):
        (directory / f"reports/{name}.rpt").write_text("mock DC report\n")
    (directory / "reports/area.rpt").write_text("Total cell area: 12.50\n")
    (directory / "reports/timing.rpt").write_text("slack (MET) 7.50\n")
    (directory / "reports/metrics.tsv").write_text(
        "area\t12.5\ncell_count\t3\narrival_ns\t2.4\nrequired_ns\t9.9\nslack_ns\t7.5\nblackbox_count\t0\n")
    (directory / "reports/cells.tsv").write_text("DFF\nDFF\nADD\n")
    for name in ("flow_complete", "mapped.v", "mapped.sdc"):
        (directory / "outputs" / name).write_text("fixture\n")
    (directory / "logs/dc.log").write_text("Error: mock failure\n" if error else "Warning: mock warning\n")
    (directory / "logs/version.log").write_text("DC Version R-2020.09-SP5\n")
    (directory / "scripts/environment.csh").write_text("# mocked environment\n")
    (directory / "scripts/home_guard.sh").write_bytes((ROOT / "synth/scripts/home_guard.sh").read_bytes())
    (directory / "scripts/limits.sh").write_text("# Linux limits mocked locally\nulimit -c 0\n")
    (directory / "status/state").write_text("SUCCEEDED\n")
    (directory / "status/exit_code").write_text("0\n")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.site = nthu.load_site(nthu.SITE_EXAMPLE)
        self.config = nthu.read_config(ROOT / "synth/configs/smoke.json")

    def test_command_construction_all_hops_batch_and_verified(self):
        argv = nthu.SSH(self.site).argv("hostname; echo $HOME")
        self.assertEqual(argv[-2], "u115123101@ws25")
        proxy = next(v for v in argv if v.startswith("ProxyCommand="))
        self.assertIn("BatchMode=yes", proxy)
        self.assertIn("StrictHostKeyChecking=yes", proxy)
        self.assertIn("11922", proxy)
        self.assertNotIn("StrictHostKeyChecking=no", " ".join(argv))
        self.site["transport"] = "nested"
        nested = nthu.SSH(self.site).argv("hostname")
        self.assertEqual(nested[-2], "u115123101@daisy.ee.nthu.edu.tw")
        self.assertIn("u115123101@ws25", nested[-1])
        self.assertNotIn("ProxyCommand", nested[-1])

    def test_path_quoting_survives_tcsh_login_shell(self):
        if not shutil.which("tcsh"):
            self.skipTest("tcsh unavailable locally")
        value = "spaces ' quotes $HOME ; [x] `echo bad`"
        command = nthu.SSH(self.site).argv("printf '%s' " + nthu.Q(value))[-1]
        actual = subprocess.check_output(["tcsh", "-f", "-c", command], text=True)
        self.assertEqual(actual, value)

    def test_multiline_command_survives_tcsh_and_preserves_upload_stdin(self):
        if not shutil.which("tcsh"):
            self.skipTest("tcsh unavailable locally")
        script = "set -eu\nprintf 'HEADER\\n'\nfor value in one two; do\n  printf '%s\\n' \"$value\"\ndone\ncat\n"
        command = nthu.SSH(self.site).argv(script)[-1]
        payload = b"upload\x00bytes\n"
        result = subprocess.run(["tcsh", "-f", "-c", command], input=payload, capture_output=True, check=True)
        self.assertEqual(result.stdout, b"HEADER\none\ntwo\n" + payload)

    def test_validation_and_policy_gates(self):
        with self.assertRaisesRegex(ValueError, "library use"):
            nthu.policy(self.site)
        for value in ("../escape", "/absolute", ".git/config", "bad\nname", "back\\slash"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                nthu.relative(value)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            nthu.load_site(Path("/does/not/exist.json"))
        for name in ("b0", "x1"):
            with self.assertRaises(ValueError):
                nthu.read_config(ROOT / f"synth/configs/cv_wally_{name}.example.json")

    def test_doctor_explains_legacy_host_key_without_enabling_it(self):
        response = subprocess.CompletedProcess([], 255, b"", b"no matching host key type found. Their offer: ssh-rsa,ssh-dss")
        output = io.StringIO()
        with patch.object(nthu.SSH, "call", return_value=response), redirect_stdout(output):
            self.assertEqual(nthu.doctor(self.site), 1)
        self.assertIn("explicit host-scoped RSA", output.getvalue())
        self.assertNotIn("HostKeyAlgorithms", " ".join(nthu.SSH(self.site).argv("hostname")))

    def test_manifest_exact_minimal_files_and_stable_hashes(self):
        files = nthu.package(self.config, self.site)
        self.assertEqual([p for p in files if p.startswith("inputs/")],
                         ["inputs/synth/smoke/registered_adder.sv"])
        self.assertEqual(files, nthu.package(self.config, self.site))
        self.assertNotIn(".db", " ".join(files))
        self.assertIn("2020.09-sp5", files["scripts/environment.csh"].decode())
        with tempfile.TemporaryDirectory() as temporary:
            nthu.safe_extract(nthu.archive(files), Path(temporary))
            for name, data in files.items():
                self.assertEqual((Path(temporary) / name).read_bytes(), data)

    def test_rejects_proprietary_or_escaping_source(self):
        config = copy.deepcopy(self.config)
        config["sources"] = ["technology.db"]
        with self.assertRaisesRegex(ValueError, "never package"):
            nthu.package(config, self.site)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "escape.sv").symlink_to("/etc/passwd")
            config["sources"] = ["escape.sv"]
            with self.assertRaisesRegex(ValueError, "escapes"):
                nthu.package(config, self.site, root=root)

    def test_order_and_includes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rtl").mkdir()
            for name in ("package.sv", "top.sv", "defs.svh", "do_not_upload.db"):
                (root / "rtl" / name).write_text("fixture")
            config = copy.deepcopy(self.config)
            config.update(sources=["rtl/package.sv", "rtl/top.sv"], headers=["rtl/defs.svh"], include_dirs=["rtl"])
            files = nthu.package(config, self.site, root=root)
            self.assertNotIn("inputs/rtl/do_not_upload.db", files)
            script = files["scripts/config.tcl"].decode()
            self.assertLess(script.index("inputs/rtl/package.sv"), script.index("inputs/rtl/top.sv"))
            self.assertIn('"inputs/rtl"', script)

    def test_tcl_data_cannot_execute(self):
        if not shutil.which("tclsh"):
            self.skipTest("tclsh unavailable")
        value = 'x"; puts INJECTED; # [puts INJECTED] $env(HOME) \\ \n'
        script = f"set value {nthu.tcl(value)}\nputs -nonewline $value\n"
        result = subprocess.run(["tclsh"], input=script, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, value)

    def test_dry_run_never_ssh_or_write(self):
        output = io.StringIO()
        # git provenance is allowed; any SSH command would fail this assertion.
        original = nthu.run
        def local_only(argv, **kwargs):
            self.assertNotEqual(argv[0], "ssh")
            return original(argv, **kwargs)
        args = argparse.Namespace(config=ROOT / "synth/configs/smoke.json", dry_run=True)
        with patch.object(nthu, "run", local_only), patch.object(Path, "mkdir", side_effect=AssertionError("write")), redirect_stdout(output):
            nthu.submit(args, self.site)
        report = json.loads(output.getvalue())
        self.assertTrue(report["dry_run"])
        self.assertIn("manifest.json", report["additional_upload"])
        self.assertIn("tar xzf -", report["tar_stage_script"])

    def test_root_cannot_follow_symlink_outside_home(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            home = Path(temporary)
            (home / "synthesis_jobs").symlink_to(outside)
            result = subprocess.run(["sh", "-c", "set -eu; " + nthu.root_guard(self.site)],
                                    env={**os.environ, "HOME": str(home)}, capture_output=True)
            self.assertEqual(result.returncode, 64)

    def test_job_guard_rejects_outside_home_and_symlinked_output(self):
        guard = ROOT / "synth/scripts/home_guard.sh"
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            home, external = Path(temporary), Path(outside)
            marker = external / "untouched"
            marker.write_text("preserve")
            command = ". " + nthu.Q(str(guard)) + "; echo bad > should_not_exist"
            result = subprocess.run(["sh", "-c", command], cwd=external,
                                    env={**os.environ, "HOME": str(home)}, capture_output=True)
            self.assertEqual(result.returncode, 64)
            job = home / JOB
            job.mkdir()
            (job / "outputs").symlink_to(external)
            result = subprocess.run(["sh", "-c", command], cwd=job,
                                    env={**os.environ, "HOME": str(home)}, capture_output=True)
            self.assertEqual(result.returncode, 64)
            self.assertEqual(list(external.iterdir()), [marker])
            self.assertEqual(marker.read_text(), "preserve")

    def test_archive_rejects_links_and_traversal(self):
        for name, kind in (("../bad", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w:gz") as tar:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "/etc/passwd"
                tar.addfile(member)
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                nthu.safe_extract(stream.getvalue(), Path(temporary))


class LifecycleTests(unittest.TestCase):
    def worker(self, directory, *, behavior="success", lock=False):
        job = directory / JOB
        fixture(job)
        for name in ("state", "exit_code"):
            (job / "status" / name).unlink()
        (job / "status/state").write_text("STAGED\n")
        fake = directory / "fake-tcsh"
        if behavior == "nonzero":
            body = "echo 'License checkout failed'; exit 1\n"
        elif behavior == "error":
            body = "echo 'Error: DC returned zero anyway'\n"
        elif behavior == "missing":
            body = "rm outputs/mapped.v; echo mocked\n"
        else:
            body = "echo mocked\n"
        fake.write_text("#!/bin/sh\n" + body)
        fake.chmod(0o700)
        worker = (ROOT / "synth/scripts/worker.sh").read_text().replace("/usr/bin/tcsh", nthu.Q(str(fake)))
        # GNU timeout and the Linux virtual-memory ulimit are validated on the
        # actual target separately; local mock DC does not require a watchdog.
        worker = worker.replace("timeout -s KILL 6h ", "")
        # The target has Linux /proc; mock only that dependency on macOS.
        worker = worker.replace('awk \'{print $22}\' "/proc/$$/stat"', "echo 12345")
        (job / "scripts/worker.sh").write_text(worker)
        (job / "scripts/hashes.sha256").write_text("")
        # Populate the input-hash manifest with real data.
        (job / "scripts/hashes.sha256").write_text(f"{nthu.sha(worker.encode())}  scripts/worker.sh\n")
        if lock:
            (directory / ".active").mkdir()
            (directory / ".active/owner").write_text("another job")
        result = subprocess.run(["sh", str(job / "scripts/worker.sh")], capture_output=True,
                                env={**os.environ, "HOME": str(directory)})
        return job, result

    def test_worker_success_and_lock_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            job, result = self.worker(Path(temporary))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((job / "status/state").read_text().strip(), "SUCCEEDED")
            self.assertEqual((job / "status/exit_code").read_text().strip(), "0")
            self.assertTrue((job / "status/ended_at").is_file())
            self.assertFalse((job.parent / ".active").exists())
            self.assertEqual((job / "tmp").stat().st_mode & 0o777, 0o700)
            paths = (job / "status/storage_paths").read_text()
            self.assertIn(f"tmp={job.resolve()}/tmp", paths)
            self.assertIn(f"cache={job.resolve()}/cache", paths)

    def test_worker_rejects_exit_zero_errors_missing_artifacts_and_license_failure(self):
        for behavior in ("error", "missing", "nonzero"):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as temporary:
                job, result = self.worker(Path(temporary), behavior=behavior)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((job / "status/state").read_text().strip(), "FAILED")
                self.assertFalse((job.parent / ".active").exists())

    def test_worker_never_disturbs_another_job_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            job, result = self.worker(Path(temporary), lock=True)
            self.assertEqual(result.returncode, 75)
            self.assertEqual((job / "status/state").read_text().strip(), "FAILED")
            self.assertEqual((job.parent / ".active/owner").read_text(), "another job")

    def test_launch_is_detached_and_not_repeatable(self):
        site = nthu.load_site(nthu.SITE_EXAMPLE)
        site["execution"] = "nohup"
        script = nthu.launch_script(nthu.SSH(site), JOB)
        self.assertIn("mkdir status/.launch-claimed", script)
        self.assertIn("</dev/null >logs/launcher.log 2>&1 &", script)
        for mode, command in (("sge", "qsub"), ("slurm", "sbatch")):
            site["execution"] = mode
            self.assertIn(command, nthu.launch_script(nthu.SSH(site), JOB))

    def test_stale_running_is_reported_as_interrupted(self):
        class FakeSSH:
            def job_path(self, job):
                return "/missing"
            def call(self, script):
                self.script = script
                return subprocess.CompletedProcess([], 0, b"state=RUNNING\nOBSERVED=INTERRUPTED\n")
        ssh = FakeSSH()
        result = nthu.status(ssh, JOB)
        self.assertEqual(result["liveness"], "INTERRUPTED")
        self.assertIn("process_start", ssh.script)
        self.assertIn('/proc/$pid/cwd', ssh.script)

    def test_failure_classification(self):
        self.assertEqual(nthu.failure_reason("License checkout failed"), "license/entitlement")
        self.assertEqual(nthu.failure_reason("Fatal: Design Compiler is not enabled. (DCSH-1)"), "license/entitlement")
        self.assertEqual(nthu.failure_reason("link failed: unresolved reference"), "RTL/dependency/link")

    def test_tar_submit_launch_status_fetch_end_to_end_with_fake_dc(self):
        # Execute the actual staging/launch/worker scripts against a temporary HOME.
        # Only SSH transport, DC, and Linux /proc are replaced.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, results, reference = root / "home", root / "local", root / "reference"
            home.mkdir()
            fixture(reference)
            fake = root / "dc-mock"
            fake.write_text("#!/bin/sh\ncp -R " + nthu.Q(str(reference / "reports")) + " .\n"
                            + "cp -R " + nthu.Q(str(reference / "outputs")) + " .\n"
                            + "cp " + nthu.Q(str(reference / "logs/version.log")) + " logs/version.log\n"
                            + "echo 'Mocked DC, not a real synthesis'\n")
            fake.chmod(0o700)
            real_package = nthu.package
            def patched_package(*args, **kwargs):
                files = real_package(*args, **kwargs)
                files["scripts/worker.sh"] = files["scripts/worker.sh"].replace(
                    b"/usr/bin/tcsh", nthu.Q(str(fake)).encode()).replace(
                    b'awk \'{print $22}\' "/proc/$$/stat"', b"echo 12345")
                files["scripts/worker.sh"] = files["scripts/worker.sh"].replace(b"timeout -s KILL 6h ", b"")
                files["scripts/limits.sh"] = b"# Linux limits mocked locally\nulimit -c 0\n"
                return files
            class LocalSSH(nthu.SSH):
                def call(self, script, **kwargs):
                    result = subprocess.run(["sh", "-c", script], input=kwargs.get("data"),
                                            env={**os.environ, "HOME": str(home)}, capture_output=True,
                                            timeout=kwargs.get("timeout", 30))
                    if kwargs.get("check", True) and result.returncode:
                        raise ValueError(result.stderr.decode())
                    return result
            site = nthu.load_site(nthu.SITE_EXAMPLE)
            site.update(execution="nohup", transfer="tar", library_use_confirmed=True,
                        execution_policy_confirmed=True)
            args = argparse.Namespace(config=ROOT / "synth/configs/smoke.json", dry_run=False)
            with patch.object(nthu, "RESULTS", results), patch.object(nthu, "package", patched_package), \
                    patch.object(nthu, "SSH", LocalSSH), redirect_stdout(io.StringIO()):
                nthu.submit(args, site)
                job = next(results.iterdir()).name
                ssh = LocalSSH(site)
                deadline = time.monotonic() + 5
                while (home / site["remote_root"] / job / "status/state").read_text().strip() == "RUNNING" and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(nthu.status(ssh, job)["state"], "SUCCEEDED")
                nthu.fetch(ssh, job)
                summary = json.loads((results / job / "summary.json").read_text())
                self.assertEqual(summary["area"], 12.5)
                remote = home / site["remote_root"] / job
                self.assertTrue((remote / "logs/input_hashes.log").is_file())
                self.assertFalse(remote.with_name(job + ".upload").exists())
                self.assertEqual(nthu.compare(job, job)["area_delta"], 0)
                with self.assertRaises(ValueError):
                    ssh.call(nthu.launch_script(ssh, job))


class ReportTests(unittest.TestCase):
    def test_parse_mapped_area_timing_cells_and_warnings(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            fixture(directory)
            result = nthu.parse_reports(directory)
            self.assertEqual(result["area"], 12.5)
            self.assertEqual(result["cell_breakdown"], {"DFF": 2, "ADD": 1})
            self.assertEqual(result["wns_ns"], 0)
            self.assertIsNone(result["fmax_mhz"])
            self.assertEqual(len(result["warnings"]), 1)

    def test_invalid_reports_are_not_measurements(self):
        for file, text in (("area.rpt", "missing"), ("timing.rpt", "unconstrained"),
                           ("metrics.tsv", "area\tnan\n"), ("cells.tsv", "wrong count")):
            with self.subTest(file=file), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                fixture(directory)
                (directory / "reports" / file).write_text(text)
                with self.assertRaises(ValueError):
                    nthu.parse_reports(directory)

    def test_compare_guards_and_deltas(self):
        site = nthu.load_site(nthu.SITE_EXAMPLE)
        config = nthu.read_config(ROOT / "synth/configs/smoke.json")
        setup = nthu.comparison_setup(config, site, nthu.package(config, site))
        variant = "20261018T010204Z-abcdef123456"
        with tempfile.TemporaryDirectory() as temporary, patch.object(nthu, "RESULTS", Path(temporary)):
            for job in (JOB, variant):
                directory = Path(temporary) / job
                fixture(directory)
                (directory / "manifest.json").write_text(nthu.dump({"setup": setup}))
                (directory / "summary.json").write_text(nthu.dump({"state": "SUCCEEDED"}))
            self.assertEqual(nthu.compare(JOB, variant)["area_delta"], 0)
            for key in ("library", "corner", "clock", "top", "scope", "compile_mode", "constraints", "allowed_blackboxes", "flow_sha256"):
                other = {**setup, key: "different"}
                (Path(temporary) / variant / "manifest.json").write_text(nthu.dump({"setup": other}))
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                    nthu.compare(JOB, variant)

    def test_fetch_snapshot_and_remote_manifest_integrity(self):
        site = nthu.load_site(nthu.SITE_EXAMPLE)
        config = nthu.read_config(ROOT / "synth/configs/smoke.json")
        manifest = {"job_id": JOB, "config": config, "site": site}
        with tempfile.TemporaryDirectory() as temporary, patch.object(nthu, "RESULTS", Path(temporary)):
            directory = Path(temporary) / JOB
            fixture(directory)
            (directory / "manifest.json").write_text(nthu.dump(manifest))
            files = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
            class FakeSSH:
                def job_path(self, job):
                    return "/fake"
                def call(self, script, **kwargs):
                    return subprocess.CompletedProcess([], 0, nthu.archive(files))
            with redirect_stdout(io.StringIO()):
                nthu.fetch(FakeSSH(), JOB)
            self.assertEqual(json.loads((directory / "summary.json").read_text())["area"], 12.5)
            files["manifest.json"] = b"{}"
            with self.assertRaisesRegex(ValueError, "manifest differs"):
                nthu.fetch(FakeSSH(), JOB)


if __name__ == "__main__":
    unittest.main()
