OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
  RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 128M
}

PHDRS {
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
  __heap_start = ALIGN(16);
  __stack_top = ORIGIN(RAM) + LENGTH(RAM);
  __stack_bottom = __stack_top - 1M;
  __heap_end = __stack_bottom;

  /DISCARD/ : {
    *(.comment)
    *(.note .note.*)
  }
}
