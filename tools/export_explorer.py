#!/usr/bin/env python3
"""Export a validated Spike capture as a portable execution-explorer ZIP."""
from __future__ import annotations
import argparse
import bisect
import collections
import hashlib
import json
from pathlib import Path
import re
import zipfile

from profile_spike import (ROOT, MODEL, capture, tool, sha, graph_nodes, disassemble,
                           load_capture, check_output, classify, CLASSIFICATION)
from explorer.control_flow import analyze, transfer
from explorer.registers import extract_registers
from explorer.register_provenance import analyze_register_roles
from explorer.register_compiler import compiler_origins


def graph_metadata(model_path: Path, saved_nodes: list[dict]) -> dict:
    import tflite
    nodes = graph_nodes(model_path)
    if nodes != saved_nodes:
        raise ValueError('model graph does not match the capture manifest')
    model = tflite.Model.GetRootAsModel(model_path.read_bytes(), 0)
    graph = model.Subgraphs(0)
    tensor_types = {getattr(tflite.TensorType, n): n for n in dir(tflite.TensorType) if n.isupper()}
    tensors = []
    for i in range(graph.TensorsLength()):
        t = graph.Tensors(i)
        q = t.Quantization()
        tensors.append({'id': i, 'name': (t.Name() or b'').decode(errors='replace'),
                        'shape': [int(v) for v in t.ShapeAsNumpy()], 'type': tensor_types.get(t.Type(), str(t.Type())),
                        'constant': model.Buffers(t.Buffer()).DataLength() > 0,
                        'quantization': None if not q else {
                            'scales': [float(q.Scale(j)) for j in range(q.ScaleLength())],
                            'zeroPoints': [str(q.ZeroPoint(j)) for j in range(q.ZeroPointLength())],
                            'axis': q.QuantizedDimension()}, 'producer': None, 'consumers': []})
    for n in nodes:
        op = graph.Operators(n['index'])
        n['id'] = str(n['index'])
        n['inputs'] = [int(v) for v in op.InputsAsNumpy() if v >= 0]
        n['outputs'] = [int(v) for v in op.OutputsAsNumpy()]
        n['eventId'] = str(n['index'] + 2)
        n['logical_macs'] = str(n['logical_macs'])
        n['executed_products'] = str(n['executed_products'])
        n['options'] = {}
        option_classes = {'ADD': tflite.AddOptions, 'CONV_2D': tflite.Conv2DOptions,
                          'DEPTHWISE_CONV_2D': tflite.DepthwiseConv2DOptions,
                          'FULLY_CONNECTED': tflite.FullyConnectedOptions, 'AVERAGE_POOL_2D': tflite.Pool2DOptions,
                          'SOFTMAX': tflite.SoftmaxOptions}
        if n['type'] in option_classes and op.BuiltinOptions():
            options = option_classes[n['type']]()
            raw = op.BuiltinOptions()
            options.Init(raw.Bytes, raw.Pos)
            for key in ('FusedActivationFunction', 'Padding', 'StrideH', 'StrideW', 'DilationHFactor',
                        'DilationWFactor', 'DepthMultiplier', 'FilterHeight', 'FilterWidth', 'Beta', 'KeepNumDims'):
                if hasattr(options, key):
                    n['options'][key] = getattr(options, key)()
        for i in n['outputs']:
            if tensors[i]['producer'] is not None:
                raise ValueError('multiple tensor producers')
            tensors[i]['producer'] = n['id']
        for i in n['inputs']:
            tensors[i]['consumers'].append(n['id'])
    edges = [{'source': t['producer'], 'target': c, 'tensorId': t['id'], 'id': f't{t["id"]}:{c}'}
             for t in tensors if t['producer'] is not None for c in t['consumers']]
    return {'nodes': nodes, 'tensors': tensors, 'edges': edges,
            'inputs': [int(v) for v in graph.InputsAsNumpy()], 'outputs': [int(v) for v in graph.OutputsAsNumpy()]}


