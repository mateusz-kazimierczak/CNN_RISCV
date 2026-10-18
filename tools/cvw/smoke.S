# Directed bring-up: RV64 multiplication, compressed instructions, RAM, loops,
# calls/returns and two acknowledged HTIF console stores before clean exit.
.option rvc
.option norelax
.section .text.init
.globl _start
_start:
  la sp, __stack_top
  call smoke_invoke
.globl smoke_return
smoke_return:
  bnez a0, fail
  # Fill an unaligned output range outside the hand-counted invocation. Its
  # dirty cache lines exercise the same coherent host dump used for B0/B1.
  la t4, fixture_output_pointer
.globl smoke_output_pointer_load
smoke_output_pointer_load:
  ld a4, 0(t4)
  mv t2, a4
  li t0, 0
  li t1, 1000
7: xori t3, t0, 0x5a
  sb t3, 0(t2)
  addi t2, t2, 1
  addi t0, t0, 1
  blt t0, t1, 7b
  la s0, tohost
  li s1, 0x0101000000000000
  li t0, 'O'
  or t0, t0, s1
  sd t0, 0(s0)
1: ld t0, 0(s0)
  bnez t0, 1b
  li t0, 'K'
  or t0, t0, s1
  sd t0, 0(s0)
2: ld t0, 0(s0)
  bnez t0, 2b
  li t0, 1
  sd t0, 0(s0)
3: j 3b
fail:
  la s0, tohost
  li t0, 3
  sd t0, 0(s0)
4: j 4b
.globl smoke_invoke
.type smoke_invoke, @function
smoke_invoke:
  li t0, -7
  li t1, 9
  mul t2, t0, t1
  li t3, -63
  bne t2, t3, 6f
  la t4, scratch
  sd t2, 0(t4)
  ld t5, 0(t4)
  bne t5, t3, 6f
  li t0, 3
5: addi t0, t0, -1
  bnez t0, 5b
  li a0, 0
  ret
6: li a0, 1
  ret
.size smoke_invoke, .-smoke_invoke
.section .data
.balign 8
scratch: .quad 0
fixture_output_pointer: .quad fixture_output
.zero 3
fixture_output: .zero 1000
.section .tohost,"aw"
.balign 8
.globl tohost
tohost: .quad 0
.globl fromhost
fromhost: .quad 0
