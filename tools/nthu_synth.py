#!/usr/bin/env python3
"""Reproducible NTHU Design Compiler jobs. Local Python 3 stdlib; remote sh/tcsh."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "synth/results"
SITE_EXAMPLE = ROOT / "synth/configs/nthu.example.json"
JOB_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
REMOTE = ("synth/scripts/worker.sh", "synth/tcl/run_dc.tcl")
RESOURCE_LIMITS = {"dc_max_cores": 1, "nice": 10, "wall_seconds": 21600,
                   "cpu_seconds_per_process": 14400, "virtual_memory_kib_per_process": 16777216,
                   "file_blocks_per_process": 2097152, "core_dump_bytes": 0}
Q = shlex.quote


def dump(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(argv, *, data=None, timeout=30, check=True):
    result = subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise ValueError(f"command failed ({result.returncode}): {shlex.join(map(str, argv))}\n"
                         + result.stderr.decode(errors="replace"))
    return result


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("paths must be nonempty strings without control characters")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("..", ".git") for p in path.parts) or value.startswith("-"):
        raise ValueError(f"path must stay below its root: {value}")
    return path.as_posix()


def load_site(path=None):
    if path is not None and not path.is_file():
        raise ValueError(f"site config does not exist: {path}")
    path = path or ROOT / "synth/configs/nthu.local.json"
    site = json.loads((path if path.exists() else SITE_EXAMPLE).read_text())
    expected = json.loads(SITE_EXAMPLE.read_text())
    if set(site) != set(expected):
        raise ValueError(f"site keys must match example (no credentials): {sorted(expected)}")
    for key in ("user", "host", "jump_host", "tool_version"):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", site[key]):
            raise ValueError(f"invalid {key}")
    for key in ("port", "jump_port"):
        if type(site[key]) is not int or not 1 <= site[key] <= 65535:
            raise ValueError(f"invalid {key}")
    site["remote_root"] = relative(site["remote_root"])
    for key in ("library", "setup"):
        value = site[key]
        if not value.startswith("/") or not re.fullmatch(r"[/A-Za-z0-9_.+ -]+", value) or ".." in Path(value).parts:
            raise ValueError(f"invalid remote absolute {key} path")
    for key, choices in {"transport": ("jump", "nested"),
                         "execution": ("unconfigured", "nohup", "sge", "slurm"),
                         "compile_mode": ("compile", "compile_ultra"),
                         "transfer": ("auto", "tar", "rsync")}.items():
        if site[key] not in choices:
            raise ValueError(f"{key} must be one of {choices}")
    for key in ("cell_family", "corner"):
        if not isinstance(site[key], str) or not re.fullmatch(r"[A-Za-z0-9_.+ -]+", site[key]):
            raise ValueError(f"invalid {key}")
    if site["tool_version"] != "2020.09-sp5":
        raise ValueError("only pinned site release 2020.09-sp5 is enabled; qualify a new release before changing this guard")
    for key in ("library_use_confirmed", "execution_policy_confirmed"):
        if type(site[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    return site


class SSH:
    def __init__(self, site):
        self.site = site

    def base(self, *, jump=False):
        s = self.site
        # ProxyJump does not propagate BatchMode to its child ssh. Set it explicitly.
        base = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1"]
        if jump:
            return base + ["-p", str(s["jump_port"]), f'{s["user"]}@{s["jump_host"]}']
        if s["transport"] == "jump":
            proxy = shlex.join(self.base(jump=True)[:-1] +
                               ["-W", "%h:%p", f'{s["user"]}@{s["jump_host"]}'])
            base += ["-o", f"ProxyCommand={proxy}"]
        return base + ["-p", str(s["port"]), f'{s["user"]}@{s["host"]}']

    def argv(self, script):
        # The login shell is tcsh: literal newlines inside shlex-quoted commands
        # are not portable through its -c parser. Decode with POSIX printf in sh,
        # retaining SSH stdin for tar uploads. No remote Python or temp file.
        encoded = "".join(f"\\0{byte:03o}" for byte in script.encode())
        remote = "/bin/sh -c " + Q(f'exec /bin/sh -c "$(printf %b "{encoded}")"')
        if self.site["transport"] == "nested":
            # Second ssh runs on Daisy; no home sharing or laptop ws25 DNS needed.
            remote = shlex.join(self.base() + [remote])
            return self.base(jump=True) + [remote]
        return self.base() + [remote]

    def call(self, script, **kwargs):
        return run(self.argv(script), **kwargs)

    def job_path(self, job):
        validate_job(job)
        return '"$HOME"/' + Q(self.site["remote_root"] + "/" + job)


def validate_job(job):
    if not JOB_RE.fullmatch(job):
        raise ValueError("invalid job ID (use the ID printed by submit)")


def tcl(value):
    """A Tcl literal word; brackets, substitutions, semicolons stay data."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace(
        "$", "\\$").replace("[", "\\[").replace("]", "\\]").replace("\n", "\\n").replace("\r", "\\r") + '"'


