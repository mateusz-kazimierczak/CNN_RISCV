# Include after the pinned TFLM Makefile to record resolved build flags.
.PHONY: profile-print-flags
profile-print-flags:
	$(info CXXFLAGS=$(CXXFLAGS))
	$(info CCFLAGS=$(CCFLAGS))
	$(info LDFLAGS=$(LDFLAGS))
	$(info CORE_OPTIMIZATION_LEVEL=$(CORE_OPTIMIZATION_LEVEL))
	$(info KERNEL_OPTIMIZATION_LEVEL=$(KERNEL_OPTIMIZATION_LEVEL))
	$(info THIRD_PARTY_KERNEL_OPTIMIZATION_LEVEL=$(THIRD_PARTY_KERNEL_OPTIMIZATION_LEVEL))
	@true
