"""Structural control-flow, compiler indexing, and real B0 evidence checks."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from explorer.control_flow import analyze, transfer
from explorer.compiler import extract_functions, collect
from profile_spike import ROOT, tool, symbols, disassemble, load_capture


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='explorer-fixture-')
        cls.elf = Path(cls.temp.name) / 'loops.elf'
        subprocess.run([tool('gcc'), '-march=rv64imc', '-mabi=lp64', '-nostdlib', '-g', '-Wl,--no-relax', '-Wl,-Ttext=0x10000',
                        str(ROOT / 'tools/explorer/fixture.S'), '-o', str(cls.elf)], check=True)
        cls.instructions = {str(pc): {**i, 'transfer': transfer(i)} for pc, i in disassemble(cls.elf).items()}
        cls.functions = {s['name']: s for s in symbols(cls.elf) if s['kind'] == 'T' and s['size']}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cfg(self, name):
        f = self.functions[name]
        pcs = [pc for pc in self.instructions if f['address'] <= int(pc) < f['address'] + f['size']]
        return analyze(name, pcs, self.instructions)

    def test_nested_loops_and_exclusive_sets(self):
        cfg = self.cfg('nested')
        self.assertTrue(cfg['complete'])
        self.assertEqual(len(cfg['loops']), 2)
        outer = next(l for l in cfg['loops'] if l['children'])
        inner = next(l for l in cfg['loops'] if l['parent'])
        self.assertEqual(inner['parent'], outer['id'])
        self.assertEqual(set(outer['exclusivePcs']), set(outer['pcs']) - set(inner['pcs']))

    def test_multiple_latches_merge(self):
        loops = self.cfg('multi')['loops']
        self.assertEqual(len(loops), 1)
        self.assertEqual(len(loops[0]['latches']), 2)

    def test_irreducible_cycle_is_not_natural_loop(self):
        loops = self.cfg('irreducible')['loops']
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]['kind'], 'irreducible')

    def test_indirect_transfer_marks_partial_cfg(self):
        cfg = self.cfg('indirect')
        self.assertFalse(cfg['complete'])
        self.assertTrue(cfg['unresolved'])
        self.assertEqual(cfg['loops'][0]['confidence'], 'partial-cfg')

    def test_control_transfer_types(self):
        for mnemonic, operands, kind, target in [
            ('jal', 'x1,8000 <callee>', 'call', '32768'), ('jal', 'x0,8000 <tail>', 'jump', '32768'),
            ('c.jr', 'x1', 'return', None), ('jalr', 'x0,0(x1)', 'return', None),
            ('jalr', 'x0,0(x10)', 'indirect', None), ('c.jalr', 'x10', 'call', None)]:
            self.assertEqual(transfer({'mnemonic': mnemonic, 'operands': operands}), {'kind': kind, 'target': target})


class CompilerTests(unittest.TestCase):
    def test_function_sections_and_raw_fallback(self):
        sections = extract_functions('preamble\n;; Function foo (_Z3foov, funcdef_no=0)\na\n;; Function bar (_Z3barv, funcdef_no=1)\nb\n')
        self.assertEqual([(f['linkageName'], f['startLine'], f['endLine']) for f in sections], [('_Z3foov', 2, 3), ('_Z3barv', 4, 5)])
        self.assertEqual(extract_functions('unstructured remarks\n'), [])
        initial = extract_functions('void ns::foo (int x)\n[foo.cc:1:1] {\n  return;\n}\n')
        self.assertEqual(initial[0]['startLine'], 1)
        self.assertTrue(initial[0]['linkageName'].startswith('source:'))
        self.assertEqual(extract_functions('\t.type\t_Z3foov, @function\n_Z3foov:\nret\n', True)[0]['linkageName'], '_Z3foov')

    def test_compiler_rejects_different_loadable_bytes(self):
        # Different text placement is a concrete mismatch even when source is identical.
        with tempfile.TemporaryDirectory(prefix='explorer-mismatch-') as directory:
            p = Path(directory)
            for name, address in [('a', '0x10000'), ('b', '0x20000')]:
                subprocess.run([tool('gcc'), '-march=rv64imc', '-mabi=lp64', '-nostdlib', '-Wl,-Ttext='+address,
                                str(ROOT / 'tools/explorer/fixture.S'), '-o', str(p / name)], check=True)
            with self.assertRaisesRegex(ValueError, 'loadable'):
                collect(p, p / 'a', p / 'b')


class B0Tests(unittest.TestCase):
    def test_real_capture_and_detected_loop(self):
        build = ROOT / 'build/profiling/B0'
        if not (build / 'manifest.json').exists():
            self.skipTest('local B0 capture unavailable')
        m = json.loads((build / 'manifest.json').read_text())
        instructions = {int(pc): i for pc, i in m['instructions'].items()}
        _, inference, ops, overhead = load_capture(build / 'run1', m['nodes'], instructions)
        self.assertEqual(inference['total'], 4867278370)
        self.assertEqual(len(ops), 64)
        self.assertEqual(overhead, 4820)
        self.assertEqual(ops[4]['total'], 327839821)
        f = next(s for s in m['symbols'] if '::ConvPerChannel(' in s['name'])
        code = {str(pc): {**i, 'transfer': transfer(i)} for pc, i in instructions.items() if f['address'] <= pc < f['address'] + f['size']}
        cfg = analyze('conv', list(code), code)
        loop = next(l for l in cfg['loops'] if len(l['pcs']) == 8 and str(0x80005c94) in l['pcs'])
        self.assertEqual(sum(inference['histogram'].get(int(pc), 0) for pc in loop['pcs']), 2794488576)
        self.assertTrue(cfg['complete'])

    def test_export_static_sharing_and_compiler_evidence(self):
        path = ROOT / 'build/explorer/B0.zip'
        if not path.exists():
            self.skipTest('exported bundle unavailable')
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read('evidence.json'))
            import hashlib
            manifest = json.loads(z.read('manifest.json'))
            for name, meta in manifest['files'].items():
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), meta['sha256'])
        pc = str(0x80005ca2)
        events = [e for e in data['events'] if e['kind'] == 'operator' and pc in e['counts']]
        self.assertGreaterEqual(len(events), 32)
        self.assertIn(pc, data['instructions'])
        self.assertTrue(all('instructions' not in e for e in events))
        for unit in data['compilerUnits']:
            self.assertTrue(unit['arguments'])
            self.assertTrue(unit['dependencyHashes'])
            self.assertIn('Optimized GIMPLE', {a['stage'] for a in unit['artifacts']})


class RegisterTests(unittest.TestCase):
    def test_direct_address_piece_and_entry_value_roles(self):
        from types import SimpleNamespace as Op
        from explorer.registers import supported_registers
        reg = lambda name, *args: Op(op_name=name, args=list(args))
        self.assertEqual(supported_registers([reg('DW_OP_reg8')])[0][:2], ('x8', 'value'))
        self.assertEqual(supported_registers([reg('DW_OP_regx', 10)])[0][:2], ('x10', 'value'))
        self.assertEqual(supported_registers([reg('DW_OP_breg8', -16)])[0][:2], ('x8', 'address'))
        self.assertEqual(supported_registers([reg('DW_OP_reg8'), reg('DW_OP_piece', 4)])[0][:2], ('x8', 'piece'))
        self.assertEqual(supported_registers([reg('DW_OP_entry_value', [0x58]), reg('DW_OP_stack_value')]), [])
        self.assertEqual(supported_registers([reg('DW_OP_breg8', 0), reg('DW_OP_deref')]), [])
        self.assertEqual(supported_registers([reg('DW_OP_reg32')]), [])

    def test_compiled_register_variable_ranges(self):
        import importlib.util
        if importlib.util.find_spec('elftools') is None:
            self.skipTest('use gmake explorer-tests for pinned DWARF dependency')
        from explorer.registers import extract_registers
        from profile_spike import sha
        with tempfile.TemporaryDirectory(prefix='register-dwarf-test-') as directory:
            elf = Path(directory) / 'register.elf'
            subprocess.run([tool('g++'), '-O2', '-g', '-fomit-frame-pointer', '-march=rv64imc', '-mabi=lp64', '-nostdlib',
                            '-Wl,-e,register_fixture', '-Wl,--no-relax', '-Wl,-Ttext=0x10000',
                            str(ROOT / 'tools/explorer/register_fixture.cc'), '-o', str(elf)], check=True)
            pcs = list(disassemble(elf))
            result = extract_registers(elf, pcs, sha(elf), ROOT)
            mapped = [location for location in result['locations'].get('x8', [])
                      if result['variables'][location['variableId']]['name'] == 'accumulator']
            self.assertTrue(mapped)
            self.assertTrue(all(location['kind'] == 'value' for location in mapped))
            self.assertTrue(any(int(location['low']) <= pc < int(location['high']) for location in mapped for pc in pcs))
            variable = result['variables'][mapped[0]['variableId']]
            self.assertEqual(variable['declaration']['file'], 'tools/explorer/register_fixture.cc')
            self.assertEqual(variable['declaration']['line'], 3)
            self.assertEqual(result['semantics'], 'before-instruction')

    def test_real_b0_mapping_preserves_unavailable_registers(self):
        path = ROOT / 'build/explorer/B0.zip'
        if not path.exists():
            self.skipTest('local B0 bundle unavailable')
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read('evidence.json'))
        r = data.get('registers')
        if r is None:
            self.skipTest('re-export B0 to include variable locations')
        self.assertEqual(r['elfHash'], data['provenance']['hashes']['profile_elf'])
        def names(reg, pc):
            return {r['variables'][e['variableId']]['name'] for e in r['locations'].get(reg, [])
                    if int(e['low']) <= pc < int(e['high']) and e['kind'] == 'value'}
        self.assertIn('acc', names('x10', 0x80005c94))
        self.assertIn('input_val', names('x23', 0x80005c9e))
        self.assertEqual(names('x8', 0x80005c9e), set())


class RegisterProvenanceTests(unittest.TestCase):
    def test_symbolic_memory_values_are_bounded_and_never_evaluated(self):
        from types import SimpleNamespace as Op
        from explorer.registers import symbolic_memory_value
        op = lambda name, *args: Op(op_name=name, args=list(args))
        expression = [op('DW_OP_breg14', -1), op('DW_OP_deref_size', 1), op('DW_OP_const1u', 56), op('DW_OP_shl'), op('DW_OP_const1u', 56), op('DW_OP_shra'), op('DW_OP_stack_value')]
        self.assertEqual(symbolic_memory_value(expression), {'register': 'x14', 'offset': '-1', 'bytes': 1, 'signed': True})
        self.assertIsNone(symbolic_memory_value(expression[:-1]))
        expression[2].args[0] = 55
        self.assertIsNone(symbolic_memory_value(expression))
        self.assertEqual(symbolic_memory_value([op('DW_OP_bregx', 17, 8), op('DW_OP_deref_size', 4), op('DW_OP_stack_value')]), {'register': 'x17', 'offset': '8', 'bytes': 4, 'signed': False})
        self.assertIsNone(symbolic_memory_value([op('DW_OP_entry_value', []), op('DW_OP_deref_size', 4), op('DW_OP_stack_value')]))

    def test_compiled_pointer_roles_and_unsafe_boundaries(self):
        from explorer.register_provenance import analyze_register_roles
        with tempfile.TemporaryDirectory(prefix='pointer-analysis-test-') as directory:
            elf = Path(directory) / 'pointer.elf'
            subprocess.run([tool('gcc'), '-march=rv64imc', '-mabi=lp64', '-nostdlib', '-g', '-Wl,--no-relax', '-Wl,-Ttext=0x10000', str(ROOT / 'tools/explorer/fixture.S'), '-o', str(elf)], check=True)
            instructions = {str(pc): {**i, 'transfer': transfer(i)} for pc, i in disassemble(elf).items()}
            functions = []
            for f in symbols(elf):
                if f['kind'] != 'T' or not f['size']: continue
                pcs = [pc for pc in instructions if f['address'] <= int(pc) < f['address'] + f['size']]
                functions.append({'id': f['name'], 'address': str(f['address']), 'pcs': pcs, 'cfg': analyze(f['name'], pcs, instructions)})
            roles = analyze_register_roles(functions, instructions, {})
            pointer = next(r for r in roles if r['functionId'] == 'pointer_loop' and r['register'] == 'x14')
            boundary = next(r for r in roles if r['functionId'] == 'pointer_loop' and r['register'] == 'x27')
            self.assertEqual(pointer['stride'], 1)
            self.assertEqual(boundary['span']['register'], 'x12')
            self.assertFalse(any(r['kind'] == 'boundary' and r['functionId'] == 'changing_boundary' for r in roles))
            self.assertFalse(any(r['functionId'] in {'indirect', 'reverse_pointer', 'irreducible'} for r in roles))
            for f in functions: f['cfg']['complete'] = False
            self.assertEqual(analyze_register_roles(functions, instructions, {}), [])

    def test_compiler_alignment_handles_compression_and_rejects_ambiguity(self):
        from explorer.register_compiler import compiler_origins, canonical
        instructions = {
            '100': {'mnemonic': 'lb', 'operands': 'x13,0(x14)', 'transfer': {'kind':'next', 'target':None}},
            '104': {'mnemonic': 'c.addi', 'operands': 'x14,1', 'transfer': {'kind':'next', 'target':None}},
            '106': {'mnemonic': 'bne', 'operands': 'x27,x14,64', 'transfer': {'kind':'branch', 'target':'100'}},
        }
        fn = {'id':'f', 'linkageNames':['_Zloop'], 'cfg': {'complete':True, 'loops':[{'id':'loop', 'kind':'natural', 'blocks':['b'], 'children':[], 'pcs':list(instructions)}]}}
        rtl = ';; Function loop (_Zloop, funcdef_no=0)\n(code_label 9 0 1 1 (nil))\n(insn 1 0 2 (set (reg:SI 13 a3 [orig:100 v ] [100]) (sign_extend:SI (mem:QI (reg:DI 14 a4 [orig:101 ivtmp.1 ] [101])))))\n(insn 2 1 3 (set (reg:DI 14 a4 [orig:101 ivtmp.1 ] [101]) (plus:DI (reg:DI 14 a4) (const_int 1))))\n(jump_insn 3 2 4 (set (pc) (if_then_else (ne (reg:DI 27 s11 [orig:102 end ] [102]) (reg:DI 14 a4 [orig:101 ivtmp.1 ] [101])) (label_ref 9) (pc))))\n'
        asm = '_Zloop:\n.L1:\n lb a3,0(a4)\n addi a4,a4,1\n bne s11,a4,.L1\n'
        artifact = lambda stage, path, end: {'stage':stage, 'archivePath':path, 'functions':[{'linkageName':'_Zloop','startLine':1,'endLine':end}]}
        unit = {'id':'u', 'artifacts':[artifact('Final RTL','rtl',len(rtl.splitlines())),artifact('Emitted assembly','asm',5)]}
        payloads = {'rtl':rtl.encode(), 'asm':asm.encode()}
        origins = compiler_origins([fn], instructions, [unit], payloads)
        self.assertEqual(origins['106']['x27'][0]['name'], 'end')
        self.assertEqual(origins['106']['x14'][0]['name'], 'ivtmp.1')
        self.assertEqual(canonical('c.addi', 'x14,1'), canonical('addi','a4,a4,1'))
        payloads['asm'] = (asm + '.L2:\n lb a3,0(a4)\n addi a4,a4,1\n bne s11,a4,.L2\n').encode()
        unit['artifacts'][1]['functions'][0]['endLine'] = 9
        self.assertEqual(compiler_origins([fn], instructions, [unit], payloads), {})
        payloads['asm'] = asm.replace('bne s11,a4,.L1','bne s11,a4,.Lwrong').encode()
        unit['artifacts'][1]['functions'][0]['endLine'] = 5
        self.assertEqual(compiler_origins([fn], instructions, [unit], payloads), {})

    def test_real_b0_relations_scope_roles_and_origins(self):
        path = ROOT / 'build/explorer/B0.zip'
        if not path.exists(): self.skipTest('local B0 bundle unavailable')
        with zipfile.ZipFile(path) as z: data = json.loads(z.read('evidence.json'))
        r = data['registers']
        self.assertGreater(r['coverage']['symbolicRelations'], 0)
        related = [e for e in r['relations']['x14'] if r['variables'][e['variableId']]['name'] == 'filter_val' and int(e['low']) <= 0x80005ca8 < int(e['high'])]
        self.assertTrue(related)
        self.assertEqual(related[0]['offset'], '-1')
        self.assertTrue(related[0]['signed'])
        self.assertFalse(any(int(e['low']) <= 0x80005cac < int(e['high']) for e in r['relations']['x14']))
        role = next(e for e in r['roles'] if e['register'] == 'x27' and str(0x80005cac) in e['pcs'])
        self.assertEqual(role['span']['source']['name'], 'filter_input_depth')
        self.assertEqual(r['compilerOrigins'][str(0x80005cac)]['x14'][0]['name'], 'ivtmp.85')
        self.assertEqual(r['compilerOrigins'][str(0x80005cac)]['x27'][0]['name'], '_90')


if __name__ == '__main__':
    unittest.main()
