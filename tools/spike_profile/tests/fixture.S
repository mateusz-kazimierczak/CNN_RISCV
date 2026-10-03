/* Hand-countable regions: allocate=2; invoke=27; operator=20.
 * SERIALIZE adds one retired CSR instruction (Spike executes it twice).
 * TRAP adds an unretired ecall plus four retired trap-handler instructions.
 */
.option norelax
.option norvc
.section .text.init
.globl _start
_start:
  la sp, __stack_top
  la a1, sample
#ifdef TRAP
  la t4, trap_handler
  csrw mtvec, t4
#endif
  call allocate
  call invoke
  la t0, tohost
  li t1, 1
  sd t1, 0(t0)
1: j 1b

.section .text
.globl allocate, invoke, toy_operator
.type allocate,@function
allocate:
  .option push
  .option rvc
  c.li a0, 0
  c.jr ra
  .option pop
.size allocate,.-allocate

.type invoke,@function
invoke:
  addi sp, sp, -16
  sd ra, 8(sp)
  jal ra, toy_operator
  ld ra, 8(sp)
  addi sp, sp, 16
  addi a0, zero, 0
  jalr zero, 0(ra)
.size invoke,.-invoke

.type toy_operator,@function
toy_operator:
#ifdef SERIALIZE
  csrr t4, minstret
#endif
#ifdef TRAP
  ecall
#endif
  addi t0, zero, 3
loop:
  lb t1, 0(a1)
  mul t2, t1, t0
  div t3, t2, t0
  addiw t0, t0, -1
  bne t0, zero, loop
  .option push
  .option rvc
  c.nop
  .option pop
  jal zero, tail_helper
.size toy_operator,.-toy_operator

.type tail_helper,@function
tail_helper:
  .option push
  .option rvc
  c.li a0, 0
  c.jr ra
  .option pop
.size tail_helper,.-tail_helper

#ifdef TRAP
.balign 4
.type trap_handler,@function
trap_handler:
  csrr t4, mepc
  addi t4, t4, 4
  csrw mepc, t4
  mret
.size trap_handler,.-trap_handler
#endif

.section .data
sample: .byte -5
.section .tohost,"aw",@progbits
.balign 8
.globl tohost
tohost: .dword 0
.section .fromhost,"aw",@progbits
.balign 8
.globl fromhost
fromhost: .dword 0
