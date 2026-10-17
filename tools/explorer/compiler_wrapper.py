#!/usr/bin/env python3
"""Record actual compiler invocations; add diagnostic outputs to selected units."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

SELECTED = ('tensorflow/lite/micro/kernels/conv.cc',
            'tensorflow/lite/micro/kernels/depthwise_conv.cc',
            'tensorflow/lite/kernels/internal/common.cc',
            'tensorflow/lite/micro/kernels/quantize.cc')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    compiler, *arguments = sys.argv[1:]
    if '-c' not in arguments:
        return subprocess.run([compiler, *arguments]).returncode
    source = next((a for a in arguments if a.endswith(('.cc', '.cpp', '.c', '.S'))), None)
    if not source or '-o' not in arguments:
        raise ValueError('unrecognized compilation command')
    directory = Path.cwd()
    source_path = (directory / source).resolve()
    output = (directory / arguments[arguments.index('-o') + 1]).resolve()
    unit_id = hashlib.sha256(str(output).encode()).hexdigest()[:20]
    root = Path(os.environ['EXPLORER_COMPILER_DIR'])
    stage_dir = root / unit_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    selected = any(str(source_path).endswith(path) for path in SELECTED)
    diagnostics = []
    if selected:
        diagnostics = ['-save-temps=obj', '-dumpdir', str(stage_dir) + '/', '-dumpbase', source_path.name,
                       '-fdump-tree-original-lineno', '-fdump-tree-gimple-lineno', '-fdump-tree-optimized-lineno',
                       '-fdump-rtl-expand', '-fdump-rtl-final', '-fdump-ipa-inline',
                       '-fopt-info-all=' + str(stage_dir / 'remarks.txt')]
    actual = [compiler, *arguments, *diagnostics]
    result = subprocess.run(actual)
    if result.returncode:
        return result.returncode
    # GCC computes prerequisites using the actual flags, include paths and source.
    base = []
    skip = False
    for arg in arguments:
        if skip:
            skip = False
            continue
        if arg in ('-o', '-MF', '-MT', '-MQ'):
            skip = True
        elif arg not in ('-c', '-MD', '-MMD', '-MP'):
            base.append(arg)
    text = subprocess.check_output([compiler, *base, '-MM', '-MT', 'unit'], text=True)
    names = shlex.split(text.replace('\\\n', '').split(':', 1)[1])
    dependencies = {str((directory / p).resolve()): digest(directory / p) for p in names}
    if selected:
        discovery = subprocess.run([compiler, *base, '-fsyntax-only', '-fdump-passes'], capture_output=True, text=True, check=True)
        (stage_dir / 'passes.txt').write_text(discovery.stderr)
        # save-temps uses dumpdir for its .s; retain only relevant dump formats in the index.
    record = {'id': unit_id, 'source': str(source_path), 'directory': str(directory),
              'arguments': actual, 'baseArguments': [compiler, *arguments], 'output': str(output),
              'selected': selected, 'dependencyHashes': dependencies}
    temporary = root / f'{unit_id}.tmp'
    temporary.write_text(json.dumps(record, indent=2))
    temporary.replace(root / f'{unit_id}.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