def tcl_list(values):
    return "[list " + " ".join(tcl(v) for v in values) + "]"


def config_tcl(config, site):
    clock = config["clock"]
    values = {"library": site["library"], "top": config["top"],
              "compile_mode": site["compile_mode"], "clock_port": clock["port"],
              "clock_period": clock["period_ns"], "clock_uncertainty": clock["uncertainty_ns"],
              "reset_port": config.get("reset") or "", "input_delay": config["input_delay_ns"],
              "output_delay": config["output_delay_ns"]}
    lines = [f"set {key} {tcl(value)}" for key, value in values.items()]
    lists = {key: ["inputs/" + p for p in config[key]]
             for key in ("sources", "include_dirs", "constraints")}
    lists.update(defines=config["defines"], allowed_blackboxes=config["allowed_blackboxes"],
                 parameters=[f"{k}={v}" for k, v in sorted(config["parameters"].items())])
    lines += [f"set {key} {tcl_list(value)}" for key, value in lists.items()]
    return ("\n".join(lines) + "\n").encode()


def environment(site):
    # Restrict setup/version path characters in load_site; no user Tcl in this file.
    return ("set synth_job = \"$cwd\"\n"
            f"source {Q(site['setup'])} {Q(site['tool_version'])}\n"
            "if ( $status != 0 ) exit 70\n"
            "if ( \"$cwd\" != \"$synth_job\" ) exit 64\nrehash\nwhich dc_shell\n"
            # Reassert job-local paths after sourcing the site environment.
            "setenv TMPDIR \"$cwd/tmp\"\nsetenv TMP \"$cwd/tmp\"\nsetenv TEMP \"$cwd/tmp\"\n"
            "setenv XDG_CACHE_HOME \"$cwd/cache\"\nsetenv LC_ALL C\nsetenv LANG C\n"
            "setenv OMP_NUM_THREADS 1\n"
            "dc_shell -version > logs/version.log\n"
            # Observed R-2020.09-SP5 returns 1 for -version even on success.
            # Require the actual version banner rather than its help-mode exit.
            "grep -i -E '2020[.]09.*SP5' logs/version.log\n"
            "if ( $status != 0 ) exit 70\n"
            "dc_shell -no_home_init -f scripts/run_dc.tcl\nexit $status\n").encode()


def read_config(path):
    config = json.loads(path.read_text())
    if config.get("blocked_reason"):
        raise ValueError(config["blocked_reason"])
    for key in ("top",):
        if not isinstance(config.get(key), str) or not IDENT.fullmatch(config[key]):
            raise ValueError(f"{key} must name a real module")
    if config.get("kind") not in ("smoke", "core") or not config.get("scope"):
        raise ValueError("kind and hardware scope are required")
    for key in ("sources", "headers", "include_dirs", "constraints", "defines", "allowed_blackboxes"):
        if not isinstance(config.get(key), list) or any(not isinstance(v, str) for v in config[key]):
            raise ValueError(f"{key} must be a list of strings")
    if not config["sources"]:
        raise ValueError("ordered sources must be nonempty")
    if config["kind"] == "smoke" and (config["top"] != "registered_adder" or config["sources"] != ["synth/smoke/registered_adder.sv"]):
        raise ValueError("smoke kind is reserved for the supplied registered adder; other designs use kind=core")
    if len(set(config["sources"])) != len(config["sources"]):
        raise ValueError("duplicate source")
    for key in ("sources", "headers", "include_dirs", "constraints"):
        config[key] = [relative(p) for p in config[key]]
    if not isinstance(config.get("parameters"), dict):
        raise ValueError("parameters must be a mapping")
    for key, value in config["parameters"].items():
        if not IDENT.fullmatch(key) or not isinstance(value, (str, int, float)):
            raise ValueError("invalid parameter")
    clock = config.get("clock")
    if not isinstance(clock, dict) or not IDENT.fullmatch(clock.get("port", "")):
        raise ValueError("one sequential clock port is required")
    for key, value in [("period_ns", clock.get("period_ns")),
                       ("uncertainty_ns", clock.get("uncertainty_ns")),
                       ("input_delay_ns", config.get("input_delay_ns")),
                       ("output_delay_ns", config.get("output_delay_ns"))]:
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
    if clock["period_ns"] <= 0:
        raise ValueError("clock period must be positive")
    if config.get("reset") and not IDENT.fullmatch(config["reset"]):
        raise ValueError("reset must be a port name")
    return config


