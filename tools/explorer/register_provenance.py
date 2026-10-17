"""Static pointer-loop evidence; no histogram path selection or memory replay."""
from __future__ import annotations
from collections import defaultdict
import re

REGISTER = re.compile(r'x(?:[0-9]|[12][0-9]|3[01])$')
LOADS = {'lb': 1, 'lbu': 1, 'lh': 2, 'lhu': 2, 'lw': 4, 'lwu': 4, 'ld': 8, 'c.lw': 4, 'c.ld': 8, 'c.lwsp': 4, 'c.ldsp': 8}
STORES = {'sb', 'sh', 'sw', 'sd', 'c.sw', 'c.sd', 'c.swsp', 'c.sdsp'}
ALU = set('addi addiw add addw sub subw mul mulw mulh mulhu mulhsu div divu divw divuw rem remu remw remuw and andi or ori xor xori sll slli sllw slliw srl srli srlw srliw sra srai sraw sraiw slt sltu slti sltiu lui auipc'.split())
ALU |= {'c.' + x for x in 'mv li lui add addw sub subw and or xor addi addiw addi16sp addi4spn slli srli srai andi'.split()}
CALLER_SAVED = {1, 5, 6, 7, *range(10, 18), *range(28, 32)}


def operands(ins):
    return [x.strip() for x in ins['operands'].split('#')[0].split(',')]


def destination(ins):
    if ins['mnemonic'] in LOADS or ins['mnemonic'] in ALU:
        value = operands(ins)[0]
        return value if REGISTER.fullmatch(value) else None
    return None


def increment(ins):
    p = operands(ins)
    if ins['mnemonic'] == 'c.addi' and len(p) == 2:
        return p[0], int(p[1], 0)
    if ins['mnemonic'] == 'addi' and len(p) == 3 and p[0] == p[1]:
        return p[0], int(p[2], 0)
    return None


