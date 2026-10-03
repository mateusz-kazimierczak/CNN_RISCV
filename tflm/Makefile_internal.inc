# TFLM discovers this external example through EXTERNAL_DIR. It links the
# shared application and embedded model against its own microlite library.
EFFICIENTNET_LITE0_SRCS := \
$(EXTERNAL_DIR)/tflm/efficientnet_lite0.cc \
$(EXTERNAL_DIR)/tflm/generated/model_data.cc

ifeq ($(TARGET), rv64imc)
# The bare-metal target supplies its own process entry and newlib syscalls.
EFFICIENTNET_LITE0_SRCS += \
$(EXTERNAL_DIR)/tflm/platform/rv64imc/crt0.S \
$(EXTERNAL_DIR)/tflm/platform/rv64imc/syscalls.cc
endif

EFFICIENTNET_LITE0_HDRS := \
$(EXTERNAL_DIR)/tflm/generated/model_data.h

INCLUDES += -I$(EXTERNAL_DIR)/tflm/generated

# Upstream's microlite_test macro also builds examples without test assertions.
$(eval $(call microlite_test,efficientnet_lite0,\
$(EFFICIENTNET_LITE0_SRCS),$(EFFICIENTNET_LITE0_HDRS),))