def package(config, site, *, root=ROOT):
    files = {}
    selected = config["sources"] + config["headers"] + config["constraints"]
    for directory in config["include_dirs"]:
        if not (root / directory).is_dir():
            raise ValueError(f"missing include directory: {directory}")
    for name in selected:
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"source link escapes repository: {name}")
        if path.suffix.lower() not in (".v", ".sv", ".vh", ".svh", ".h", ".sdc", ".tcl", ".json"):
            raise ValueError(f"unsupported synthesis input (never package .db/weights/binaries): {name}")
        if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError(f"missing/oversized input: {name}")
        files["inputs/" + name] = path.read_bytes()
    for directory in config["include_dirs"]:
        # Preserve include paths without copying arbitrary directory contents.
        if not any(p.startswith("inputs/" + directory + "/") for p in files):
            raise ValueError(f"include directory has no explicitly listed headers/sources: {directory}")
    files["scripts/run_dc.tcl"] = (ROOT / REMOTE[1]).read_bytes()
    files["scripts/worker.sh"] = (ROOT / REMOTE[0]).read_bytes()
    for name in ("home_guard.sh", "limits.sh"):
        files["scripts/" + name] = (ROOT / "synth/scripts" / name).read_bytes()
    files["scripts/config.tcl"] = config_tcl(config, site)
    files["scripts/environment.csh"] = environment(site)
    if sum(map(len, files.values())) > 256 * 1024 * 1024:
        raise ValueError("package exceeds 256 MiB; use a minimal explicit source list")
    return files


def git_info(directory=ROOT):
    head = run(["git", "-C", str(directory), "rev-parse", "HEAD"], check=False)
    if head.returncode:
        return {"commit": None, "dirty": None}
    dirty = run(["git", "-C", str(directory), "status", "--porcelain", "--untracked-files=normal"])
    return {"commit": head.stdout.decode().strip(), "dirty": bool(dirty.stdout)}


def comparison_setup(config, site, files):
    keys = ("library", "cell_family", "corner", "tool_version", "compile_mode")
    setup = {k: site[k] for k in keys}
    for k in ("scope", "top", "clock", "reset", "input_delay_ns", "output_delay_ns", "allowed_blackboxes"):
        setup[k] = config[k]
    setup["constraints"] = [{"path": p, "sha256": sha(files["inputs/" + p])} for p in config["constraints"]]
    setup["flow_sha256"] = sha(files["scripts/run_dc.tcl"])
    setup["setup_script"] = site["setup"]
    return setup


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o600, 0
            tar.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


def policy(site):
    if not site["library_use_confirmed"]:
        raise ValueError("library use unconfirmed: obtain course/site permission, then set library_use_confirmed")
    if not site["execution_policy_confirmed"] or site["execution"] == "unconfigured":
        raise ValueError("execution policy unconfirmed: discover scheduler with doctor, obtain site guidance, configure execution")


