# Include after the pinned upstream Makefile. BASE_GENDIR must be isolated.
INCLUDES += -I$(EXTERNAL_DIR)/tflm/generated
$(eval $(call microlite_test,compiler_tflm_oracle,\
$(EXTERNAL_DIR)/tools/compiler/oracle.cc \
$(EXTERNAL_DIR)/tflm/generated/model_data.cc,\
$(EXTERNAL_DIR)/tflm/generated/model_data.h,))
