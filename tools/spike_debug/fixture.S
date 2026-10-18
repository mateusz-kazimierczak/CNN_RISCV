.option norelax
.option norvc
.section .text.init
.globl _start
_start:
  la sp, __stack_top
#ifdef TRAP
  la t0, trap_handler
  csrw mtvec, t0
#endif
  call allocate
  la a0, graph_state
  call invoke
  la t0, tohost
  li t1, 1
  sd t1, 0(t0)
1: j 1b
.section .text
.globl invoke, allocate, graph_enter, toy_operator, loop, trap_instruction, trap_handler, helper
allocate: ret
invoke:
  addi sp,sp,-16
  sd ra,8(sp)
  call graph_enter
  la s1,graph_state
  sw zero,0(s1)
.globl before_operator
before_operator:
  call toy_operator
  li t5,1
  sw t5,0(s1)
  call toy_operator
  li t5,2
  sw t5,0(s1)
  call toy_operator
  ld ra,8(sp)
  addi sp,sp,16
#ifdef BADSTATUS
  li a0,2
#else
  li a0,0
#endif
  ret
graph_enter: ret
toy_operator:
#ifdef TAIL
  tail helper
#endif
  addi sp,sp,-16
#ifdef FOREVER
1: j 1b
#endif
  sd ra,8(sp)
#ifdef SERIALIZE
  csrr t4,minstret
#endif
#ifdef TRAP
trap_instruction: ecall
#endif
#ifdef WAIT
  wfi
#endif
  li t0,3
loop:
  addi t0,t0,-1
  bne t0,zero,loop
  .option push
  .option rvc
  c.li a0,7
  .option pop
  call helper
  ld ra,8(sp)
  addi sp,sp,16
  ret
helper:
  addi a0,a0,1
  ret
.balign 4
trap_handler:
  csrr t4,mepc
  addi t4,t4,4
  csrw mepc,t4
  mret
.section .data
.balign 8
.globl graph_state
graph_state: .word 0,0
.balign 4096
.space 4094
.globl cross_page
cross_page: .byte 0xab,0xcd,0xef,0x12,0x34,0x56
.section .tohost,"aw",@progbits
.balign 8
.globl tohost
tohost: .dword 0
.section .fromhost,"aw",@progbits
.balign 8
.globl fromhost
fromhost: .dword 0