def read_sources(elf: Path, pcs: list[str]) -> dict:
    sources = {}
    for offset in range(0, len(pcs), 1500):
        lines = capture(tool('addr2line'), '-a', '-f', '-C', '-i', '-e', str(elf),
                        *[hex(int(pc)) for pc in pcs[offset:offset + 1500]]).splitlines()
        current, rows = None, []
        def finish():
            if current is None:
                return
            frames = []
            for name, location in zip(rows[::2], rows[1::2]):
                match = re.match(r'^(.*):(\d+)(?: \(discriminator (\d+)\))?$', location)
                if match and match[1] != '??' and int(match[2]) > 0:
                    path = match[1]
                    if path.startswith(str(ROOT) + '/'):
                        path = path[len(str(ROOT)) + 1:]
                    # Compilation directories are upstream; addr2line normally emits absolute paths.
                    if not Path(path).is_absolute() and not (ROOT / path).exists() and (ROOT / '.deps/tflite-micro' / path).exists():
                        path = '.deps/tflite-micro/' + path
                    frames.append({'function': name, 'file': path, 'line': int(match[2]),
                                   'discriminator': int(match[3] or 0)})
                else:
                    frames.append({'function': name, 'file': None, 'line': None, 'discriminator': 0})
            sources[current] = frames
        for line in lines:
            if re.fullmatch(r'0x[0-9a-f]+', line):
                finish()
                current, rows = str(int(line, 16)), []
            else:
                rows.append(line)
        finish()
    return sources


def reviewed_annotations(elf_hash: str, instructions: dict, source_files: dict) -> list[dict]:
    # Reviewed against results/profiling/B0/analysis.md, not generic opcode guesses.
    if elf_hash != '26061ddf6b3f7f7c4fa3dc6e69137aa16dba3176943669d903e232bc1d569cac':
        return []
    groups = [
        ('Operand loads', 'load', [0x80005c94, 0x80005c98], 'Load the activation and weight as signed bytes.'),
        ('Input offset', 'arithmetic', [0x80005c9e], 'Apply the input zero-point offset before multiplying.'),
        ('Product and accumulation', 'arithmetic', [0x80005ca2, 0x80005ca8], 'Scalar product followed by INT32 accumulation.'),
        ('Address increments', 'address', [0x80005c9c, 0x80005ca6], 'Advance the activation and weight pointers.'),
        ('Channel loop control', 'control', [0x80005cac], 'Branch to the reduction-loop header.'),
        ('Depthwise padding checks', 'padding', [0x8000745e, 0x80007462, 0x80007466, 0x80007468],
         'Check whether the candidate input coordinate is inside the image; skipped padding positions do not perform a product.'),
        ('Depthwise address products', 'address', [0x8000747a, 0x80007486, 0x8000748e, 0x80007494, 0x8000749a],
         'Five address-index multiplications per valid product; these are distinct from the scalar MAC.'),
        ('Depthwise scalar product', 'arithmetic', [0x800074b6], 'Multiply the selected activation and weight after address calculation.'),
    ]
    reviewed = json.loads((ROOT / 'tools/explorer/reviewed_sources.json').read_text())
    result = []
    for title, category, addresses, description in groups:
        pcs = [str(a) for a in addresses]
        if not all(pc in instructions for pc in pcs):
            continue
        files = {f['file'] for pc in pcs for f in instructions[pc]['frames'] if f['file']}
        if any(p not in reviewed or source_files[p]['sha256'] != reviewed[p] for p in files):
            continue
        result.append({'id': f'annotation-{len(result)}', 'title': title, 'category': category,
                       'description': description, 'pcs': pcs, 'elfHash': elf_hash,
                       'sourceHashes': {p: source_files[p]['sha256'] for p in files if source_files[p]['sha256']},
                       'evidence': 'results/profiling/B0/analysis.md', 'status': 'reviewed'})
    return result


