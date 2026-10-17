"""Conservative compiler-origin links for uniquely aligned small loop bodies.

A link requires matching function linkage, normalized emitted assembly, final RTL,
and the decoded measured loop, including the backedge destination in all three.
Compression aliases are normalized. Relaxed/multi-insn/unrecognized patterns fail
closed; RTL instruction IDs are never treated as executable addresses.
"""
from __future__ import annotations
import re

ABI = {'zero': 0, 'ra': 1, 'sp': 2, 'gp': 3, 'tp': 4, 'fp': 8}
ABI.update({f't{i}': n for i, n in enumerate([5, 6, 7, 28, 29, 30, 31])})
ABI.update({f's{i}': n for i, n in enumerate([8, 9, *range(18, 28)])})
ABI.update({f'a{i}': i + 10 for i in range(8)})


def canonical(mnemonic, operands):
    operands = re.sub(r'\b(?:zero|ra|sp|gp|tp|fp|[ast]\d+)\b', lambda m: 'x' + str(ABI[m[0]]) if m[0] in ABI else m[0], operands)
    p = [x.strip() for x in operands.split('#')[0].split(',')]
    if mnemonic == 'c.mv': mnemonic = 'mv'
    elif mnemonic.startswith('c.'):
        mnemonic = mnemonic[2:]
        if mnemonic in {'addi', 'addiw', 'slli', 'srli', 'srai', 'andi', 'add', 'addw', 'sub', 'subw', 'and', 'or', 'xor'}:
            p = [p[0], p[0], p[1]]
        elif mnemonic in {'ldsp', 'lwsp', 'sdsp', 'swsp'}: mnemonic = mnemonic[:2]
        elif mnemonic == 'j': mnemonic, p = 'jal', ['x0', p[0]]
        elif mnemonic in {'addi16sp', 'addi4spn'}:
            mnemonic = 'addi'
            if len(p) == 2: p = [p[0], p[0], p[1]]
    if mnemonic in {'bne', 'beq', 'blt', 'bge', 'bltu', 'bgeu', 'jal'}:
        p[-1] = '@target'
    if mnemonic == 'addi' and len(p) == 3 and p[2] == '0': mnemonic, p = 'mv', p[:2]
    return mnemonic, tuple(p)


def rtl_roots(text, start_line):
    """Read balanced RTL roots, retaining exact line ranges and raw excerpts."""
    root, depth, quoted, escaped, first = [], 0, False, False, 0
    line = start_line
    for char in text:
        if depth == 0:
            if char == '(':
                root, depth, first = [char], 1, line
        else:
            root.append(char)
            if quoted:
                if escaped: escaped = False
                elif char == '\\': escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char == '(': depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0: yield ''.join(root), first, line
        if char == '\n': line += 1


def parse_rtl(text):
    stack, result = [], None
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token == '(':
            if len(stack) > 64: return None
            child = []
            if stack: stack[-1].append(child)
            else: result = child
            stack.append(child)
        elif token == ')':
            if not stack: return None
            stack.pop()
        elif stack: stack[-1].append(token)
    return result if not stack else None


def head(node):
    return node[0].split(':')[0].split('/')[0] if isinstance(node, list) and node and isinstance(node[0], str) else ''


def reg(node):
    return 'x' + node[1] if head(node) == 'reg' and node[1].isdigit() and 0 <= int(node[1]) < 32 else None


def rtl_instruction(root):
    change = next((x for x in root if head(x) == 'set'), None)
    if change is None: return None, None
    dest, source = change[1:3]
    if head(dest) == 'pc' and head(source) == 'if_then_else':
        condition, target = source[1:3]
        names = {'ne': 'bne', 'eq': 'beq', 'lt': 'blt', 'ge': 'bge', 'ltu': 'bltu', 'geu': 'bgeu'}
        if head(condition) in names and reg(condition[1]) and reg(condition[2]) and head(target) == 'label_ref':
            return (names[head(condition)], (reg(condition[1]), reg(condition[2]), '@target')), target[1]
        return None, None
    rd = reg(dest)
    if not rd: return None, None
    extension = head(source)
    if extension in {'sign_extend', 'zero_extend'}: source = source[1]
    if head(source) == 'mem':
        address = source[1]
        base, offset = reg(address), '0'
        if head(address) == 'plus' and reg(address[1]) and head(address[2]) == 'const_int':
            base, offset = reg(address[1]), address[2][1]
        size = source[0].split(':')[-1]
        mnemonic = {'QI': 'lb', 'HI': 'lh', 'SI': 'lw', 'DI': 'ld'}.get(size)
        if mnemonic and extension == 'zero_extend' and size != 'DI': mnemonic += 'u'
        if base and mnemonic: return (mnemonic, (rd, f'{offset}({base})')), None
    if head(source) in {'plus', 'minus', 'mult'}:
        left, right = source[1:3]
        word = source[0].endswith(':SI')
        mnemonic = {'plus': 'add', 'minus': 'sub', 'mult': 'mul'}[head(source)] + ('w' if word else '')
        if reg(left) and reg(right): return (mnemonic, (rd, reg(left), reg(right))), None
        if head(source) == 'plus' and reg(left) and head(right) == 'const_int':
            return canonical('addiw' if word else 'addi', f'{rd},{reg(left)},{right[1]}'), None
    if reg(source) and extension != 'sign_extend': return ('mv', (rd, reg(source))), None
    return None, None


