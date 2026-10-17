#!/usr/bin/env python3
"""Build isolated compiler evidence and verify correspondence to a measured ELF."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profile_spike import ROOT, Elf, sha, tool


def extract_functions(text: str, assembly: bool = False) -> list[dict]:
    lines = text.splitlines()
    starts = []
    if assembly:
        # GCC emits .type <linkage>, @function before each function definition.
        for i, line in enumerate(lines):
            match = re.match(r'\s*\.type\s+([^,]+),\s*@function', line)
            if match:
                starts.append((i, match[1], match[1]))
    else:
        for i, line in enumerate(lines):
            match = re.match(r';; Function (.*?) \(([^,\s)]+)', line)
            if match:
                starts.append((i, match[1], match[2]))
    if not starts and not assembly:
        # Initial GIMPLE uses top-level source signatures instead of ;; Function markers.
        for i, line in enumerate(lines[:-1]):
            if line and not line[0].isspace() and ' (' in line and line.rstrip().endswith(')'):
                next_line = lines[i + 1]
                if next_line == '{' or re.match(r'^\[.*\] \{$', next_line):
                    starts.append((i, line, 'source:' + line))
    return [{'name': name, 'linkageName': linkage, 'startLine': i + 1,
             'endLine': starts[n + 1][0] if n + 1 < len(starts) else len(lines)}
            for n, (i, name, linkage) in enumerate(starts)]


def collect(root: Path, measured: Path, analysis: Path):
    a, b = Elf(measured), Elf(analysis)
    if a.allocated() != b.allocated() or a.loads != b.loads:
        raise ValueError('analysis ELF changes loadable bytes/layout; capture the matching executable before attaching IR')
    units = []
    for record in sorted(root.glob('*.json')):
        if record.name == 'compiler.json':
            continue
        unit = json.loads(record.read_text())
        if not unit.get('selected'):
            continue
        for dependency, digest in unit['dependencyHashes'].items():
            if sha(Path(dependency)) != digest:
                raise ValueError(f'dependency changed during analysis: {dependency}')
        unit['artifacts'] = []
        for path in sorted((root / unit['id']).iterdir()):
            stage = None
            name = path.name
            for suffix, title in [('original', 'Original tree'), ('gimple', 'Initial GIMPLE'), ('optimized', 'Optimized GIMPLE'),
                                  ('expand', 'RTL expansion'), ('final', 'Final RTL'), ('inline', 'Inlining analysis')]:
                if name.endswith('.' + suffix):
                    stage = title
            if path.suffix == '.s':
                stage = 'Emitted assembly'
            elif name == 'remarks.txt':
                stage = 'Optimization remarks'
            elif name == 'passes.txt':
                stage = 'Pass discovery'
            if stage:
                text = path.read_text(errors='replace')
                unit['artifacts'].append({'stage': stage, 'path': str(path.relative_to(root)), 'sha256': sha(path),
                                          'functions': extract_functions(text, path.suffix == '.s')})
        required = {'Initial GIMPLE', 'Optimized GIMPLE', 'RTL expansion', 'Final RTL', 'Emitted assembly', 'Pass discovery'}
        if not required <= {a['stage'] for a in unit['artifacts']}:
            raise ValueError(f'incomplete diagnostic outputs for {unit["source"]}')
        units.append(unit)
    if len(units) != 4:
        raise ValueError(f'expected four selected translation units, found {len(units)}; use a fresh analysis build directory')
    data = {'schemaVersion': 1, 'measuredElfHash': sha(measured), 'analysisElf': str(analysis),
            'analysisElfHash': sha(analysis), 'loadableIdentical': True, 'units': units,
            'commandInventory': [json.loads(p.read_text()) for p in sorted(root.glob('*.json')) if p.name != 'compiler.json']}
    (root / 'compiler.json').write_text(json.dumps(data, indent=2))
    print(f'Verified compiler evidence: {len(data["commandInventory"])} compilation commands, {len(units)} units with IR')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    build = root / 'build'
    env = dict(os.environ, EXPLORER_COMPILER_DIR=str(root))
    env['PATH'] = str(ROOT / '.deps/tflm-python/bin') + os.pathsep + env['PATH']
    wrapper = ROOT / 'tools/explorer/compiler_wrapper.py'
    # Upstream recipes do not track this wrapper or all diagnostic flag changes.
    # Reuse only when the previous command inventory's inputs still match.
    stamp = root / 'build-inputs.stamp'
    fingerprint = sha(wrapper) + sha(Path(__file__)) + sha(ROOT / 'tflm/platform/rv64imc/rv64imc_makefile.inc')
    fingerprint += subprocess.check_output([tool('g++'), '--version'], text=True)
    reusable = stamp.exists() and stamp.read_text() == fingerprint
    previous = root / 'compiler.json'
    if reusable and previous.exists():
        old = json.loads(previous.read_text())
        reusable = all(Path(p).is_file() and sha(Path(p)) == digest
                       for command in old['commandInventory'] for p, digest in command['dependencyHashes'].items())
    else:
        reusable = False
    if not reusable:
        # These are exclusively generated analysis outputs; measured captures are elsewhere.
        if root == ROOT or not root.is_relative_to(ROOT / 'build'):
            raise ValueError('compiler analysis output must be inside the repository build/ directory')
        for path in root.iterdir():
            if path.name == 'build' or re.fullmatch(r'[0-9a-f]{20}', path.name):
                if path.is_symlink():
                    raise ValueError('refusing symlink in analysis output')
                if path.is_dir():
                    shutil.rmtree(path)
            elif re.fullmatch(r'[0-9a-f]{20}\.(json|tmp)', path.name) or path.name in {'compiler.json', 'build-inputs.stamp'}:
                path.unlink()
    command = ['gmake', '-s', f'-j{args.jobs}', '-C', str(ROOT / '.deps/tflite-micro'),
               '-f', 'tensorflow/lite/micro/tools/make/Makefile', f'EXTERNAL_DIR={ROOT}',
               'TARGET=rv64imc', 'TARGET_ARCH=rv64imc', f'RV64_TOOLCHAIN_ROOT={ROOT}/.deps/xpack-riscv/bin/',
               f'PATH_TO_TARGET_SRCS={ROOT}/tflm/platform/rv64imc', f'BASE_GENDIR={build}',
               'SKIP_DOWNLOADS=1', 'BUILD_TYPE=release_with_logs', 'PROFILE_DEBUG_SYMBOLS=1',
               'CXX=' + shlex.join([sys.executable, str(wrapper), tool('g++')]),
               'CC=' + shlex.join([sys.executable, str(wrapper), tool('gcc')]), 'efficientnet_lite0']
    subprocess.run(command, check=True, env=env)
    analysis = build / 'rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0'
    collect(root, args.elf.resolve(), analysis)
    stamp.write_text(fingerprint)


if __name__ == '__main__':
    main()