def export_bundle(capture_dir: Path, model: Path, elf: Path, output: Path, compiler_dir: Path | None = None):
    manifest = json.loads((capture_dir / 'manifest.json').read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported capture manifest schema')
    if sha(model) != manifest['hashes']['model'] or sha(elf) != manifest['hashes']['profile_elf']:
        raise ValueError('model or measured ELF does not match capture hashes')
    if not manifest['loadable_sections_identical'] or not manifest['repeat_histograms_identical']:
        raise ValueError('capture was not validated against baseline and repeat')
    for suffix in ('events.csv', 'pcs.csv'):
        if (capture_dir / f'run1.{suffix}').read_bytes() != (capture_dir / f'run2.{suffix}').read_bytes():
            raise ValueError('repeat histograms differ')
    for name in ('ordinary-output.txt', 'run1-output.txt', 'run2-output.txt'):
        check_output((capture_dir / name).read_text())
    saved_instructions = {int(k): v for k, v in manifest['instructions'].items()}
    if disassemble(elf) != saved_instructions:
        raise ValueError('manifest disassembly does not match measured ELF')
    allocate, invoke, ops, overhead = load_capture(capture_dir / 'run1', manifest['nodes'], saved_instructions)
    for event in (allocate, invoke, *ops):
        if event['total'] > 2**64 - 1 or any(n > 2**64 - 1 for n in event['histogram'].values()):
            raise ValueError('capture counter exceeds uint64')
    graph = graph_metadata(model, manifest['nodes'])
    print('Validated capture; mapping complete function disassembly...', flush=True)
    mappings = read_sources(elf, [str(pc) for pc in saved_instructions])
    raw_names = collections.defaultdict(list)
    for line in capture(tool('nm'), '-S', '-n', '--defined-only', str(elf)).splitlines():
        match = re.match(r'([0-9a-f]+) ([0-9a-f]+) ([tTW]) (.+)', line)
        if match:
            raw_names[(int(match[1], 16), int(match[2], 16))].append(match[4])
    grouped = collections.defaultdict(list)
    for s in manifest['symbols']:
        if s['kind'] in 'tTW' and s['size']:
            grouped[(s['address'], s['size'])].append(s['name'])
    functions = []
    for (address, size), names in sorted(grouped.items()):
        functions.append({'id': f'f{address}:{size}', 'name': names[0], 'aliases': names,
                          'linkageNames': raw_names.get((address, size), []), 'address': str(address),
                          'size': size, 'pcs': []})
    starts = [int(f['address']) for f in functions]
    instructions = {}
    for pc, ins in saved_instructions.items():
        # Retain overlapping symbol ranges and aliases; choose the narrowest range for navigation.
        candidates = [f for f in functions[:bisect.bisect_right(starts, pc)] if pc < int(f['address']) + f['size']]
        for f in candidates:
            f['pcs'].append(str(pc))
        primary = min(candidates, key=lambda f: f['size'])['id'] if candidates else None
        instructions[str(pc)] = {**ins, 'pc': str(pc), 'bits': hex(ins['bits']),
                                 'category': classify(ins['mnemonic']) if ins['mnemonic'] in CLASSIFICATION else 'unknown',
                                 'functionIds': [f['id'] for f in candidates], 'functionId': primary,
                                 'frames': mappings.get(str(pc), []), 'transfer': transfer(ins)}
    for f in functions:
        f['cfg'] = analyze(f['id'], f['pcs'], instructions)
    residual = dict(invoke['histogram'])
    for op in ops:
        for pc, n in op['histogram'].items():
            residual[pc] -= n
    events = []
    for e in [allocate, invoke, *ops]:
        events.append({'id': str(e['event_id']), 'kind': e['kind'], 'name': e['name'],
                       'nodeId': str(e['event_id'] - 2) if e['kind'] == 'operator' else None,
                       'entry': str(e['entry']), 'returnPc': str(e['return_pc']), 'complete': True, 'status': '0',
                       'total': str(e['total']), 'counts': {str(pc): str(n) for pc, n in e['histogram'].items()},
                       'mix': {c: str(n) for c, n in e['mix'].items()}})
    residual = {str(pc): str(n) for pc, n in residual.items() if n}
    events.append({'id': 'overhead', 'kind': 'derived', 'name': 'Interpreter overhead', 'nodeId': None,
                   'total': str(overhead), 'counts': residual, 'mix': dict(collections.Counter())})
    print('Extracting address-scoped DWARF register locations...', flush=True)
    registers = extract_registers(elf, list(saved_instructions), manifest['hashes']['profile_elf'], ROOT)
    payloads, source_files = {}, {}
    source_paths = {f['file'] for i in instructions.values() for f in i['frames'] if f['file']}
    source_paths.update(v['declaration']['file'] for v in registers['variables'].values() if v['declaration'])
    for path in sorted(source_paths):
        p = (ROOT / path).resolve()
        record = {'id': path, 'path': path, 'archivePath': None, 'sha256': None, 'status': 'unavailable'}
        if p.is_relative_to(ROOT) and p.is_file():
            content = p.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            archive_path = f'sources/{digest}.txt'
            payloads[archive_path] = content
            record.update(archivePath=archive_path, sha256=digest, status='export-time snapshot')
        source_files[path] = record
    annotations = reviewed_annotations(manifest['hashes']['profile_elf'], instructions, source_files)
    # Add hash-bound helper-body annotations using verified ELF symbols, never opcode inference.
    reviewed_hashes = json.loads((ROOT / 'tools/explorer/reviewed_sources.json').read_text())
    registers['roles'] = analyze_register_roles(functions, instructions, registers)
    for role in registers['roles']:
        if 'span' not in role:
            continue
        # Only bind a scalar shape load to a reviewed declaration. A multiply
        # or other opaque definition may be a byte-scaled temporary instead.
        if instructions[role['span']['definitionPc']]['mnemonic'] != 'lw':
            continue
        for frame in instructions[role['span']['definitionPc']]['frames']:
            file = frame['file']
            source = source_files.get(file, {})
            if not file or not frame['line'] or source.get('sha256') != reviewed_hashes.get(file) or not source.get('archivePath'):
                continue
            lines = payloads[source['archivePath']].decode().splitlines()
            if frame['line'] > len(lines):
                continue
            declaration = re.match(r'\s*const\s+int\s+(\w+)\s*=\s*(?:\w+\.Dims\(|MatchingDim\()', lines[frame['line'] - 1])
            if declaration:
                role['span']['source'] = {'name': declaration[1], 'file': file, 'line': frame['line'], 'sha256': source['sha256']}
                break
    scaling_path = '.deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc'
    scaling_verified = source_files.get(scaling_path, {}).get('sha256') == reviewed_hashes[scaling_path]
    for f in functions:
        if scaling_verified and manifest['hashes']['profile_elf'] == '26061ddf6b3f7f7c4fa3dc6e69137aa16dba3176943669d903e232bc1d569cac' and 'MultiplyByQuantizedMultiplier(' in f['name']:
            annotations.append({'id': f'scaling-{f["id"]}', 'title': 'Fixed-point scaling helper', 'category': 'scaling',
                                'description': 'Helper-body scaling only; caller zero-point adjustment, clamp and stores are excluded.',
                                'pcs': f['pcs'], 'elfHash': manifest['hashes']['profile_elf'], 'sourceHashes': {scaling_path: reviewed_hashes[scaling_path]},
                                'evidence': 'results/profiling/B0/analysis.md', 'status': 'reviewed'})
    compiler_units = []
    compiler_evidence = None
    if compiler_dir:
        cm = json.loads((compiler_dir / 'compiler.json').read_text())
        if cm.get('schemaVersion') != 1 or not cm.get('loadableIdentical') or cm.get('measuredElfHash') != sha(elf):
            raise ValueError('compiler analysis is not verified against measured ELF')
        analysis_elf = Path(cm['analysisElf'])
        from profile_spike import Elf
        a, b = Elf(elf), Elf(analysis_elf)
        if sha(analysis_elf) != cm['analysisElfHash'] or a.allocated() != b.allocated() or a.loads != b.loads:
            raise ValueError('compiler ELF changed after verification')
        payloads['compiler/commands.json'] = json.dumps(cm['commandInventory'], separators=(',', ':')).encode()
        compiler_evidence = {'loadableIdentical': True, 'measuredElfHash': cm['measuredElfHash'],
                             'analysisElfHash': cm['analysisElfHash'], 'commandInventoryPath': 'compiler/commands.json'}
        for unit in cm['units']:
            for dependency, digest in unit['dependencyHashes'].items():
                if sha(Path(dependency)) != digest:
                    raise ValueError(f'compiler dependency changed: {dependency}')
            for artifact in unit['artifacts']:
                p = (compiler_dir / artifact['path']).resolve()
                if not p.is_relative_to(compiler_dir.resolve()) or sha(p) != artifact['sha256']:
                    raise ValueError('compiler artifact path/hash mismatch')
                archive_path = f'compiler/{artifact["path"]}'
                payloads[archive_path] = p.read_bytes()
                artifact['archivePath'] = archive_path
            compiler_units.append(unit)
    registers['compilerOrigins'] = compiler_origins(functions, instructions, compiler_units, payloads) if compiler_evidence else {}
    print(f"Register evidence: {registers['coverage']['symbolicRelations']} symbolic relationships, {len(registers['roles'])} loop roles, {len(registers['compilerOrigins'])} aligned compiler instructions", flush=True)
    mapped_count = sum(any(frame['file'] for frame in ins['frames']) for ins in instructions.values())
    data = {'schemaVersion': 1, 'provenance': {**{k: v for k, v in manifest.items() if k not in {'nodes', 'instructions', 'sources', 'symbols'}},
                                              'captureAdapter': 'legacy-v1', 'sourceSnapshotStatus': 'export-time; original capture did not hash source text'},
            'graph': graph, 'events': events, 'instructions': instructions, 'functions': functions,
            'registers': registers, 'sources': source_files, 'annotations': annotations, 'compilerUnits': compiler_units, 'compilerEvidence': compiler_evidence,
            'totals': {'inference': str(invoke['total']), 'allocation': str(allocate['total']), 'overhead': str(overhead)},
            'capabilities': {'sourceMappedInstructions': mapped_count, 'staticInstructions': len(instructions),
                             'compiler': bool(compiler_units), 'loops': True}}
    payloads['evidence.json'] = json.dumps(data, separators=(',', ':'), allow_nan=False).encode()
    bundle_manifest = {'format': 'riscv-execution-explorer', 'schemaVersion': 1,
                       'files': {name: {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)} for name, content in payloads.items()}}
    total_size = sum(len(v) for v in payloads.values())
    if total_size > 512 * 1024**2 or any(len(v) > 128 * 1024**2 for v in payloads.values()):
        raise ValueError('export exceeds viewer decompression limits; reduce compiler coverage')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('manifest.json', json.dumps(bundle_manifest))
        for name, content in sorted(payloads.items()):
            archive.writestr(name, content)
    if temporary.stat().st_size > 256 * 1024**2:
        temporary.unlink()
        raise ValueError('compressed bundle exceeds viewer limit')
    temporary.replace(output)
    print(f'Exported {output}: {len(graph["nodes"])} operators, {len(functions)} functions, '
          f'{sum(len(f["cfg"]["loops"]) for f in functions)} cyclic regions; {output.stat().st_size:,} bytes')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture-dir', type=Path, required=True)
    p.add_argument('--model', type=Path, default=MODEL)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--compiler-dir', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    export_bundle(args.capture_dir, args.model, args.elf, args.output, args.compiler_dir)


if __name__ == '__main__':
    main()