def analyze_register_roles(functions, instructions, registers):
    roles = []
    relations = registers.get('relations', {})
    for fn in functions:
        cfg = fn['cfg']
        if not cfg['complete']:
            continue
        blocks = {b['id']: b for b in cfg['blocks']}
        owners = {pc: (b['id'], i) for b in blocks.values() for i, pc in enumerate(b['pcs'])}
        pred = defaultdict(set)
        for b in blocks.values():
            for edge in b['successors']:
                pred[edge['to']].add(b['id'])
        cyclic = {pc for loop in cfg['loops'] for pc in loop['pcs']}
        budget = [12000]
        active = set()
        leaves = {}
        cycle = object()

        # Symbolic 64-bit add/copy provenance. Unsupported definitions remain
        # opaque leaves; only shared definitions can cancel. Never read memory.
        def value(reg, block_id, end, depth=0):
            budget[0] -= 1
            if budget[0] < 0 or depth > 32:
                return None
            if reg == 'x0':
                return {}
            query = reg, block_id, end
            if query in active:
                return cycle
            active.add(query)
            visited, pending, answers = set(), [(block_id, end)], []
            unknown = False
            while pending and not unknown:
                b, stop = pending.pop()
                if (b, stop) in visited:
                    continue
                visited.add((b, stop))
                found = False
                for index in range(stop - 1, -1, -1):
                    budget[0] -= 1
                    if budget[0] < 0:
                        unknown = True
                        break
                    pc = blocks[b]['pcs'][index]
                    ins, p = instructions[pc], operands(instructions[pc])
                    kind, mnemonic = ins['transfer']['kind'], ins['mnemonic']
                    explicit_link = mnemonic in {'jal', 'jalr'} and len(p) > 1 and p[0] == reg
                    if (kind == 'call' and int(reg[1:]) in CALLER_SAVED) or explicit_link:
                        unknown = True
                        break
                    if destination(ins) == reg:
                        def read(r):
                            return value(r, b, index, depth + 1)
                        if mnemonic == 'c.mv':
                            answer = read(p[1])
                        elif mnemonic in {'add', 'sub', 'c.add', 'c.sub'}:
                            a, c = (p[0], p[1]) if mnemonic.startswith('c.') else (p[1], p[2])
                            left, right = read(a), read(c)
                            answer = combine(left, right, -1 if mnemonic.endswith('sub') else 1)
                        elif mnemonic in {'addi', 'c.addi', 'c.addi16sp', 'c.addi4spn'}:
                            a, immediate = (p[0], p[1]) if len(p) == 2 else (p[1], p[2])
                            answer = combine(read(a), {'constant': int(immediate, 0)}, 1)
                        else:
                            key = f'{pc}:{reg}'
                            leaves[key] = {'pc': pc, 'register': reg}
                            answer = {key: 1}
                        if answer is None:
                            unknown = True
                        else:
                            answers.append(answer)
                        found = True
                        break
                    if mnemonic not in ALU and mnemonic not in LOADS and mnemonic not in STORES and kind not in {'branch', 'jump', 'call'}:
                        unknown = True
                        break
                if unknown:
                    break
                if not found:
                    if not pred[b] or blocks[b]['start'] == fn['address']:
                        answers.append({f'entry:{reg}': 1})
                    else:
                        pending.extend((p, len(blocks[p]['pcs'])) for p in pred[b])
            active.remove(query)
            concrete = [answer for answer in answers if answer is not cycle]
            if unknown or not answers or (concrete and any(a != concrete[0] for a in concrete)):
                return None
            return concrete[0] if concrete else cycle

        def combine(left, right, sign):
            if left is None or right is None or left is cycle or right is cycle:
                return None
            result = dict(left)
            for key, n in right.items():
                result[key] = result.get(key, 0) + sign * n
            return {key: n for key, n in result.items() if n}

        for loop in cfg['loops']:
            if loop['kind'] != 'natural' or loop['children'] or len(loop['blocks']) != 1:
                continue
            block = blocks[loop['header']]
            pcs = block['pcs']
            last = instructions[pcs[-1]]
            if last['mnemonic'] != 'bne' or last['transfer']['target'] != block['start']:
                continue
            if any(instructions[pc]['mnemonic'] not in ALU | LOADS.keys() | {'bne'} for pc in pcs):
                continue
            writes = defaultdict(list)
            for pc in pcs:
                reg = destination(instructions[pc])
                if reg:
                    writes[reg].append(pc)
            pointers = {}
            for reg, definitions in writes.items():
                if len(definitions) != 1:
                    continue
                update = increment(instructions[definitions[0]])
                if not update or update[1] <= 0:
                    continue
                loads = [pc for pc in pcs if instructions[pc]['mnemonic'] in LOADS and re.fullmatch(r'-?(?:0x[0-9a-f]+|\d+)\(' + reg + r'\)', operands(instructions[pc])[-1])]
                if loads:
                    pointers[reg] = {'functionId': fn['id'], 'loopId': loop['id'], 'register': reg, 'kind': 'pointer', 'pcs': pcs,
                                     'stride': update[1], 'loadPcs': loads, 'updatePcs': definitions, 'comparePc': pcs[-1],
                                     'sourceVariableIds': sorted({r['variableId'] for r in relations.get(reg, []) if any(int(r['low']) <= int(pc) < int(r['high']) for pc in pcs)})}
            p = operands(last)
            for reg in p[:2]:
                other = p[1] if reg == p[0] else p[0]
                if reg not in pointers or other in writes or not REGISTER.fullmatch(other):
                    continue
                pointer = pointers[reg]
                pointer['relatedRegister'] = other
                boundary = {**pointer, 'register': other, 'relatedRegister': reg, 'kind': 'boundary', 'updatePcs': []}
                # Prove end - initial_pointer equals one scalar definition on
                # every external predecessor. Common changing definitions can
                # cancel only within that same straight-line predecessor block.
                spans = []
                for before in pred[block['id']] - {block['id']}:
                    budget[0] = 12000
                    leaves.clear()
                    end = len(blocks[before]['pcs'])
                    initial = value(reg, before, end)
                    limit = value(other, before, end)
                    difference = combine(limit, initial, -1)
                    if initial is None or limit is None or difference is None:
                        spans = []
                        break
                    cancelled = set(initial) & set(limit)
                    if any(key in leaves and leaves[key]['pc'] in cyclic and owners[leaves[key]['pc']][0] != before for key in cancelled):
                        spans = []
                        break
                    if len(difference) != 1:
                        spans = []
                        break
                    key, coefficient = next(iter(difference.items()))
                    if coefficient != 1 or key not in leaves or leaves[key]['pc'] in cyclic:
                        spans = []
                        break
                    spans.append(leaves[key])
                if spans and all(s == spans[0] for s in spans):
                    pointer['span'] = boundary['span'] = {'definitionPc': spans[0]['pc'], 'register': spans[0]['register']}
                roles.append(boundary)
            roles.extend(pointers.values())
    return roles
