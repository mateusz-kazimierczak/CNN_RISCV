  .section .text.init
  .globl _start
  .type _start, @function
_start:
  # Keep gp initialization independent of linker relaxation, which may itself
  # rewrite address calculations to use gp. Spike has already loaded .data.
  .option push
  .option norelax
  la gp, __global_pointer$
  .option pop
  la sp, __stack_top

  # Satisfy the C/C++ zero-initialization contract.
  la t0, __bss_start
  la t1, __bss_end
1:
  bgeu t0, t1, 2f
  sd zero, 0(t0)
  addi t0, t0, 8
  j 1b
2:
  call main
  # a0 holds main's status; report it to Spike through the HTIF exit request.
  call platform_exit
3:
  wfi
  j 3b
  .size _start, .-_start
