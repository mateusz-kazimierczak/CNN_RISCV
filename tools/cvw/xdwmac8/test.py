#!/usr/bin/env python3
"""Verify the depthwise bank on real Wally cores, then run an original X4 ELF."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools.cvw.prepare_xdwmac8 import prepare
from tools.cvw.xdwmac8.runtime import WORK,OVERLAY,PREFIX,build,compile_program,execute,image,run,digest
from tools.cvw.xdwmac8 import fixtures
from tools.cvw.xqmac8 import test as qmac
from tools.cvw.xrequant import test as req
from tools.cvw.xpostinc import test as post
from tools.xdwmac8.contract import NAMES,encode


def bank_unit(jobs):
    import shutil,os
    output=WORK/'unit';output.mkdir(parents=True,exist_ok=True)
    command=[shutil.which('verilator'),'--binary','--timing','--assert','-Wno-fatal','-j',str(jobs),'--top-module','bank_tb','--Mdir',output,ROOT/'rtl/cvw/xdwmac8.sv',ROOT/'tools/cvw/xdwmac8/bank_tb.sv',ROOT/'.deps/cvw/src/generic/flop/flopenrc.sv']
    env=dict(os.environ)
    if sys.platform=='darwin':
        env['SDKROOT']='/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk'
        command+=['-MAKEFLAGS','CXX=/Library/Developer/CommandLineTools/usr/bin/clang++ LINK=/Library/Developer/CommandLineTools/usr/bin/clang++']
    run(command,WORK/'unit-build.log',env=env)
    binary=output/'Vbank_tb'
    text=run([binary],WORK/'unit.log')
    if 'XDWMAC8_BANK_UNIT_PASS' not in text:raise ValueError('unit test incomplete')
    return {'status':'PASS','simulator_sha256':digest(binary),'log_sha256':digest(WORK/'unit.log'),'command':list(map(str,command))}


def replay(pointer,binary):
    from tools.investigation.replay import verify_replay
    directory,_,workload,rows=verify_replay(pointer)
    if workload['configuration']!='X4':raise ValueError('requires verified X4 replay')
    bank={name:sum(f.get('expected_xdwmac8_instructions',{}).get(name,0) for f in workload['fixtures']) for name in NAMES}
    counts={key:sum(f.get(field,0) for f in workload['fixtures']) for key,field in [('qmac','expected_xqmac8_instructions'),('requant','expected_xrequant_instructions')]}
    for key,kind in [('postload','load'),('poststore','store')]:
        counts[key]=sum(int(row['unit'].get('postincrement',{}).get(kind,{}).get('value',0)) for row in rows)
    elf=directory/json.loads((directory/'rv64/build.json').read_text())['binary']
    result=execute('compiler-kernel-replay',binary,elf,bank=bank,**counts,timeout=7200)
    text=(WORK/'compiler-kernel-replay.log').read_text()
    actual=[json.loads(line) for line in text.splitlines() if line.startswith('{"fixture":')]
    if len(actual)!=len(workload['fixtures']) or 'compiler replay: PASS' not in text:raise ValueError('incomplete replay')
    for i,(row,f) in enumerate(zip(actual,workload['fixtures'])):
        if row!={'fixture':i,'status':f['expected_status'],'guards':True,'bytes_compared':f['output']['bytes'],'first_difference':None}:raise ValueError(f'replay mismatch {i}')
    return result,{'artifact_id':directory.name,'fixtures':len(rows),'nodes':workload['nodes'],'cases':workload['cases'],'elf_sha256':digest(elf),'bank_counts':bank,'counts':counts,'complete_output_bytes_compared':sum(r['bytes_compared'] for r in actual)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs',type=int,default=8)
    parser.add_argument('--compiler-replay',type=Path)
    args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    integration=prepare(ROOT/'.deps/cvw',OVERLAY)
    built={name:build(name,args.jobs) for name in integration['configurations']}
    enabled=built['arch_project_xdwmac8'][0]
    unit=bank_unit(args.jobs)
    results={}
    handoff=ROOT/'build/xdwmac8/tests';proof=json.loads((handoff/'verification.json').read_text())
    if proof['status']!='PASS' or proof['elf_sha256']!=digest(handoff/'vectors.elf') or proof['vectors_sha256']!=digest(handoff/'vectors.json'):raise ValueError('invalid Spike handoff')
    for config in ('arch_project_xdwmac8','arch_project_xdwmac8_only'):
        for stall in (0,31):
            name=config+'-vectors'+('-stalled' if stall else '')
            results[name]=execute(name,built[config][0],handoff/'vectors.elf',bank=proof['counts'],stall=stall)
    program,counts=fixtures.hazards();elf=compile_program('hazards',program)
    for stall in (0,31):
        name='hazards'+('-stalled' if stall else '')
        results[name]=execute(name,enabled,elf,**counts,stall=stall)
        for key in ('bank_forward','dw_forward_m','dw_forward_w','dw_load','dw_mdu','dw_csr','base_a_m'):
            if not results[name]['metrics'][key]:raise ValueError(f'hazard coverage absent {key}')
    reserved=[0x208b,0x0200200b,0x0800300b,0x0010300b,0x308b,0x0800400b,0xc00b,0x0010400b]
    for i,value in enumerate(reserved):
        program,counts=fixtures.trap(value);elf=compile_program(f'reserved-{i}',program)
        for stall in (0,31):
            name=f'reserved-{i}'+('-stalled' if stall else '')
            results[name]=execute(name,enabled,elf,**counts,stall=stall)
    for config in ('arch_project_xdwmac8_off','arch_project_xdwmac8_rv32'):
        xlen=32 if config.endswith('rv32') else 64
        for op in NAMES:
            value=encode(op,**({'rs1':5,'rs2':6} if op=='xdwmac8' else {'rs1':5} if op.startswith('xdwset') else {'rd':5}))
            program,counts=fixtures.trap(value,xlen=xlen,bank=False)
            name=config+'-'+op;elf=compile_program(name,program,xlen)
            results[name]=execute(name,built[config][0],elf,xlen=xlen,**counts)
    for value in (0x0000000b,0x0000100b,0x0000002b,0x0000007b):
        program,counts=fixtures.trap(value);name=f'bank-only-illegal-{value:08x}';elf=compile_program(name,program)
        results[name]=execute(name,built['arch_project_xdwmac8_only'][0],elf,**counts)
    # Older memory faults, ecall and invalid descriptors squash pending bank ops.
    for kind,value,cause,tval,setup in [
        ('load',0x00033283,5,0x40000000,''),
        ('store',0x00533023,7,0x40000000,''),
        ('ecall',0x73,11,0,''),
        ('descriptor',0x0073128b,2,0x0073128b,'li t2,-1'),
    ]:
        for younger in ('mac','set'):
            name='fault-'+kind+'-'+younger
            program,counts=fixtures.trap(value,cause=cause,tval=tval,fault_setup=setup,younger=younger)
            elf=compile_program(name,program)
            results[name]=execute(name,enabled,elf,**counts,stall=31)
    for operation in ('xdwmac8','xdwset2'):
        program,counts=fixtures.interrupt(operation);elf=compile_program('irq-'+operation,program);_,symbols=image(elf,64)
        for stall in (0,31):
            name='irq-'+operation+('-stalled' if stall else '')
            results[name]=execute(name,enabled,elf,**counts,irq_pc=symbols['target'],stall=stall)
            if not results[name]['metrics']['bank_trap']:raise ValueError('bank M-stage interrupt suppression absent')
    for mode in ('s','u'):
        program,counts=fixtures.privilege(mode);name='privilege-'+mode;elf=compile_program(name,program)
        results[name]=execute(name,built['arch_project_xdwmac8_vm'][0],elf,**counts,stall=31)
    for config,(binary,_) in built.items():
        xlen=32 if config.endswith('rv32') else 64;name=config+'-base'
        elf=compile_program(name,qmac.compatibility(xlen,True),xlen)
        results[name]=execute(name,binary,elf,xlen=xlen)
    # The shared multiplier hardware must preserve both older arithmetic ISAs.
    from tools.xqmac8.test import assembly as qasm
    from tools.xqmac8.vectors import vectors as qvec
    from tools.xrequant.test import assembly as rasm,vectors as rvec
    from tools.xpostinc.test import vector_program
    program=qasm(qvec());elf=compile_program('qmac-regression',program)
    results['qmac-regression']=execute('qmac-regression',enabled,elf,qmac=len(qvec()))
    program=rasm(rvec());elf=compile_program('requant-regression',program)
    results['requant-regression']=execute('requant-regression',enabled,elf,requant=len(rvec())+64)
    program,cases,total=vector_program();elf=compile_program('postinc-regression',program)
    from tools.xpostinc.contract import LOADS
    loads=sum(c['name'] in LOADS for c in cases)+8
    results['postinc-regression']=execute('postinc-regression',enabled,elf,postload=loads,poststore=total-loads,stall=31)
    for label,module in [('qmac',qmac),('requant',req),('postinc',post)]:
        program,counts=module.hazards()
        if label=='qmac':counts={'qmac':counts}
        elf=compile_program(label+'-hazards',program)
        results[label+'-hazards']=execute(label+'-hazards',enabled,elf,**counts,stall=31)
    replay_proof=None
    if args.compiler_replay:
        results['compiler-kernel-replay'],replay_proof=replay(args.compiler_replay,enabled)
    for name,sha in integration['files_sha256'].items():
        if digest(OVERLAY/name)!=sha:raise ValueError('overlay changed during tests')
    record={'schema_version':1,'status':'PASS','integration':integration,'builds':{k:v[1] for k,v in built.items()},'unit':unit,'vectors':proof['vectors'],'vector_counts':proof['counts'],'vectors_sha256':digest(handoff/'vectors.json'),'cases':results,'compiler_replay':replay_proof,'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),Path(__file__).with_name('fixtures.py'),ROOT/'tools/cvw/xqmac8/test.py',ROOT/'tools/cvw/xrequant/test.py',ROOT/'tools/cvw/xpostinc/test.py']},'scope':'functional bank RTL on actual Wally SoC; test-program cycles include setup/checks; synthesis timing/area unmeasured'}
    output=ROOT/'results/cvw/xdwmac8';output.mkdir(parents=True,exist_ok=True)
    (output/'verification.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    print('Xdwmac8 RTL suite: PASS',flush=True)

if __name__=='__main__':main()