def launch_script(ssh, job):
    path = ssh.job_path(job)
    mode = ssh.site["execution"]
    preamble = f"set -eu; umask 077; cd {path}; . scripts/home_guard.sh; mkdir status/.launch-claimed; "
    # launch-claimed prevents duplicate execution after ambiguous network failures.
    if mode == "nohup":
        launch = "nohup /bin/sh scripts/worker.sh </dev/null >logs/launcher.log 2>&1 &\npid=$!\nprintf '%s\\n' \"$pid\" >status/launcher_pid\n"
    elif mode == "slurm":
        launch = "sbatch --parsable --chdir=\"$PWD\" --output=logs/launcher.log --wrap='/bin/sh scripts/worker.sh' >status/scheduler_id\n"
    elif mode == "sge":
        launch = "qsub -terse -cwd -j y -o logs/launcher.log -b y /bin/sh scripts/worker.sh >status/scheduler_id\n"
    else:
        raise ValueError("execution mode is unconfigured")
    return (preamble + "\n" + launch +
            "for i in 1 2 3 4 5; do\n"
            " state=$(cat status/state); case $state in RUNNING|SUCCEEDED|FAILED) cat status/state; exit 0;; esac\n"
            " sleep 1\ndone\n" +
            ("echo 'QUEUED (scheduler accepted; worker still STAGED)'\n" if mode != "nohup" else
             "echo 'Launch not verified; inspect status/logs before any retry' >&2; exit 76\n"))


def root_guard(site):
    # Check the nearest existing ancestor before creating anything, including symlinks.
    return (f'p="$HOME"/{Q(site["remote_root"])}; '
            'while test ! -e "$p"; do p=$(dirname "$p"); done; '
            'home=$(cd "$HOME" && pwd -P); parent=$(cd "$p" && pwd -P); '
            'case "$parent" in "$home"|"$home"/*) :;; '
            '*) echo "remote_root escapes home" >&2; exit 64;; esac; ')


