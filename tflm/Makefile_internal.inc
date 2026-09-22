EFFICIENTNET_LITE0_SRCS := \
$(EXTERNAL_DIR)/tflm/efficientnet_lite0.cc \
$(EXTERNAL_DIR)/tflm/generated/model_data.cc

ifeq ($(TARGET), rv64imc)
EFFICIENTNET_LITE0_SRCS += \
$(EXTERNAL_DIR)/tflm/platform/rv64imc/crt0.S \
$(EXTERNAL_DIR)/tflm/platform/rv64imc/syscalls.cc
endif

EFFICIENTNET_LITE0_HDRS := \
$(EXTERNAL_DIR)/tflm/generated/model_data.h

INCLUDES += -I$(EXTERNAL_DIR)/tflm/generated

$(eval $(call microlite_test,efficientnet_lite0,\
$(EFFICIENTNET_LITE0_SRCS),$(EFFICIENTNET_LITE0_HDRS),))
