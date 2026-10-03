OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
  /* Address-space provision for Spike; not measured application RAM usage. */
  RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 128M
}

PHDRS {
  /* Explicit segment permissions avoid a combined writable/executable LOAD. */
  text PT_LOAD FLAGS(5);
  data PT_LOAD FLAGS(6);
}

SECTIONS {
  . = ORIGIN(RAM);

  .text : ALIGN(16) {
    KEEP(*(.text.init))
    *(.text .text.*)
  } > RAM :text

  .rodata : ALIGN(16) {
    *(.srodata .srodata.*)
    *(.rodata .rodata.*)
  } > RAM :text

  .data : ALIGN(16) {
    *(.data .data.*)
    *(.sdata .sdata.*)
  } > RAM :data

  .htif : ALIGN(4096) {
    /* Spike locates these mailbox symbols in the ELF. Retain them under GC. */
    KEEP(*(.tohost))
    KEEP(*(.fromhost))
  } > RAM :data

  .bss (NOLOAD) : ALIGN(16) {
    __bss_start = .;
    *(.sbss .sbss.*)
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(16);
    __bss_end = .;
  } > RAM :data

  __global_pointer$ = ADDR(.data) + 0x800;
  /* Newlib's optional heap grows upward; the stack has a separate reservation. */
  __heap_start = ALIGN(16);
  __stack_top = ORIGIN(RAM) + LENGTH(RAM);
  __stack_bottom = __stack_top - 1M;
  __heap_end = __stack_bottom;

  /DISCARD/ : {
    *(.comment)
    *(.note .note.*)
  }
}