def submit(args, site):
    config = read_config(args.config)
    files = package(config, site)
    job = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    ssh = SSH(site)
    setup = comparison_setup(config, site, files)
    repositories = {}
    for source in config["sources"] + config["headers"]:
        directory = (ROOT / source).resolve().parent
        probe = run(["git", "-C", str(directory), "rev-parse", "--show-toplevel"], check=False)
        if probe.returncode == 0:
            checkout = Path(probe.stdout.decode().strip())
            label = str(checkout.relative_to(ROOT)) if checkout.is_relative_to(ROOT) else str(checkout)
            if label not in repositories:
                repositories[label] = git_info(checkout)
    if config.get("expected_wally_revision"):
        revision = git_info(ROOT / ".deps/cvw")["commit"]
        if revision != config["expected_wally_revision"]:
            raise ValueError("CV-Wally checkout does not match expected_wally_revision")
    manifest = {"schema": 1, "job_id": job, "config": config, "setup": setup,
                "git": git_info(), "source_repositories": repositories, "resource_limits": RESOURCE_LIMITS,
                "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "files": {p: {"sha256": sha(v), "bytes": len(v)} for p, v in sorted(files.items())},
                "command": sys.argv, "site": site,
                "log_path": f"~/{site['remote_root']}/{job}/logs/dc.log"}
    uploads = {**files, "manifest.json": dump(manifest).encode()}
    uploads["scripts/hashes.sha256"] = "".join(f"{sha(data)}  {name}\n" for name, data in sorted(uploads.items())).encode()
    staging = ssh.job_path(job + "") + ".upload"
    stage = ("set -eu; umask 077; " + root_guard(site) + f"mkdir -p \"$HOME\"/{Q(site['remote_root'])}; "
             f"test ! -e {ssh.job_path(job)}; mkdir {staging}; "
             f"cd {staging}; tar xzf -; mkdir logs reports outputs status; "
             "echo STAGED >status/state; "
             f"cd ..; mv {Q(job + '.upload')} {Q(job)}")
    if args.dry_run:
        print(dump({"dry_run": True, "job_id": job, "remote_directory": f"~/{site['remote_root']}/{job}",
                    "files": manifest["files"], "manifest": manifest,
                    "additional_upload": {p: {"sha256": sha(uploads[p]), "bytes": len(uploads[p])} for p in ("manifest.json", "scripts/hashes.sha256")},
                    "transfer": "auto prefers mutually available rsync; fallback tar over SSH",
                    "tar_stage_argv": ssh.argv(stage),
                    "tar_stage_script": stage,
                    "launch_argv": ssh.argv(launch_script(ssh, job)) if site["execution"] != "unconfigured" else None,
                    "blocked_until": ["site library/execution attestations", "configured scheduler or approved nohup"],
                    "dc_command": "/usr/bin/tcsh -f scripts/environment.csh"}))
        return
    policy(site)
    if config["kind"] != "smoke":
        if not args.allow_full_core or not args.smoke_job:
            raise ValueError("full-core launch requires --allow-full-core and --smoke-job <successful fetched smoke ID>")
        validate_job(args.smoke_job)
        prior = json.loads((RESULTS / args.smoke_job / "manifest.json").read_text())
        summary = json.loads((RESULTS / args.smoke_job / "summary.json").read_text())
        if prior["config"]["kind"] != "smoke" or summary["state"] != "SUCCEEDED":
            raise ValueError("smoke must be a successfully fetched mapped run")
        for key in ("library", "tool_version", "compile_mode", "corner", "cell_family", "flow_sha256", "setup_script"):
            if prior["setup"][key] != setup[key]:
                raise ValueError(f"smoke setup differs: {key}")
    local = RESULTS / job
    local.mkdir(parents=True, mode=0o700)
    (local / "manifest.json").write_text(dump(manifest))
    files = uploads
    print(f"job_id={job}", flush=True)
    try:
        remote_rsync = ssh.call("command -v rsync", check=False).returncode == 0
        use_rsync = site["transfer"] != "tar" and site["transport"] == "jump" and shutil.which("rsync") and remote_rsync
        if site["transfer"] == "rsync" and not use_rsync:
            raise ValueError("rsync requested but not available on both ends / jump transport")
        if use_rsync:
            ssh.call("set -eu; umask 077; " + root_guard(site) + f"mkdir -p \"$HOME\"/{Q(site['remote_root'])}; test ! -e {ssh.job_path(job)}; mkdir {staging}")
            with tempfile.TemporaryDirectory() as temporary:
                tree = Path(temporary)
                for name, data in files.items():
                    target = tree / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    target.chmod(0o600)
                # Old rsync invokes a remote shell: quote its destination path explicitly.
                dest = f"{site['user']}@{site['host']}:" + Q(site["remote_root"] + "/" + job + ".upload/")
                run(["rsync", "-rt", "-e", shlex.join(ssh.base()[:-1]), str(tree) + "/", dest], timeout=120)
            ssh.call(f"set -eu; cd {staging}; mkdir logs reports outputs status; echo STAGED >status/state; cd ..; mv {Q(job + '.upload')} {Q(job)}")
        else:
            ssh.call(stage, data=archive(files), timeout=120)
        print(ssh.call(launch_script(ssh, job)).stdout.decode().strip())
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        (local / "submission_error.txt").write_text(str(exc) + "\n")
        raise ValueError(f"submission incomplete/uncertain for {job}; preserve directory and inspect status/logs. Never relaunch this ID blindly. {exc}") from exc


def job_ssh(job):
    validate_job(job)
    manifest = json.loads((RESULTS / job / "manifest.json").read_text())
    return SSH(manifest["site"])


def status(ssh, job):
    script = (f"set -eu; cd {ssh.job_path(job)}; "
              "for key in state exit_code hostname worker_pid launcher_pid scheduler_id started_at ended_at run_directory; do "
              'if test -f "status/$key"; then printf "%s=" "$key"; cat "status/$key"; fi; done; '
              'if test "$(cat status/state)" = RUNNING; then '
              'if test "$(hostname)" != "$(cat status/hostname)"; then echo OBSERVED=WRONG_HOST; else '
              'pid=$(cat status/worker_pid); expected=$(cat status/process_start); '
              'case "$pid" in *[!0-9]*|"") echo OBSERVED=INTERRUPTED;; *) '
              "actual=$(awk '{print $22}' \"/proc/$pid/stat\" 2>/dev/null || :); "
              'cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || :); '
              'if test "$actual" = "$expected" && test "$cwd" = "$(pwd -P)"; then '
              'echo OBSERVED=LIVE; else echo OBSERVED=INTERRUPTED; fi;; esac; fi; fi')
    result = ssh.call(script).stdout.decode()
    values = dict(line.split("=", 1) for line in result.splitlines() if "=" in line)
    if values.get("state") == "RUNNING":
        values["liveness"] = values.pop("OBSERVED", "UNVERIFIED")
    return values


