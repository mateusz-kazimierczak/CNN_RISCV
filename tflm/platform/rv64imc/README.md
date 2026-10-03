# RV64IMC platform support

This directory supplies the platform-specific code needed to run TFLM in
Spike as a bare-metal program. The application is shared with the native
build; see [the runtime guide](../../README.md) and
[the project guide](../../../README.md) for build commands.

## File map

| File | Responsibility |
|---|---|
| [rv64imc_makefile.inc](rv64imc_makefile.inc) | Cross compiler, `rv64imc`/`lp64` flags, startup/link options, math library |
| [crt0.S](crt0.S) | ELF entry point `_start`: initialize `gp`/`sp`, clear BSS, call `main()`, report exit |
| [link.ld](link.ld) | Code/data placement and symbols for BSS, heap, stack, and HTIF |
| [syscalls.cc](syscalls.cc) | Spike console/exit transport and minimal newlib system calls |
| [debug_log.cc](debug_log.cc) | Format TFLM logs and send characters through the console transport |
| [system_setup.cc](system_setup.cc) | TFLM's `InitializeTarget()` hook, currently empty |
| [micro_time.cc](micro_time.cc) | Timing hooks, currently return zero |

The top-level Makefile copies the target `.inc` into TFLM's target directory
and passes this directory as `PATH_TO_TARGET_SRCS`. TFLM then substitutes
the logging, timing, and setup implementations. `Makefile_internal.inc` in
the parent runtime directory adds `crt0.S` and `syscalls.cc` to the executable.
Edit these tracked sources rather than their generated/dependency copies.

## Startup and memory

Spike loads the ELF segments into target memory before entering `_start`.
The loader supplies initialized data and the embedded model. Startup sets
the global pointer with linker relaxation disabled for that instruction
sequence, sets the stack pointer, and clears `.bss` before calling C++ `main()`.
This startup is sufficient for the current application, which does not need
a global-constructor initialization sequence.

The linker script provides:

| Region | Contents |
|---|---|
| `.text` | Startup, application, runtime, kernels, and library routines |
| `.rodata` | Embedded model and other constants |
| `.data` | Initialized writable state |
| `.htif` | `tohost` and `fromhost` symbols discovered by Spike |
| `.bss` | Zero-initialized state, including the static tensor arena |
| Heap range | From the end of BSS to the reserved stack boundary |
| Stack range | Top 1 MiB of the 128 MiB RAM mapping at `0x80000000` |

The ELF has separate executable/readable and writable/readable load segments.
TFLM's tensor buffers come from the static arena. `_sbrk()` supplies a separate
bounded heap interface for newlib support; its presence does not mean TFLM
uses that heap for its tensor arena.

## Console and exit through Spike

HTIF is Spike's host-target interface. `tohost` is a volatile 64-bit mailbox:
the target writes a request, and the simulator handles it and clears the
mailbox. The console request encodes device 1, command 1, and a character.
The implementation waits for each request to finish before sending another.

Exit is encoded as `(status << 1) | 1` in `tohost`. Startup passes `main()`'s
return value to this exit path. These mailbox accesses are ordinary integer
loads/stores. `wfi` is the privileged idle instruction used after sending
exit; it is not a floating-point or atomic extension instruction.

This console implementation is specific to Spike's HTIF environment. A
CV-Wally hardware run will need a corresponding console/exit interface and
a memory layout appropriate to that environment.

## Arithmetic and timing

`-march=rv64imc -mabi=lp64` selects integer RISC-V instructions and the soft
float ABI. Operator preparation still performs floating-point calculations
on scale metadata. GCC supplies software arithmetic helpers and newlib
supplies math routines such as rounding; both execute integer instructions
on the target. The inference kernels use integer fixed-point requantization.
The build does not currently define `TFLITE_EMULATE_FLOAT`.

The timer hooks are placeholders. Their zero values do not represent
measured cycles or elapsed time. The current run validates inference output;
instruction profiling and hardware timing need separate measurement support.
