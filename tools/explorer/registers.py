"""Export conservative, address-scoped DWARF register/variable locations.

Location lists describe program state BEFORE the instruction at a PC executes.
Only direct register values, simple memory addresses, and register pieces are
reported. Bounded memory-value expressions are retained symbolically, never
evaluated. Entry values and expressions requiring execution history are omitted.
"""
from __future__ import annotations
import bisect
from pathlib import Path
import re


def inherited(die, name, seen=None):
    seen = set() if seen is None else seen
    if die.offset in seen:
        return None, None
    seen.add(die.offset)
    if name in die.attributes:
        return die.attributes[name], die
    for key in ('DW_AT_abstract_origin', 'DW_AT_specification'):
        if key in die.attributes:
            found, owner = inherited(die.get_DIE_from_attribute(key), name, seen)
            if found is not None:
                return found, owner
    return None, None


def text(attribute, fallback=''):
    if attribute is None:
        return fallback
    value = attribute.value
    return value.decode(errors='replace') if isinstance(value, bytes) else str(value)


def intersection(a, b):
    return [(max(lo, x), min(hi, y)) for lo, hi in a for x, y in b if max(lo, x) < min(hi, y)]


def supported_registers(ops):
    """Return only location expressions whose register role is unambiguous."""
    if len(ops) == 1:
        op = ops[0]
        match = re.fullmatch(r'DW_OP_reg(\d+)', op.op_name)
        reg = int(match[1]) if match else (op.args[0] if op.op_name == 'DW_OP_regx' else None)
        if reg is not None and 0 <= reg < 32:
            return [(f'x{reg}', 'value', 'Variable value is held in this register.')]
        match = re.fullmatch(r'DW_OP_breg(\d+)', op.op_name)
        reg = int(match[1]) if match else (op.args[0] if op.op_name == 'DW_OP_bregx' else None)
        if reg is not None and 0 <= reg < 32:
            offset = op.args[-1]
            return [(f'x{reg}', 'address', f'Variable is in memory at this register {offset:+d}; the register holds its address, not its value.')]
    # Composite variables can occupy several registers. Keep byte offsets explicit.
    if ops and len(ops) % 2 == 0:
        result, offset = [], 0
        for i in range(0, len(ops), 2):
            register, piece = ops[i:i + 2]
            match = re.fullmatch(r'DW_OP_reg(\d+)', register.op_name)
            reg = int(match[1]) if match else (register.args[0] if register.op_name == 'DW_OP_regx' else None)
            if reg is None or not 0 <= reg < 32 or piece.op_name != 'DW_OP_piece':
                return []
            size = piece.args[0]
            if size > 0:
                result.append((f'x{reg}', 'piece', f'Holds {size} bytes of the variable at byte offset {offset}; not the complete variable.'))
            offset += size
        return result
    return []


def symbolic_memory_value(ops, address_bits=64):
    """Recognize a register-relative load, optionally explicitly sign extended.

    DW_OP_stack_value is required: this is a relationship to a variable's value,
    not a claim that its address base register holds the named variable.
    """
    if not 3 <= len(ops) <= 10 or ops[-1].op_name != 'DW_OP_stack_value':
        return None
    base = ops[0]
    match = re.fullmatch(r'DW_OP_breg(\d+)', base.op_name)
    reg = int(match[1]) if match else base.args[0] if base.op_name == 'DW_OP_bregx' else None
    if reg is None or not 0 <= reg < 32:
        return None
    offset, index = base.args[-1], 1
    if ops[index].op_name == 'DW_OP_plus_uconst':
        offset += ops[index].args[0]
        index += 1
    if index >= len(ops) or ops[index].op_name != 'DW_OP_deref_size' or ops[index].args[0] not in (1, 2, 4, 8):
        return None
    size = ops[index].args[0]
    rest = ops[index + 1:-1]
    signed = False
    if rest:
        def constant(op):
            match = re.fullmatch(r'DW_OP_lit(\d+)', op.op_name)
            return int(match[1]) if match else op.args[0] if op.op_name in {'DW_OP_constu', 'DW_OP_consts', 'DW_OP_const1u', 'DW_OP_const1s', 'DW_OP_const2u', 'DW_OP_const2s', 'DW_OP_const4u', 'DW_OP_const4s', 'DW_OP_const8u', 'DW_OP_const8s'} else None
        if len(rest) != 4 or rest[1].op_name != 'DW_OP_shl' or rest[3].op_name != 'DW_OP_shra':
            return None
        if constant(rest[0]) != address_bits - size * 8 or constant(rest[2]) != address_bits - size * 8:
            return None
        signed = True
    return {'register': f'x{reg}', 'offset': str(offset), 'bytes': size, 'signed': signed}