def parse_reports(directory):
    metrics = {}
    for line in (directory / "reports/metrics.tsv").read_text().splitlines():
        key, value = line.split("\t")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"non-finite metric: {key}")
        metrics[key] = number
    for key in ("area", "cell_count", "arrival_ns", "required_ns", "slack_ns", "blackbox_count"):
        if key not in metrics:
            raise ValueError(f"missing metric: {key}")
    if metrics["area"] <= 0 or metrics["cell_count"] <= 0:
        raise ValueError("mapped area and cell count must be positive")
    for key in ("cell_count", "blackbox_count"):
        if metrics[key] < 0 or not metrics[key].is_integer():
            raise ValueError(f"invalid integer count: {key}")
    for name in ("reference", "check_design", "check_timing", "qor", "library"):
        if not (directory / f"reports/{name}.rpt").stat().st_size:
            raise ValueError(f"missing report: {name}")
    area_report = (directory / "reports/area.rpt").read_text()
    match = re.search(r"Total cell area:\s*([0-9.eE+\-]+)", area_report)
    if not match or not math.isclose(float(match[1]), metrics["area"], rel_tol=0.01):
        raise ValueError("report_area missing/inconsistent with machine metrics")
    timing = (directory / "reports/timing.rpt").read_text()
    slack = re.search(r"slack\s*\([^)]*\)\s*([-+0-9.eE]+)", timing)
    if not slack or not math.isclose(float(slack[1]), metrics["slack_ns"], abs_tol=0.02):
        raise ValueError("report_timing missing/inconsistent with machine metrics")
    log = (directory / "logs/dc.log").read_text(errors="replace")
    if re.search(r"(^|\s)Error:|^SYNTH_FATAL", log, re.M):
        raise ValueError("DC log contains errors")
    version = (directory / "logs/version.log").read_text()
    if not re.search(r"2020[.]09.*SP5", version, re.I):
        raise ValueError("unexpected DC version in fetched record")
    counts = dict(collections.Counter((directory / "reports/cells.tsv").read_text().splitlines()))
    if sum(counts.values()) != int(metrics["cell_count"]):
        raise ValueError("cell breakdown/count mismatch")
    metrics.update(cell_breakdown=counts, dc_version=version.strip(),
                   warnings=[line for line in log.splitlines() if "Warning:" in line],
                   unresolved_references=0,
                   area_label="pre-placement standard-cell area (library area units; see library.rpt)",
                   timing_label="pre-layout constrained max-delay path; arrival includes I/O delay where applicable",
                   wns_ns=min(0.0, metrics["slack_ns"]), tns_ns=None,
                   fmax_mhz=None)
    return metrics


def safe_extract(data, destination):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"unsafe result archive member: {member.name}")
            if not (destination / member.name).resolve().is_relative_to(destination.resolve()):
                raise ValueError("result archive escapes destination")
        tar.extractall(destination, filter="data") if sys.version_info >= (3, 12) else tar.extractall(destination)


def failure_reason(log):
    for category, pattern in (
        ("license/entitlement", r"license.*(fail|denied|unavailable)|checkout.*fail|LIC-|DCSH-1\b|Design Compiler is not enabled"),
        ("library", r"library.*(not readable|not found|cannot|failed)|read_db|DB-"),
        ("RTL/dependency/link", r"unresolved|cannot find.*design|link failed|VER-|HDL-"),
        ("constraints", r"check_timing|clock port|clock period|constraints"),
        ("mapping/validation", r"unmapped|check_design|SYNTH_FATAL"),
    ):
        if re.search(pattern, log, re.I):
            return category
    return "inspect logs/dc.log, logs/launcher.log and logs/validation.log"


