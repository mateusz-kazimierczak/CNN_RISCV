# Reuse the isolated oracle library; no source or object changes to B0.
$(eval $(call microlite_test,compiler_prepared_oracle,\
$(EXTERNAL_DIR)/tools/compiler/prepared.cc,,))