def extract_registers(elf_path: Path, pcs: list[int], elf_hash: str, root: Path):
    from elftools.elf.elffile import ELFFile
    from elftools.dwarf.descriptions import describe_form_class, describe_DWARF_expr
    from elftools.dwarf.dwarf_expr import DWARFExprParser
    from elftools.dwarf.locationlists import LocationParser
    from elftools.common.exceptions import DWARFError, ELFError

    result = {'schemaVersion': 1, 'elfHash': elf_hash, 'semantics': 'before-instruction',
              'variables': {}, 'locations': {}, 'relations': {}, 'coverage': {'compilationUnits': 0, 'supportedLocations': 0, 'symbolicRelations': 0, 'unsupportedExpressions': 0, 'skippedScopes': 0}}
    pcs = sorted(pcs)
    def has_code(ranges):
        return any((i := bisect.bisect_left(pcs, lo)) < len(pcs) and pcs[i] < hi for lo, hi in ranges)
    with elf_path.open('rb') as stream:
        elf = ELFFile(stream)
        if not elf.has_dwarf_info():
            return result
        dwarf = elf.get_dwarf_info()
        aranges = dwarf.get_aranges()
        eligible = {entry.info_offset for entry in aranges.entries if entry.length and has_code([(entry.begin_addr, entry.begin_addr + entry.length)])} if aranges else None
        locations = LocationParser(dwarf.location_lists())
        expression_parser = DWARFExprParser(dwarf.structs)
        for cu in dwarf.iter_CUs():
            if eligible is not None and cu.cu_offset not in eligible:
                continue
            result['coverage']['compilationUnits'] += 1
            top = cu.get_top_DIE()
            base = top.attributes.get('DW_AT_low_pc')
            base = base.value if base else 0
            line_program = dwarf.line_program_for_CU(cu)

            def ranges_for(die):
                if 'DW_AT_ranges' in die.attributes:
                    current_base, ranges = base, []
                    for entry in dwarf.range_lists().get_range_list_at_offset(die.attributes['DW_AT_ranges'].value, cu=cu):
                        if hasattr(entry, 'base_address'):
                            current_base = entry.base_address
                        else:
                            add = 0 if entry.is_absolute else current_base
                            if entry.begin_offset + add < entry.end_offset + add:
                                ranges.append((entry.begin_offset + add, entry.end_offset + add))
                    return ranges
                low, high = die.attributes.get('DW_AT_low_pc'), die.attributes.get('DW_AT_high_pc')
                if low is not None and high is not None:
                    end = high.value if describe_form_class(high.form) == 'address' else low.value + high.value
                    return [(low.value, end)] if end > low.value else []
                return None

            def type_name(die, seen=None):
                seen = set() if seen is None else seen
                if die is None or die.offset in seen:
                    return 'unknown type'
                seen.add(die.offset)
                named, _ = inherited(die, 'DW_AT_name')
                if named is not None:
                    return text(named)
                typ, owner = inherited(die, 'DW_AT_type')
                target = owner.get_DIE_from_attribute('DW_AT_type') if typ else None
                suffix = {'DW_TAG_pointer_type': ' *', 'DW_TAG_reference_type': ' &', 'DW_TAG_rvalue_reference_type': ' &&', 'DW_TAG_array_type': '[]'}
                if die.tag in suffix:
                    return (type_name(target, seen) if target else 'void') + suffix[die.tag]
                qualifier = {'DW_TAG_const_type': 'const ', 'DW_TAG_volatile_type': 'volatile '}.get(die.tag, '')
                return qualifier + type_name(target, seen) if target else 'unknown type'

            def declaration(die):
                file_attr, owner = inherited(die, 'DW_AT_decl_file')
                line_attr, _ = inherited(die, 'DW_AT_decl_line')
                if file_attr is None or line_attr is None or not line_program or line_attr.value <= 0:
                    return None
                # Imported abstract origins may belong to a different CU.
                lp = line_program if owner.cu is cu else dwarf.line_program_for_CU(owner.cu)
                if not lp:
                    return None
                v5 = lp.header.version >= 5
                index = file_attr.value if v5 else file_attr.value - 1
                files = lp.header.file_entry
                if index < 0 or index >= len(files):
                    return None
                entry = files[index]
                filename = Path(entry.name.decode(errors='replace'))
                if not filename.is_absolute():
                    directories = lp.header.include_directory
                    directory_index = entry.dir_index if v5 else entry.dir_index - 1
                    directory = Path(directories[directory_index].decode(errors='replace')) if 0 <= directory_index < len(directories) else Path(text(owner.cu.get_top_DIE().attributes.get('DW_AT_comp_dir')))
                    filename = directory / filename
                if not filename.is_absolute():
                    filename = Path(text(owner.cu.get_top_DIE().attributes.get('DW_AT_comp_dir'))) / filename
                filename = filename.resolve()
                path = str(filename.relative_to(root)) if filename.is_relative_to(root) else str(filename)
                return {'file': path, 'line': int(line_attr.value)}

            def variable(die, scope, function):
                name, _ = inherited(die, 'DW_AT_name')
                location = die.attributes.get('DW_AT_location')
                if name is None or location is None or 'DW_AT_start_scope' in die.attributes:
                    return
                parsed = locations.parse_from_attribute(location, cu['version'], die=die)
                entries = []
                if isinstance(parsed, list):
                    current_base, explicit, defaults = base, [], []
                    for entry in parsed:
                        if hasattr(entry, 'base_address'):
                            current_base = entry.base_address
                        elif entry.begin_offset == -1 and entry.end_offset == -1:
                            defaults.append(entry.loc_expr)
                        else:
                            add = 0 if entry.is_absolute else current_base
                            lo, hi = entry.begin_offset + add, entry.end_offset + add
                            explicit.append((lo, hi))
                            entries.extend((a, b, entry.loc_expr) for a, b in intersection(scope, [(lo, hi)]))
                    # Default locations apply only outside explicit location-list ranges.
                    if defaults:
                        remainder = list(scope)
                        for lo, hi in explicit:
                            remainder = [(x, min(y, lo)) for x, y in remainder if x < lo and x < min(y, lo)] + [(max(x, hi), y) for x, y in remainder if y > hi and max(x, hi) < y]
                        for expr in defaults:
                            entries.extend((lo, hi, expr) for lo, hi in remainder)
                else:
                    entries = [(lo, hi, parsed.loc_expr) for lo, hi in scope]
                for lo, hi, expr in entries:
                    if not has_code([(lo, hi)]):
                        continue
                    ops = expression_parser.parse_expr(expr)
                    roles = supported_registers(ops)
                    relation = symbolic_memory_value(ops, elf.elfclass) if not roles else None
                    if not roles and relation is None:
                        result['coverage']['unsupportedExpressions'] += 1
                        continue
                    key = f'v{die.offset:x}'
                    if key not in result['variables']:
                        typ, owner = inherited(die, 'DW_AT_type')
                        result['variables'][key] = {'id': key, 'name': text(name), 'type': type_name(owner.get_DIE_from_attribute('DW_AT_type')) if typ else 'unknown type',
                                                    'function': function, 'kind': 'parameter' if die.tag == 'DW_TAG_formal_parameter' else 'local', 'declaration': declaration(die)}
                    expression = describe_DWARF_expr(expr, dwarf.structs)
                    if relation:
                        reg = relation.pop('register')
                        result['relations'].setdefault(reg, []).append({**relation, 'variableId': key, 'low': str(lo), 'high': str(hi), 'expression': expression})
                        result['coverage']['symbolicRelations'] += 1
                    for reg, kind, description in roles:
                        result['locations'].setdefault(reg, []).append({'variableId': key, 'low': str(lo), 'high': str(hi), 'kind': kind, 'description': description, 'expression': expression})
                        result['coverage']['supportedLocations'] += 1

            def children(die, scope, function):
                for child in die.iter_children():
                    if child.tag in {'DW_TAG_variable', 'DW_TAG_formal_parameter'}:
                        variable(child, scope, function)
                    elif child.tag in {'DW_TAG_lexical_block', 'DW_TAG_inlined_subroutine'}:
                        own = ranges_for(child)
                        # An inline instance without code ranges is not addressable evidence.
                        if own is None and child.tag == 'DW_TAG_inlined_subroutine':
                            continue
                        active = intersection(scope, own) if own is not None else scope
                        if active and has_code(active):
                            name, _ = inherited(child, 'DW_AT_name')
                            children(child, active, text(name, function) if child.tag == 'DW_TAG_inlined_subroutine' else function)

            for die in cu.iter_DIEs():
                if die.tag != 'DW_TAG_subprogram':
                    continue
                try:
                    scope = ranges_for(die)
                    if scope and has_code(scope):
                        name, _ = inherited(die, 'DW_AT_name')
                        children(die, scope, text(name, 'unnamed function'))
                except (DWARFError, ELFError, KeyError, ValueError, NotImplementedError):
                    result['coverage']['skippedScopes'] += 1
    for entries in result['locations'].values():
        entries.sort(key=lambda item: (int(item['low']), int(item['high']), item['variableId']))
    for entries in result['relations'].values():
        entries.sort(key=lambda item: (int(item['low']), int(item['high']), item['variableId']))
    return result