def fetch(ssh, job):
    local = RESULTS / job
    data = ssh.call(f"set -eu; cd {ssh.job_path(job)}; tar czf - status logs reports outputs scripts manifest.json", timeout=120).stdout
    # Fetch may occur during a run; parse only a completed validated snapshot.
    with tempfile.TemporaryDirectory(dir=local) as temporary:
        snapshot = Path(temporary)
        safe_extract(data, snapshot)
        original = json.loads((local / "manifest.json").read_text())
        if json.loads((snapshot / "manifest.json").read_text()) != original:
            raise ValueError("remote manifest differs from local submission")
        for name, metadata in original.get("files", {}).items():
            if name.startswith("scripts/") and sha((snapshot / name).read_bytes()) != metadata["sha256"]:
                raise ValueError(f"fetched script differs from submitted hash: {name}")
        state = (snapshot / "status/state").read_text().strip()
        summary = {"job_id": job, "state": state, "clock_target_ns": original["config"]["clock"]["period_ns"]}
        if state == "FAILED":
            summary["failure_reason"] = failure_reason("\n".join(p.read_text(errors="replace") for p in (snapshot / "logs").glob("*.log")))
        if state == "SUCCEEDED":
            if (snapshot / "status/exit_code").read_text().strip() != "0":
                raise ValueError("SUCCEEDED with nonzero exit code")
            for path in ("outputs/flow_complete", "outputs/mapped.v", "outputs/mapped.sdc"):
                if not (snapshot / path).stat().st_size:
                    raise ValueError(f"missing artifact: {path}")
            summary.update(parse_reports(snapshot))
        for name in ("status", "logs", "reports", "outputs", "scripts"):
            shutil.copytree(snapshot / name, local / name, dirs_exist_ok=True)
        (local / "summary.json").write_text(dump(summary))
    print(dump(summary))


def compare(baseline, variant):
    records = []
    for job in (baseline, variant):
        validate_job(job)
        directory = RESULTS / job
        manifest = json.loads((directory / "manifest.json").read_text())
        summary = json.loads((directory / "summary.json").read_text())
        if summary["state"] != "SUCCEEDED" or (directory / "status/exit_code").read_text().strip() != "0":
            raise ValueError(f"{job} is not a successfully fetched run")
        # Revalidate reports instead of trusting an old summary.
        metrics = parse_reports(directory)
        records.append((manifest, metrics))
    differences = [key for key in records[0][0]["setup"]
                   if records[0][0]["setup"][key] != records[1][0]["setup"].get(key)]
    if differences:
        raise ValueError("incomparable synthesis setup: " + ", ".join(differences))
    a, b = records[0][1], records[1][1]
    if a["dc_version"] != b["dc_version"] or a["blackbox_count"] != b["blackbox_count"]:
        raise ValueError("incomparable observed DC versions or blackbox counts")
    return {"baseline": baseline, "variant": variant,
            "area_delta": b["area"] - a["area"],
            "area_delta_percent": 100 * (b["area"] / a["area"] - 1),
            "arrival_delta_ns": b["arrival_ns"] - a["arrival_ns"],
            "slack_delta_ns": b["slack_ns"] - a["slack_ns"],
            "scope": records[0][0]["setup"]["scope"],
            "area_label": a["area_label"], "timing_label": a["timing_label"],
            "blackbox_note": "Intentional blackbox area is excluded; see allowlist and library reports.",
            "design_config_differences": [key for key in ("defines", "parameters", "include_dirs")
                                          if records[0][0].get("config", {}).get(key) != records[1][0].get("config", {}).get(key)],
            "review_note": "Review source/config manifests for identical cache/memory sizes and unrelated hardware choices.",
            "warning_counts": [len(a["warnings"]), len(b["warnings"])],
            "fmax_mhz": None}


