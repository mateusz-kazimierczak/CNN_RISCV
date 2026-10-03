# Bare-metal RV64IMC target for the TFLM Make build.
TARGET_ARCH := rv64imc
TARGET_TOOLCHAIN_PREFIX := riscv-none-elf-
TARGET_TOOLCHAIN_ROOT := $(RV64_TOOLCHAIN_ROOT)

# lp64 selects the soft float ABI. C++ float/double calculations in operator
# preparation are compiled to software helpers that use integer instructions.
RISCV_ARCH := rv64imc
RISCV_ABI := lp64

PLATFORM_FLAGS := \
  -march=$(RISCV_ARCH) \
  -mabi=$(RISCV_ABI) \
  -mcmodel=medany \
  -fno-builtin \
  -fno-delete-null-pointer-checks \
  -fomit-frame-pointer \
  -DTF_LITE_MCU_DEBUG_LOG \
  -DTF_LITE_USE_GLOBAL_CMATH_FUNCTIONS

CXXFLAGS += $(PLATFORM_FLAGS) \
  -fpermissive \
  -fno-use-cxa-atexit \
  -DTF_LITE_USE_GLOBAL_MIN \
  -DTF_LITE_USE_GLOBAL_MAX

CCFLAGS += $(PLATFORM_FLAGS)

LDFLAGS += \
  -march=$(RISCV_ARCH) \
  -mabi=$(RISCV_ABI) \
  -mcmodel=medany \
  -nostartfiles \
  -Wl,--gc-sections \
  -Wl,-T,$(EXTERNAL_DIR)/tflm/platform/rv64imc/link.ld

# Newlib's math library supplies setup routines such as rounding; GCC supplies
# software float arithmetic. Inference requantization uses integer operations.
MICROLITE_LIBS := -lm
