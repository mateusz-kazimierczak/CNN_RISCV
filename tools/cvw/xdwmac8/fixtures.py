"""Self-checking bank hazards and precise exception/context fixtures."""
from tools.cvw.xqmac8.test import envelope
from tools.xdwmac8.contract import NAMES,encode,oracle


def word(name,**operands):return f'.word {encode(name,**operands)}'


def hazards():
    counts=dict.fromkeys(NAMES,0)
    code=[]
    lanes=[0]*8
    def op(name,**kw):
        code.append(word(name,**kw));counts[name]+=1
    def check():
        for i in range(4):
            op(f'xdwget{i}',rd=10)
            code.extend([f'li a1,0x{lanes[2*i]|(lanes[2*i+1]<<32):x}','bne a0,a1,fail'])
    # Back-to-back full-bank forwarding and pair isolation.
    for i in range(4):
        v=((0x80000000+i)<<32)|(0x7fffffff-i)
        code.append(f'li t0,0x{v:x}');op(f'xdwset{i}',rs1=5)
        lanes[2*i:2*i+2]=[v&0xffffffff,v>>32]
    code+=['li t0,0x8080808080808080','li t1,0x7f7f7f7f7f7f7f7f']
    for _ in range(64):op('xdwmac8',rs1=5,rs2=6);lanes=oracle(lanes,0x8080808080808080,0x7f7f7f7f7f7f7f7f)
    check()
    code+=['la s0,source','li s1,1','li s2,0x0101010101010101','csrw mscratch,s2']
    # Inputs from ALU, load, MDU, CSR, and post-increment primary/base paths.
    producers=['add t0,s2,zero','addi t0,s2,0','ld t0,0(s0)','mul t0,s2,s1','divu t0,s2,s1','csrr t0,mscratch']
    for gap in (0,1):
        for source in producers:
            code.append(source);code+=['nop']*gap
            op('xdwset1',rs1=5);lanes[2:4]=[0x01010101,0x01010101]
            code.append(source);code+=['nop']*gap
            op('xdwmac8',rs1=5,rs2=5);lanes=oracle(lanes,0x0101010101010101,0x0101010101010101)
            check()
    # A get result forwarded into both GPR sources and to the old-rd Xqmac8 port.
    for gap in (0,1):
        op('xdwget2',rd=5);v=lanes[4]|(lanes[5]<<32)
        code+=['nop']*gap;op('xdwset3',rs1=5);lanes[6:8]=[v&0xffffffff,v>>32]
        op('xdwget0',rd=5);v=lanes[0]|(lanes[1]<<32)
        code+=['nop']*gap;op('xdwmac8',rs1=5,rs2=5);lanes=oracle(lanes,v,v)
        check()
    # Postinc old-base destination is a real dependency of both bank operands.
    from tools.xpostinc.contract import encode as pi
    code+=['mv t0,s0',f'.word {pi("xldpi",6,5,8)}']
    op('xdwset0',rs1=5)
    op('xdwget0',rd=10)
    code+=['addi a1,s0,8','bne a0,a1,fail']
    # Primary postinc value, then immediately a MAC consuming it.
    code+=['mv t0,s0',f'.word {pi("xldpi",6,5,8)}']
    op('xdwset0',rs1=6)
    op('xdwget0',rd=10);code+=['bne a0,s2,fail']
    # A predicted/not-taken branch must not run either younger bank mutation.
    op('xdwset0');lanes[:2]=[0,0]
    code+=['beq zero,zero,taken',word('xdwmac8',rs1=18,rs2=18),word('xdwset0',rs1=18),'taken:']
    op('xdwget0',rd=10);code+=['bnez a0,fail','j pass']
    text=envelope('\n'.join(code))+'\n.section .data\n.balign 8\nsource: .dword 0x0101010101010101\n'
    return text,dict(bank=counts,postload=2)