def doctor(site, smoke=False):
    ok = True
    for executable in ("ssh", "tar", "scp", "rsync"):
        found = shutil.which(executable)
        print(f"{'PASS' if found else 'WARN'} local {executable}: {found or 'not available'}")
    ssh = SSH(site)
    setup_probe = (f"source {Q(site['setup'])} {Q(site['tool_version'])}\n"
                   "if ( $status != 0 ) exit 70\nrehash\nwhich dc_shell\ndc_shell -version\nexit 0\n")
    script = f'''set -eu
printf 'HOST='; hostname
printf 'HOME=%s\\nSHELL=%s\\n' "$HOME" "$SHELL"
printf 'REMOTE_SH='; /bin/sh -c 'echo NONINTERACTIVE_OK'
df -Pk "$HOME"
p="$HOME"/{Q(site['remote_root'])}
while test ! -e "$p"; do p=$(dirname "$p"); done
if test -w "$p" && test -x "$p"; then echo PASS_WORK_DIRECTORY; else echo FAIL_WORK_DIRECTORY; fi
{root_guard(site)}
for tool in tar tcsh sha256sum awk grep readlink timeout nice; do
    if command -v "$tool"; then echo "PASS_TOOL_$tool"; else echo "FAIL_TOOL_$tool"; fi
done
for tool in nohup rsync scp qsub sbatch; do command -v "$tool" || echo "WARN_TOOL_$tool"; done
if test -r {Q(site['library'])}; then echo PASS_LIBRARY_READABLE; else echo FAIL_LIBRARY_READABLE; fi
/usr/bin/tcsh -f -c {Q(setup_probe)}
'''
    try:
        result = ssh.call(script, timeout=50, check=False)
        output = result.stdout.decode(errors="replace")
        print(output, end="")
        if result.returncode or "FAIL_" in output:
            diagnostic = result.stderr.decode(errors="replace")
            print("FAIL remote preflight: " + diagnostic)
            if re.search(r"administratively prohibited|stdio forwarding failed", diagnostic, re.I):
                print("FAIL jump forwarding blocked; verify Daisy-to-workstation SSH, then use transport=nested")
            elif "no matching host key type found" in diagnostic:
                print("FAIL legacy workstation host key; see synth/README.md for an explicit host-scoped RSA compatibility exception")
            elif "Permission denied" in diagnostic:
                print("FAIL SSH authentication; configure supported authorized key/agent access manually")
            ok = False
        if not re.search(r"2020\.09.*SP5", output, re.I):
            print("FAIL pinned DC release not verified in noninteractive tcsh")
            ok = False
        elif ok:
            print("PASS end-to-end SSH and pinned noninteractive DC release")
    except (ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL end-to-end SSH: {exc}")
        ok = False
    print("WARN scheduler presence is discovery only; site policy and library permission require human confirmation")
    print("WARN DB acceptance/cell metadata and license/compile entitlement require doctor --smoke (policy gated)")
    if not site["library_use_confirmed"] or not site["execution_policy_confirmed"]:
        print("WARN submission disabled by unconfirmed site/library policy")
    if smoke:
        if not ok:
            raise ValueError("repair preflight before submitting smoke")
        args = argparse.Namespace(config=ROOT / "synth/configs/smoke.json", dry_run=False,
                                  allow_full_core=False, smoke_job=None)
        submit(args, site)
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, help="site JSON (default: ignored synth/configs/nthu.local.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    diag = sub.add_parser("doctor", help="read-only remote checks; optional gated smoke submission")
    diag.add_argument("--smoke", action="store_true", help="submit one registered adder after confirmed site permissions")
    submit_parser = sub.add_parser("submit", help="package explicit synthesis inputs and launch an isolated job")
    submit_parser.add_argument("--config", required=True, type=Path)
    submit_parser.add_argument("--dry-run", action="store_true", help="show hashes, uploads and commands; no SSH or writes")
    submit_parser.add_argument("--allow-full-core", action="store_true", help="explicitly authorize this full core synthesis")
    submit_parser.add_argument("--smoke-job", help="successful fetched smoke with same library/tool/flow")
    for name in ("status", "logs", "fetch"):
        command = sub.add_parser(name)
        command.add_argument("job_id")
        if name == "logs":
            command.add_argument("--follow", action="store_true")
    comparison = sub.add_parser("compare", help="compare successfully fetched compatible jobs")
    comparison.add_argument("baseline")
    comparison.add_argument("variant")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(load_site(args.site), args.smoke)
        if args.command == "submit":
            submit(args, load_site(args.site))
        elif args.command == "compare":
            print(dump(compare(args.baseline, args.variant)))
        else:
            ssh = job_ssh(args.job_id)
            if args.command == "status":
                print(dump(status(ssh, args.job_id)))
            elif args.command == "fetch":
                fetch(ssh, args.job_id)
            else:
                path = ssh.job_path(args.job_id)
                script = f"cd {path} && " + ("tail -F logs/dc.log" if args.follow else
                         "for f in logs/launcher.log logs/dc.log logs/validation.log; do if test -f \"$f\"; then cat \"$f\"; fi; done")
                return subprocess.call(ssh.argv(script))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
