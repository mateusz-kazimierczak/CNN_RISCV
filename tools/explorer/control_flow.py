"""Conservative function-local RV64 control flow and natural loop analysis.

Edges are static possibilities, never inferred dynamic branch outcomes. Counts
are supplied separately by the viewer/exporter and are never used for detection.
"""
from __future__ import annotations
import re

CONDITIONAL = {'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu', 'c.beqz', 'c.bnez'}


def transfer(instruction: dict) -> dict:
    mnemonic, operands = instruction['mnemonic'], instruction['operands'].split('#')[0].strip()
    parts = [p.strip() for p in operands.split(',')]
    target = None
    if mnemonic in CONDITIONAL | {'jal', 'c.j', 'c.jal'}:
        match = re.match(r'(?:0x)?([0-9a-f]+)(?:\s|$)', parts[-1])
        if match:
            target = str(int(match[1], 16))
    kind = 'next'
    if mnemonic in CONDITIONAL:
        kind = 'branch'
    elif mnemonic in {'jal', 'c.j', 'c.jal'}:
        kind = 'call' if mnemonic == 'c.jal' or (mnemonic == 'jal' and parts[0] != 'x0') else 'jump'
    elif mnemonic in {'jalr', 'c.jr', 'c.jalr'}:
        if mnemonic == 'c.jalr' or (mnemonic == 'jalr' and parts[0] in {'x1', 'x5'}):
            kind = 'call'
        elif (mnemonic == 'c.jr' and operands == 'x1') or (mnemonic == 'jalr' and parts == ['x0', '0(x1)']):
            kind = 'return'
        else:
            kind = 'indirect'
    elif mnemonic in {'ecall', 'ebreak', 'c.ebreak', 'mret', 'sret'}:
        kind = 'indirect'
    return {'kind': kind, 'target': target}


def analyze(function_id: str, pcs: list[str], instructions: dict) -> dict:
    pcs = sorted(pcs, key=int)
    if not pcs:
        return {'blocks': [], 'loops': [], 'unresolved': [], 'complete': True}
    positions = {pc: i for i, pc in enumerate(pcs)}
    leaders = {pcs[0]}
    for i, pc in enumerate(pcs):
        t = instructions[pc]['transfer']
        if t['target'] in positions and t['kind'] != 'call':
            leaders.add(t['target'])
        if i + 1 < len(pcs) and (t['kind'] != 'next' or int(pc) + instructions[pc]['length'] != int(pcs[i + 1])):
            leaders.add(pcs[i + 1])
    blocks, owner = [], {}
    for pc in pcs:
        if pc in leaders:
            blocks.append({'id': f'{function_id}:b{pc}', 'start': pc, 'pcs': [], 'successors': [], 'calls': []})
        blocks[-1]['pcs'].append(pc)
        owner[pc] = blocks[-1]['id']
    by_id = {b['id']: b for b in blocks}
    unresolved = []
    for i, block in enumerate(blocks):
        pc = block['pcs'][-1]
        t = instructions[pc]['transfer']
        next_pc = str(int(pc) + instructions[pc]['length'])
        fallthrough = owner.get(next_pc)
        if t['kind'] in {'next', 'branch', 'call'} and fallthrough:
            block['successors'].append({'to': fallthrough, 'kind': 'return-continuation' if t['kind'] == 'call' else 'fallthrough'})
        elif t['kind'] in {'next', 'branch', 'call'}:
            unresolved.append({'pc': pc, 'reason': 'fallthrough outside function or undecoded bytes'})
        if t['kind'] in {'jump', 'branch'}:
            if t['target'] in owner:
                block['successors'].append({'to': owner[t['target']], 'kind': 'branch'})
            elif t['target'] is None or t['kind'] == 'branch':
                unresolved.append({'pc': pc, 'reason': 'unresolved or external conditional target'})
        if t['kind'] == 'indirect':
            unresolved.append({'pc': pc, 'reason': 'indirect control transfer'})
        if t['kind'] == 'call':
            block['calls'].append({'pc': pc, 'target': t['target'], 'kind': 'static call; continuation assumes return'})
    successors = {b['id']: {e['to'] for e in b['successors']} for b in blocks}
    pred = {b: set() for b in by_id}
    for b, targets in successors.items():
        for target in targets:
            pred[target].add(b)
    entry = blocks[0]['id']
    reachable, work = set(), [entry]
    while work:
        b = work.pop()
        if b not in reachable:
            reachable.add(b)
            work.extend(successors[b])
    dom = {b: ({b} if b == entry else set(reachable)) for b in reachable}
    changed = True
    while changed:
        changed = False
        for b in sorted(reachable - {entry}):
            incoming = pred[b] & reachable
            new = {b} | (set.intersection(*(dom[p] for p in incoming)) if incoming else set())
            if new != dom[b]:
                dom[b] = new
                changed = True
    headers = {}
    for tail in reachable:
        for head in successors[tail]:
            if head in dom[tail]:
                members = {head, tail}
                work = [] if tail == head else [tail]
                while work:
                    n = work.pop()
                    for p in pred[n] & reachable:
                        if p not in members and head in dom[p]:
                            members.add(p)
                            work.append(p)
                item = headers.setdefault(head, {'blocks': set(), 'latches': set()})
                item['blocks'].update(members)
                item['latches'].add(tail)
    loops = []
    for head, info in sorted(headers.items()):
        members = sorted(info['blocks'], key=lambda b: int(by_id[b]['start']))
        loops.append({'id': f'{function_id}:loop{by_id[head]["start"]}', 'kind': 'natural', 'header': head,
                      'blocks': members, 'latches': sorted(info['latches']), 'children': [], 'parent': None,
                      'pcs': sorted({p for b in members for p in by_id[b]['pcs']}, key=int),
                      'confidence': 'partial-cfg' if unresolved else 'resolved-static-cfg'})
    # Tarjan SCCs retain irreducible cycles separately from natural loops.
    serial, stack, on_stack, index, low = [0], [], set(), {}, {}
    components = []
    def visit(v):
        index[v] = low[v] = serial[0]
        serial[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in successors[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = set()
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.add(w)
                if w == v:
                    break
            components.append(component)
    for b in by_id:
        if b not in index:
            visit(b)
    for component in components:
        if len(component) < 2 and not any(b in successors[b] for b in component):
            continue
        # A reducible SCC has a member dominating the entire region.
        reducible = component <= reachable and any(all(h in dom[n] for n in component) for h in component)
        if not reducible:
            members = sorted(component, key=lambda b: int(by_id[b]['start']))
            loops.append({'id': f'{function_id}:cycle{by_id[members[0]]["start"]}', 'kind': 'irreducible',
                          'header': None, 'blocks': members, 'latches': [], 'children': [], 'parent': None,
                          'pcs': sorted({p for b in members for p in by_id[b]['pcs']}, key=int), 'confidence': 'partial-cfg' if unresolved else 'resolved-static-cfg'})
    for loop in loops:
        enclosing = [other for other in loops if set(loop['blocks']) < set(other['blocks'])]
        if enclosing:
            parent = min(enclosing, key=lambda other: (len(other['blocks']), other['id']))
            loop['parent'] = parent['id']
            parent['children'].append(loop['id'])
    for loop in loops:
        child_pcs = {pc for child in loops if child['id'] in loop['children'] for pc in child['pcs']}
        loop['exclusivePcs'] = [pc for pc in loop['pcs'] if pc not in child_pcs]
    return {'blocks': blocks, 'loops': loops, 'unresolved': unresolved, 'complete': not unresolved}