def trap(word_value, *, xlen=64, bank=True, cause=2, fault_setup='', tval=None, younger='mac'):
    counts=dict.fromkeys(NAMES,0)
    code=['la s0,handler','csrw mtvec,s0','li t0,42','li t1,0x40000000']
    if bank:
        for i in range(4):
            code+=[f'li t2,{i+123}',word(f'xdwset{i}',rs1=7)]
            counts[f'xdwset{i}']+=1
    code+=['la s0,fault',f'li s1,{word_value}',fault_setup,'fault:',f'.word {word_value}']
    code+=[word('xdwmac8',rs1=5,rs2=5) if younger=='mac' else word('xdwset0',rs1=5),'j fail','.balign 4','handler:',
           'li a0,3','csrr t3,mcause',f'li t4,{cause}','bne t3,t4,exit','csrr t3,mepc','bne t3,s0,exit',
           'csrr t3,mtval',f'li t4,{word_value if tval is None else tval}','bne t3,t4,exit','li t4,42','bne t0,t4,exit']
    if bank:
        for i in range(4):
            code+=[word(f'xdwget{i}',rd=5),f'li t4,{i+123}','bne t0,t4,exit'];counts[f'xdwget{i}']+=1
    code+=['j pass']
    return envelope('\n'.join(code),xlen),dict(bank=counts,traps=1)


def interrupt(operation):
    # Save all bank state, emulate a nested bank user, restore and reexecute the
    # interrupted mutation. A premature or duplicate update is observable.
    counts=dict.fromkeys(NAMES,0)
    code=['la s0,handler','csrw mtvec,s0','li t0,0x0101010101010101','la s1,saved']
    for i in range(4):code+=[word(f'xdwset{i}')];counts[f'xdwset{i}']+=1
    code+=['li t1,128','csrw mie,t1','csrsi mstatus,8','target:',word(operation,**({'rs1':5,'rs2':5} if operation=='xdwmac8' else {'rs1':5}))]
    counts[operation]+=1
    for i in range(4):
        expected=(1<<32)|1 if operation=='xdwmac8' else 0x0101010101010101 if i==2 else 0
        code+=[word(f'xdwget{i}',rd=6),f'li t2,{expected}','bne t1,t2,fail'];counts[f'xdwget{i}']+=1
    code+=['j pass','.balign 4','handler:','csrr t1,mcause','li t2,0x8000000000000007','bne t1,t2,fail','csrr t1,mepc','la t2,target','bne t1,t2,fail']
    for i in range(4):
        code+=[word(f'xdwget{i}',rd=6),'bnez t1,fail',f'sd t1,{8*i}(s1)',word(f'xdwset{i}',rs1=5)]
        counts[f'xdwget{i}']+=1;counts[f'xdwset{i}']+=1
    for i in range(4):
        code+=[f'ld t1,{8*i}(s1)',word(f'xdwset{i}',rs1=6)];counts[f'xdwset{i}']+=1
    code+=['mret']
    return envelope('\n'.join(code))+'\n.section .data\n.balign 8\nsaved: .zero 32\n',dict(bank=counts,traps=1)


def privilege(mode):
    # Bare translation with permissive PMP, bank use in S/U followed by ecall.
    counts=dict.fromkeys(NAMES,0)
    code=['la t0,handler','csrw mtvec,t0','li t0,-1','csrw pmpaddr0,t0','li t0,15','csrw pmpcfg0,t0',
          'li t0,0x1800','csrc mstatus,t0']
    if mode=='s':code+=['li t0,0x800','csrs mstatus,t0']
    code+=['la t0,lower','csrw mepc,t0','mret','lower:','li t0,0x0101010101010101',word('xdwset0',rs1=5),word('xdwmac8',rs1=5,rs2=5),'ecall','j fail','.balign 4','handler:','csrr t0,mcause',f'li t1,{9 if mode=="s" else 8}','bne t0,t1,fail',word('xdwget0',rd=5),'li t1,0x0101010201010102','bne t0,t1,fail','j pass']
    counts['xdwset0']=counts['xdwmac8']=counts['xdwget0']=1
    return envelope('\n'.join(code)),dict(bank=counts,traps=1)
