# Bare-metal RV64IMC target for the TFLM Make build.
TARGET_ARCH := rv64imc
TARGET_TOOLCHAIN_PREFIX := riscv-none-elf-
TARGET_TOOLCHAIN_ROOT := $(RV64_TOOLCHAIN_ROOT)

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

# Newlib supplies the few floating-point setup helpers used to derive integer
# requantization parameters. Inference kernels remain integer-only.
MICROLITE_LIBS := -lm