def matches(sequence, needle):
    return [i for i in range(len(sequence) - len(needle) + 1) if sequence[i:i + len(needle)] == needle]


def compiler_origins(functions, instructions, units, payloads):
    result = {}
    for fn in functions:
        loops = [l for l in fn['cfg']['loops'] if fn['cfg']['complete'] and l['kind'] == 'natural' and len(l['blocks']) == 1 and not l['children'] and 3 <= len(l['pcs']) <= 32]
        if not loops: continue
        for unit in units:
            rtl = next((a for a in unit['artifacts'] if a['stage'] == 'Final RTL'), None)
            asm = next((a for a in unit['artifacts'] if a['stage'] == 'Emitted assembly'), None)
            if not rtl or not asm: continue
            rfunc = [f for f in rtl['functions'] if f['linkageName'] in fn['linkageNames']]
            afunc = [f for f in asm['functions'] if f['linkageName'] in fn['linkageNames']]
            if len(rfunc) != 1 or len(afunc) != 1: continue
            rlines = payloads[rtl['archivePath']].decode().splitlines()
            alines = payloads[asm['archivePath']].decode().splitlines()
            emitted, asm_labels = [], {}
            for number in range(afunc[0]['startLine'], afunc[0]['endLine'] + 1):
                line = alines[number - 1].strip()
                if line.endswith(':'): asm_labels[line[:-1]] = len(emitted)
                elif line and not line.startswith(('.', '#')):
                    match = re.fullmatch(r'([a-z][a-z0-9.]*)\s*(.*)', line)
                    if match:
                        emitted.append({'key': canonical(*match.groups()), 'line': number, 'raw': line, 'target': match[2].split(',')[-1].strip()})
            final, rtl_labels = [], {}
            section = '\n'.join(rlines[rfunc[0]['startLine'] - 1:rfunc[0]['endLine']])
            for raw, low, high in rtl_roots(section, rfunc[0]['startLine']):
                root = parse_rtl(raw)
                if not root: continue
                if head(root) == 'code_label': rtl_labels[root[1]] = len(final)
                if head(root) not in {'insn', 'jump_insn', 'call_insn'}: continue
                key, target = rtl_instruction(root)
                origins = {}
                for number, name in re.findall(r'\(reg(?:/[^:\s()]+)?:[A-Z]+ (\d+) [^()\n]*?\[orig:\d+\s+([^\]\s]+)', raw):
                    if int(number) < 32: origins.setdefault('x' + number, set()).add(name)
                final.append({'key': key, 'line': low, 'endLine': high, 'target': target,
                              'origins': {reg: next(iter(names)) for reg, names in origins.items() if len(names) == 1}})
            for loop in loops:
                pcs = sorted(loop['pcs'], key=int)
                if instructions[pcs[-1]]['transfer']['target'] != pcs[0]: continue
                needle = [canonical(instructions[pc]['mnemonic'], instructions[pc]['operands']) for pc in pcs]
                am = matches([r['key'] for r in emitted], needle)
                rm = matches([r['key'] for r in final], needle)
                if len(am) != 1 or len(rm) != 1: continue
                ai, ri = am[0], rm[0]
                if asm_labels.get(emitted[ai + len(pcs) - 1]['target']) != ai or rtl_labels.get(final[ri + len(pcs) - 1]['target']) != ri: continue
                for index, pc in enumerate(pcs):
                    record = final[ri + index]
                    for register, name in record['origins'].items():
                        origin = {'name': name, 'unitId': unit['id'], 'artifactPath': rtl['archivePath'],
                                  'startLine': record['line'], 'endLine': record['endLine'],
                                  'assemblyPath': asm['archivePath'], 'assemblyLine': emitted[ai + index]['line'],
                                  'matching': 'unique-loop-window', 'loopId': loop['id']}
                        values = result.setdefault(pc, {}).setdefault(register, [])
                        if origin not in values: values.append(origin)
    return result
