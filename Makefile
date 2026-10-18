# Invoke from the repository root. This wrapper delegates runtime/kernel
# compilation to the pinned upstream TFLM Makefile.
PROJECT_ROOT := $(abspath .)
.DEFAULT_GOAL := all
TFLM_DIR := $(PROJECT_ROOT)/.deps/tflite-micro
TFLM_MAKEFILE := tensorflow/lite/micro/tools/make/Makefile
TFLM_REVISION := 9f638f18154dff868e7053572f089be845b2fbdf
TFLM_PYTHON_ENV := $(PROJECT_ROOT)/.deps/tflm-python
RV64_TOOLCHAIN := $(PROJECT_ROOT)/.deps/xpack-riscv
# The automatic toolchain download is specific to macOS on Apple Silicon.
RV64_TOOLCHAIN_URL := https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v15.2.0-1/xpack-riscv-none-elf-gcc-15.2.0-1-darwin-arm64.tar.gz
RV64_TOOLCHAIN_SHA256 := 6588e8351455fad8aca37551f0e5a5543f3346bfa9a837cf03cbd3bdd4989f8f
RV64_TARGET_FILE := $(TFLM_DIR)/tensorflow/lite/micro/tools/make/targets/rv64imc_makefile.inc
RV64_ELF := $(TFLM_DIR)/gen/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0
SPIKE_SRC := $(PROJECT_ROOT)/.deps/riscv-isa-sim
SPIKE_BUILD := $(PROJECT_ROOT)/.deps/spike-build
SPIKE_PREFIX := $(PROJECT_ROOT)/.deps/spike
SPIKE_BIN := $(SPIKE_PREFIX)/bin/spike
SPIKE_REVISION := 19609434bb3d83448eec8796e8f0367c868efbda
MODEL := $(PROJECT_ROOT)/models/efficientnet-lite0-int8.tflite
MODEL_DATA_CC := $(PROJECT_ROOT)/tflm/generated/model_data.cc
MODEL_DATA_H := $(PROJECT_ROOT)/tflm/generated/model_data.h
GMAKE ?= gmake
JOBS ?= 8

.PHONY: all deps model-data native run-native rv64-toolchain rv64 audit-rv64 spike run-spike clean-local
.PHONY: rv64-profile spike-profile profile-tests profile-spike profile-report

RV64_PROFILE_ELF := $(PROJECT_ROOT)/build/tflm-profile/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0
PROFILE_CONFIGURATION ?= B0

# Debug information is kept outside LOAD sections; the profiling runner checks
# byte equality against RV64_ELF before accepting any measurements.
rv64-profile: rv64
	PATH="$(TFLM_PYTHON_ENV)/bin:$$PATH" \
	$(GMAKE) -j$(JOBS) -C "$(TFLM_DIR)" -f "$(TFLM_MAKEFILE)" \
		EXTERNAL_DIR="$(PROJECT_ROOT)" TARGET=rv64imc TARGET_ARCH=rv64imc \
		RV64_TOOLCHAIN_ROOT="$(RV64_TOOLCHAIN)/bin/" \
		PATH_TO_TARGET_SRCS="$(PROJECT_ROOT)/tflm/platform/rv64imc" \
		BASE_GENDIR="$(PROJECT_ROOT)/build/tflm-profile" \
		SKIP_DOWNLOADS=1 BUILD_TYPE=release_with_logs PROFILE_DEBUG_SYMBOLS=1 \
		efficientnet_lite0

spike-profile: spike
	python3 tools/build_profile_spike.py --jobs $(JOBS)

profile-tests: spike-profile rv64-toolchain
	python3 tools/test_spike_profile.py

profile-spike: rv64-profile profile-tests
	uv run --python 3.12 --with tflite --with numpy \
		python tools/profile_spike.py run --configuration "$(PROFILE_CONFIGURATION)" --baseline "$(RV64_ELF)" --elf "$(RV64_PROFILE_ELF)"

profile-report:
	python3 tools/profile_spike.py report --configuration "$(PROFILE_CONFIGURATION)"

all: native

deps:
	@if [ ! -d "$(TFLM_DIR)/.git" ]; then \
		mkdir -p "$(dir $(TFLM_DIR))"; \
		git init "$(TFLM_DIR)"; \
		git -C "$(TFLM_DIR)" remote add origin https://github.com/tensorflow/tflite-micro.git; \
		git -C "$(TFLM_DIR)" fetch --depth 1 origin "$(TFLM_REVISION)"; \
		git -C "$(TFLM_DIR)" checkout --detach FETCH_HEAD; \
	fi
	@actual_revision=$$(git -C "$(TFLM_DIR)" rev-parse HEAD); \
	if [ "$$actual_revision" != "$(TFLM_REVISION)" ]; then \
		echo "Expected TFLM $(TFLM_REVISION), found $$actual_revision" >&2; \
		echo "Move .deps/tflite-micro aside and rerun make deps." >&2; \
		exit 1; \
	fi
	@if [ ! -x "$(TFLM_PYTHON_ENV)/bin/python3" ]; then \
		python3 -m venv "$(TFLM_PYTHON_ENV)"; \
		"$(TFLM_PYTHON_ENV)/bin/python3" -m pip install pillow; \
	fi

# Grouped targets ensure one generator invocation creates both files.
$(MODEL_DATA_CC) $(MODEL_DATA_H) &: $(MODEL) tools/generate_cc_array.py | deps
	@mkdir -p "$(PROJECT_ROOT)/tflm/generated"
	python3 tools/generate_cc_array.py \
		--input "$(MODEL)" \
		--source "$(MODEL_DATA_CC)" \
		--header "$(MODEL_DATA_H)" \
		--symbol g_efficientnet_lite0_int8_model_data

model-data: $(MODEL_DATA_CC) $(MODEL_DATA_H)

rv64-toolchain:
	@if [ ! -x "$(RV64_TOOLCHAIN)/bin/riscv-none-elf-g++" ]; then \
		tmp_dir=$$(mktemp -d); \
		curl -fL --retry 3 "$(RV64_TOOLCHAIN_URL)" -o "$$tmp_dir/toolchain.tar.gz"; \
		printf '%s  %s\n' "$(RV64_TOOLCHAIN_SHA256)" "$$tmp_dir/toolchain.tar.gz" | shasum -a 256 -c -; \
		mkdir -p "$(RV64_TOOLCHAIN)"; \
		tar -xzf "$$tmp_dir/toolchain.tar.gz" -C "$(RV64_TOOLCHAIN)" --strip-components=1; \
	fi

$(RV64_TARGET_FILE): tflm/platform/rv64imc/rv64imc_makefile.inc | deps
	cp "$<" "$@"

native: model-data
	SDKROOT="$$(xcrun --sdk macosx --show-sdk-path)" \
	PATH="$(TFLM_PYTHON_ENV)/bin:$$PATH" \
	$(GMAKE) -j$(JOBS) -C "$(TFLM_DIR)" -f "$(TFLM_MAKEFILE)" \
		EXTERNAL_DIR="$(PROJECT_ROOT)" \
		BUILD_TYPE=release_with_logs \
		efficientnet_lite0

run-native: model-data
	SDKROOT="$$(xcrun --sdk macosx --show-sdk-path)" \
	PATH="$(TFLM_PYTHON_ENV)/bin:$$PATH" \
	$(GMAKE) -j$(JOBS) -C "$(TFLM_DIR)" -f "$(TFLM_MAKEFILE)" \
		EXTERNAL_DIR="$(PROJECT_ROOT)" \
		BUILD_TYPE=release_with_logs \
		run_efficientnet_lite0

# A fresh checkout needs a native build first to populate TFLM's downloads.
rv64: model-data rv64-toolchain $(RV64_TARGET_FILE)
	PATH="$(TFLM_PYTHON_ENV)/bin:$$PATH" \
	$(GMAKE) -j$(JOBS) -C "$(TFLM_DIR)" -f "$(TFLM_MAKEFILE)" \
		EXTERNAL_DIR="$(PROJECT_ROOT)" \
		TARGET=rv64imc \
		TARGET_ARCH=rv64imc \
		RV64_TOOLCHAIN_ROOT="$(RV64_TOOLCHAIN)/bin/" \
		PATH_TO_TARGET_SRCS="$(PROJECT_ROOT)/tflm/platform/rv64imc" \
		SKIP_DOWNLOADS=1 \
		BUILD_TYPE=release_with_logs \
		efficientnet_lite0

audit-rv64: rv64
	python3 tools/audit_rv64_elf.py \
		--readelf "$(RV64_TOOLCHAIN)/bin/riscv-none-elf-readelf" \
		--objdump "$(RV64_TOOLCHAIN)/bin/riscv-none-elf-objdump" \
		"$(RV64_ELF)"

spike:
	@if [ ! -d "$(SPIKE_SRC)/.git" ]; then \
		mkdir -p "$(dir $(SPIKE_SRC))"; \
		git init "$(SPIKE_SRC)"; \
		git -C "$(SPIKE_SRC)" remote add origin https://github.com/riscv-software-src/riscv-isa-sim.git; \
		git -C "$(SPIKE_SRC)" fetch --depth 1 origin "$(SPIKE_REVISION)"; \
		git -C "$(SPIKE_SRC)" checkout --detach FETCH_HEAD; \
	fi
	@actual_revision=$$(git -C "$(SPIKE_SRC)" rev-parse HEAD); \
	if [ "$$actual_revision" != "$(SPIKE_REVISION)" ]; then \
		echo "Expected Spike $(SPIKE_REVISION), found $$actual_revision" >&2; \
		exit 1; \
	fi
	@if [ ! -x "$(SPIKE_BIN)" ]; then \
		command -v dtc >/dev/null || { echo "Spike requires dtc" >&2; exit 1; }; \
		mkdir -p "$(SPIKE_BUILD)" "$(SPIKE_PREFIX)"; \
		sdk_root=""; \
		if command -v xcrun >/dev/null; then sdk_root=$$(xcrun --sdk macosx --show-sdk-path); fi; \
		cd "$(SPIKE_BUILD)"; \
		SDKROOT="$$sdk_root" "$(SPIKE_SRC)/configure" --prefix="$(SPIKE_PREFIX)"; \
		SDKROOT="$$sdk_root" $(GMAKE) -s -j$(JOBS); \
		SDKROOT="$$sdk_root" $(GMAKE) -s install; \
	fi

# Reference values correspond to the fixed synthetic input in the application.
run-spike: audit-rv64 spike
	@mkdir -p "$(PROJECT_ROOT)/build"
	@"$(SPIKE_BIN)" --isa=rv64imc "$(RV64_ELF)" | tr -d '\r' | tee "$(PROJECT_ROOT)/build/spike-output.txt"
	@grep -qx 'TFLM EfficientNet-Lite0 inference: PASS' "$(PROJECT_ROOT)/build/spike-output.txt"
	@grep -qx 'arena_used_bytes=1688176' "$(PROJECT_ROOT)/build/spike-output.txt"
	@grep -qx 'output_top_index=21 output_top_score=48 output_sum=215' "$(PROJECT_ROOT)/build/spike-output.txt"
	@grep -qx 'output_fnv1a=0x4b6a91e2' "$(PROJECT_ROOT)/build/spike-output.txt"
	@echo "Spike output matches the native TFLM reference: PASS"

clean-local:
	@if [ -d "$(PROJECT_ROOT)/tflm/generated" ]; then \
		archive_dir=$$(mktemp -d); \
		mv "$(PROJECT_ROOT)/tflm/generated" "$$archive_dir/"; \
	fi

# Browser-only execution explorer. Generated bundles/IR remain in ignored build/.
EXPLORER_BUNDLE := $(PROJECT_ROOT)/build/explorer/$(PROFILE_CONFIGURATION).zip
EXPLORER_COMPILER_DIR := $(PROJECT_ROOT)/build/explorer/compiler/$(PROFILE_CONFIGURATION)
EXPLORER_INCLUDE_BUNDLE ?= 0
EXPLORER_WITH_COMPILER := $(if $(wildcard $(EXPLORER_COMPILER_DIR)/compiler.json),--compiler-dir "$(EXPLORER_COMPILER_DIR)",)
.PHONY: explorer-export explorer-compiler explorer-dev explorer-build explorer-serve explorer-tests

explorer-export:
	uv run --python 3.12 --with tflite==2.18.0 --with numpy==2.4.3 --with pyelftools==0.32 \
		python tools/export_explorer.py --capture-dir "$(PROJECT_ROOT)/build/profiling/$(PROFILE_CONFIGURATION)" \
		--model "$(MODEL)" --elf "$(RV64_PROFILE_ELF)" \
		$(EXPLORER_WITH_COMPILER) --output "$(EXPLORER_BUNDLE)"

explorer-compiler:
	python3 tools/explorer/compiler.py --elf "$(RV64_PROFILE_ELF)" \
		--output "$(EXPLORER_COMPILER_DIR)" --jobs $(JOBS)

explorer-dev:
	cd explorer && PROFILE_CONFIGURATION="$(PROFILE_CONFIGURATION)" npm run dev

explorer-build:
	cd explorer && PROFILE_CONFIGURATION="$(PROFILE_CONFIGURATION)" EXPLORER_INCLUDE_BUNDLE="$(EXPLORER_INCLUDE_BUNDLE)" npm run build

explorer-serve:
	cd explorer && PROFILE_CONFIGURATION="$(PROFILE_CONFIGURATION)" npm run preview

explorer-tests:
	uv run --python 3.12 --with pyelftools==0.32 python -m unittest discover -s tools -p 'test_explorer.py' -v
	cd explorer && npm test

# Unified local app: the backend serves both Explorer and Simulator tabs.
.PHONY: app-dev app-serve simulator-spike simulator-dev simulator-serve simulator-tests
app-dev: simulator-dev

app-serve: simulator-serve

simulator-spike: spike
	python3 tools/spike_debug/build.py --jobs $(JOBS)

simulator-dev: simulator-spike
	uv run --python 3.12 --with aiohttp==3.14.5 --with pyelftools==0.32 python -m tools.spike_debug.dev --configuration "$(PROFILE_CONFIGURATION)" --elf "$(RV64_PROFILE_ELF)" --model "$(MODEL)" --bundle "$(EXPLORER_BUNDLE)"

simulator-serve: simulator-spike explorer-build
	uv run --python 3.12 --with aiohttp==3.14.5 --with pyelftools==0.32 python -m tools.spike_debug.server --configuration "$(PROFILE_CONFIGURATION)" --elf "$(RV64_PROFILE_ELF)" --model "$(MODEL)" --bundle "$(EXPLORER_BUNDLE)"

simulator-tests: simulator-spike
	uv run --python 3.12 --with aiohttp==3.14.5 --with pyelftools==0.32 python -m unittest discover -s tools -p 'test_spike_debug.py' -v
	cd explorer && npm test

# Stages 0–4 of the fixed-model compiler. The oracle has its own objects/library;
# no capture code is added to either B0 executable or its profiling callbacks.
COMPILER_PYTHON ?= uv run --python 3.12 python
COMPILER_FRONTEND_PYTHON ?= uv run --python 3.12 --with-requirements tools/compiler/requirements.txt python
.PHONY: compiler-freeze-b0 compiler-oracle-build compiler-oracle compiler-tests
.PHONY: compiler-import compiler-validate compiler-inspect compiler-frontend-tests

compiler-freeze-b0:
	$(COMPILER_PYTHON) tools/freeze_compiler_baseline.py

compiler-oracle-build: native
	$(COMPILER_PYTHON) tools/capture_tflm_oracle.py build --jobs $(JOBS)

compiler-oracle: compiler-oracle-build
	$(COMPILER_PYTHON) tools/capture_tflm_oracle.py capture

compiler-tests: compiler-freeze-b0 compiler-oracle compiler-a0-verify
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_*.py' -v

compiler-frontend-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_frontend.py' -v

compiler-import:
	$(COMPILER_FRONTEND_PYTHON) -m compiler import "$(MODEL)" --output-dir "$(PROJECT_ROOT)/build/compiler/import"

compiler-validate:
	$(COMPILER_FRONTEND_PYTHON) -m compiler validate "$(MODEL)"

compiler-inspect:
	$(COMPILER_FRONTEND_PYTHON) -m compiler inspect "$(MODEL)"

.PHONY: compiler-numeric-build compiler-prepare compiler-quantization-tests compiler-numeric-sanitize

compiler-numeric-build: compiler-oracle-build
	$(COMPILER_FRONTEND_PYTHON) tools/prepare_compiler.py build --jobs $(JOBS)

compiler-prepare: compiler-numeric-build
	$(COMPILER_FRONTEND_PYTHON) tools/prepare_compiler.py prepare --model "$(MODEL)"

compiler-quantization-tests: compiler-prepare compiler-oracle
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_quantization.py' -v

compiler-numeric-sanitize: compiler-numeric-build
	$(COMPILER_FRONTEND_PYTHON) tools/prepare_compiler.py sanitize

# A workspace budget is explicit, never inferred from Spike's linker RAM map.
COMPILER_MEMORY_FLAGS ?=
.PHONY: compiler-memory-plan compiler-memory-tests

compiler-memory-plan: compiler-prepare
	$(COMPILER_FRONTEND_PYTHON) -m compiler plan-memory "$(MODEL)" \
		--prepared-ir "$(PROJECT_ROOT)/build/compiler/prepared/prepared_ir.json" \
		--output-dir "$(PROJECT_ROOT)/build/compiler/memory" $(COMPILER_MEMORY_FLAGS)

compiler-memory-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_memory_plan.py' -v

# A0 proves standalone reference execution. B1 optimization is a later stage.
.PHONY: compiler-generate compiler-a0-build compiler-a0-capture compiler-a0-sanitize compiler-a0-rv64
.PHONY: compiler-a0-verify compiler-codegen-tests

compiler-generate: compiler-memory-plan
	$(COMPILER_FRONTEND_PYTHON) -m compiler generate "$(MODEL)" --config A0 \
		--prepared-ir "$(PROJECT_ROOT)/build/compiler/prepared/prepared_ir.json" \
		--memory-plan "$(PROJECT_ROOT)/build/compiler/memory/memory_plan.json" \
		--output-dir "$(PROJECT_ROOT)/build/compiler/A0"

compiler-a0-build: compiler-generate
	$(COMPILER_PYTHON) tools/build_a0.py build --kind native

compiler-a0-capture: compiler-generate
	$(COMPILER_PYTHON) tools/build_a0.py build --kind capture

compiler-a0-sanitize: compiler-generate
	$(COMPILER_PYTHON) tools/build_a0.py build --kind sanitized

compiler-a0-rv64: compiler-generate rv64-toolchain
	$(COMPILER_PYTHON) tools/build_a0.py build --kind rv64

compiler-a0-verify: compiler-a0-build compiler-a0-capture compiler-a0-sanitize compiler-a0-rv64 compiler-oracle spike
	$(COMPILER_PYTHON) tools/build_a0.py compare --kind native
	$(COMPILER_PYTHON) tools/build_a0.py compare --kind capture
	$(COMPILER_PYTHON) tools/build_a0.py compare --kind sanitized
	$(COMPILER_PYTHON) tools/build_a0.py spike

compiler-codegen-tests: compiler-a0-verify
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_codegen.py' -v

# Stage 5: scalar pointwise specialization; all other kernels retain A0 paths.
B1_GENERATED ?= $(PROJECT_ROOT)/build/compiler/B1
B1_CODEGEN_FLAGS ?=
B1_CHECKPOINT ?= B1-pointwise
B1_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/be93754b9e78bd63475c266fe05bea45f80541d015b081eb264cdb3534c6b5fd
.PHONY: compiler-b1-generate compiler-b1-build compiler-b1-verify compiler-b1-checkpoint compiler-b1-tests

compiler-b1-generate:
	$(COMPILER_FRONTEND_PYTHON) -m compiler generate "$(MODEL)" --config B1 --output-dir "$(B1_GENERATED)" $(B1_CODEGEN_FLAGS)

compiler-b1-build: compiler-b1-generate rv64-toolchain
	$(COMPILER_PYTHON) tools/build_a0.py build --kind native --generated-dir "$(B1_GENERATED)"
	$(COMPILER_PYTHON) tools/build_a0.py build --kind capture --generated-dir "$(B1_GENERATED)"
	$(COMPILER_PYTHON) tools/build_a0.py build --kind sanitized --generated-dir "$(B1_GENERATED)"
	$(COMPILER_PYTHON) tools/build_a0.py build --kind rv64 --generated-dir "$(B1_GENERATED)"

compiler-b1-verify: compiler-b1-build compiler-oracle spike
	$(COMPILER_PYTHON) tools/build_a0.py compare --kind native --generated-dir "$(B1_GENERATED)"
	$(COMPILER_PYTHON) tools/build_a0.py compare --kind capture --generated-dir "$(B1_GENERATED)"
	$(COMPILER_PYTHON) tools/build_a0.py compare --kind sanitized --generated-dir "$(B1_GENERATED)"
	$(COMPILER_PYTHON) tools/build_a0.py spike --generated-dir "$(B1_GENERATED)"

compiler-b1-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_b1.py' -v

compiler-b1-checkpoint: compiler-b1-verify compiler-b1-tests profile-tests
	$(COMPILER_PYTHON) tools/profile_compiler.py run --build-manifest "$(B1_GENERATED)/rv64/build.json" \
		--checkpoint "$(B1_CHECKPOINT)" --parent "$(B1_PARENT_CAPTURE)" --results-dir "$(PROJECT_ROOT)/results/profiling/$(B1_CHECKPOINT)"

B1_STEM_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/57fa9463fd9065d3ad8ff92493444cc5a2ce19e5e68d9399e35058238f0f859e
.PHONY: compiler-b1-stem-tests compiler-b1-stem-checkpoint
compiler-b1-stem-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_stem_unroll.py' -v

compiler-b1-stem-checkpoint: compiler-b1-stem-tests
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-stem" \
		B1_CODEGEN_FLAGS=--stem-unroll B1_CHECKPOINT=B1-stem-unroll B1_PARENT_CAPTURE="$(B1_STEM_PARENT_CAPTURE)"

B1_OC_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/62c8e308b8ffd071a3db39d21f6bfaea54cdfaa328e3577896d1e547fdd19964
.PHONY: compiler-b1-blocking-tests compiler-b1-oc2-checkpoint compiler-b1-oc4-checkpoint compiler-b1-blocking-checkpoint
# OC4 won all 32 pointwise units in the recorded same-parent comparison.
compiler-b1-blocking-checkpoint: compiler-b1-oc4-checkpoint

compiler-b1-blocking-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_pointwise_blocking.py' -v

compiler-b1-oc2-checkpoint compiler-b1-oc4-checkpoint: compiler-b1-blocking-tests compiler-b1-stem-tests

compiler-b1-oc2-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-oc2" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 2" B1_CHECKPOINT=B1-oc2 B1_PARENT_CAPTURE="$(B1_OC_PARENT_CAPTURE)"

compiler-b1-oc4-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-oc4" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4" B1_CHECKPOINT=B1-oc4 B1_PARENT_CAPTURE="$(B1_OC_PARENT_CAPTURE)"

# Compiler profiles select an immutable build record, never PROFILE_CONFIGURATION.
COMPILER_PROFILE_BUILD ?= $(PROJECT_ROOT)/build/compiler/A0/rv64/build.json
COMPILER_CHECKPOINT ?= A0-stage4-profile
COMPILER_PROFILE_PARENT ?=
COMPILER_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/latest.json
COMPILER_PROFILE_PARENT_FLAG = $(if $(COMPILER_PROFILE_PARENT),--parent "$(COMPILER_PROFILE_PARENT)",)
.PHONY: compiler-profile compiler-a0-profile compiler-profile-report compiler-profile-tests compiler-checkpoint

compiler-profile:
	$(COMPILER_PYTHON) tools/profile_compiler.py run --build-manifest "$(COMPILER_PROFILE_BUILD)" \
		--checkpoint "$(COMPILER_CHECKPOINT)" $(COMPILER_PROFILE_PARENT_FLAG)

compiler-a0-profile: compiler-a0-rv64 profile-tests
	$(COMPILER_PYTHON) tools/profile_compiler.py run --build-manifest "$(COMPILER_PROFILE_BUILD)" \
		--checkpoint "$(COMPILER_CHECKPOINT)" $(COMPILER_PROFILE_PARENT_FLAG)

compiler-profile-report:
	$(COMPILER_PYTHON) tools/profile_compiler.py report --capture "$(COMPILER_CAPTURE)" \
		--output "$(PROJECT_ROOT)/results/profiling/$(COMPILER_CHECKPOINT)"

compiler-profile-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_profiling.py' -v

# Full profiling is an explicit checkpoint gate, not part of ordinary unit tests.
compiler-checkpoint: compiler-tests profile-tests
	$(COMPILER_PYTHON) tools/profile_compiler.py run --build-manifest "$(COMPILER_PROFILE_BUILD)" \
		--checkpoint "$(COMPILER_CHECKPOINT)" $(COMPILER_PROFILE_PARENT_FLAG)

# Isolated investigation; production A0 and B0 are unchanged.
COMPILER_REPLAY_NODES ?= 1,4,8,15,58,61
COMPILER_REPLAY_CASES ?= baseline
COMPILER_REPLAY_KINDS ?= native,sanitized,rv64
.PHONY: compiler-replay compiler-gcc-analysis compiler-investigation-tests compiler-investigation-checkpoint

compiler-replay:
	$(COMPILER_PYTHON) tools/profile_compiler.py replay --build-manifest "$(COMPILER_PROFILE_BUILD)" \
		--nodes "$(COMPILER_REPLAY_NODES)" --cases "$(COMPILER_REPLAY_CASES)" --kinds "$(COMPILER_REPLAY_KINDS)"

compiler-gcc-analysis:
	$(COMPILER_PYTHON) tools/profile_compiler.py analyze --build-manifest "$(COMPILER_PROFILE_BUILD)"

compiler-investigation-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_investigation.py' -v

compiler-investigation-checkpoint: compiler-tests profile-tests
	$(COMPILER_PYTHON) tools/profile_compiler.py replay --build-manifest "$(COMPILER_PROFILE_BUILD)"
	$(COMPILER_PYTHON) tools/profile_compiler.py replay --build-manifest "$(COMPILER_PROFILE_BUILD)" \
		--nodes 1,4,8,15,58,61,10,60,62 --cases all --kinds native,sanitized \
		--output-root "$(PROJECT_ROOT)/build/compiler/replay-correctness" --results-dir "$(PROJECT_ROOT)/results/profiling/A0-replay-correctness"
	$(COMPILER_PYTHON) tools/profile_compiler.py replay --build-manifest "$(COMPILER_PROFILE_BUILD)" \
		--nodes 10,60,62 --cases baseline,zero_point --kinds rv64 \
		--output-root "$(PROJECT_ROOT)/build/compiler/replay-edge" --results-dir "$(PROJECT_ROOT)/results/profiling/A0-replay-edge"
	$(COMPILER_PYTHON) tools/profile_compiler.py analyze --build-manifest "$(COMPILER_PROFILE_BUILD)"
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_investigation.py' -v

# Portable schema-v2 compiler viewer evidence; no simulator is launched by export.
COMPILER_ANALYSIS ?= $(PROJECT_ROOT)/build/compiler/gcc-analysis/latest.json
COMPILER_VIEWER_BUNDLE ?= $(PROJECT_ROOT)/build/explorer/A0.zip
COMPILER_VIEWER_ANALYSIS_FLAG = $(if $(COMPILER_ANALYSIS),--compiler-analysis "$(COMPILER_ANALYSIS)",)
.PHONY: compiler-export compiler-viewer-tests compiler-visibility-checkpoint

compiler-export:
	uv run --python 3.12 --with pyelftools==0.32 python tools/profile_compiler.py export \
		--capture "$(COMPILER_CAPTURE)" $(COMPILER_VIEWER_ANALYSIS_FLAG) --output "$(COMPILER_VIEWER_BUNDLE)"

compiler-viewer-tests:
	uv run --python 3.12 --with pyelftools==0.32 python -m unittest discover -s tools -p 'test_explorer*.py' -v
	cd explorer && npm test

# Export regenerates B0 in v2; no v1 archive compatibility is promised.
compiler-visibility-checkpoint: compiler-export
	$(MAKE) explorer-export PROFILE_CONFIGURATION=B0
	$(MAKE) compiler-viewer-tests
	cd explorer && npm run build
	cd explorer && PROFILE_CONFIGURATION=B0 npm run test:browser -- tests/explorer.spec.ts tests/compiler.spec.ts

# Stage 6: independently selectable 3x3 / 5x5 depthwise families, retaining OC4.
B1_DW_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/482d18bbff4c7df63fe41c90ca8d30d81b53807816528eeb13da6eb30038e41f
.PHONY: compiler-b1-depthwise-tests compiler-b1-depthwise-checkpoint compiler-b1-depthwise3-checkpoint compiler-b1-depthwise5-checkpoint
compiler-b1-depthwise-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_depthwise.py' -v

compiler-b1-depthwise-checkpoint compiler-b1-depthwise3-checkpoint compiler-b1-depthwise5-checkpoint: compiler-b1-depthwise-tests compiler-b1-blocking-tests compiler-b1-stem-tests

compiler-b1-depthwise-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-depthwise" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5" \
		B1_CHECKPOINT=B1-depthwise B1_PARENT_CAPTURE="$(B1_DW_PARENT_CAPTURE)"

compiler-b1-depthwise3-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-depthwise3" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3" \
		B1_CHECKPOINT=B1-depthwise3 B1_PARENT_CAPTURE="$(B1_DW_PARENT_CAPTURE)"

compiler-b1-depthwise5-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-depthwise5" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 5" \
		B1_CHECKPOINT=B1-depthwise5 B1_PARENT_CAPTURE="$(B1_DW_PARENT_CAPTURE)"

# Project-owned B1 runtime. Modes retain stem/OC4/depthwise selections.
B1_NUMERICS_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/228637b6b0a191eb384c8e6ebb62dc56fb887780a6177e2e1dbd3efde5ba9760
B1_PROJECT_KERNELS_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/1abb9c425edb7649cd5cc9d9b64831a6ae4847fc199a9684da0f5c32f037aab3
B1_STANDALONE_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/4ce04be03cfabc010ecfd5efd57b5763c2e830a0a0c67ba8405ba6c53cdaa3f1
.PHONY: compiler-b1-runtime-tests compiler-b1-numerics-checkpoint compiler-b1-project-kernels-checkpoint compiler-b1-standalone-checkpoint
compiler-b1-runtime-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_project_runtime.py' -v

compiler-b1-numerics-checkpoint compiler-b1-project-kernels-checkpoint compiler-b1-standalone-checkpoint: compiler-b1-runtime-tests compiler-b1-depthwise-tests compiler-b1-blocking-tests compiler-b1-stem-tests

compiler-b1-numerics-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-numerics" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime project-numerics" \
		B1_CHECKPOINT=B1-numerics B1_PARENT_CAPTURE="$(B1_NUMERICS_PARENT_CAPTURE)"

compiler-b1-project-kernels-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-project-kernels" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime project-kernels" \
		B1_CHECKPOINT=B1-project-kernels B1_PARENT_CAPTURE="$(B1_PROJECT_KERNELS_PARENT_CAPTURE)"

compiler-b1-standalone-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-standalone" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime standalone" \
		B1_CHECKPOINT=B1-standalone B1_PARENT_CAPTURE="$(B1_STANDALONE_PARENT_CAPTURE)"

B1_READABILITY_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/9a880237526864575d888bc39fc88a1d96c3c827c26c49cb303bdaf573a893fc
.PHONY: compiler-b1-readable-checkpoint
compiler-b1-readable-checkpoint: compiler-b1-runtime-tests compiler-b1-depthwise-tests compiler-b1-blocking-tests compiler-b1-stem-tests
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-readable" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime standalone" \
		B1_CHECKPOINT=B1-readable B1_PARENT_CAPTURE="$(B1_READABILITY_PARENT_CAPTURE)"

# Software-only scaling; keep generic and inline alternatives reproducible.
B1_REQUANTIZATION_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/e098cc5d9eea5f3512f584e642d30032c9d83b31998d8a4cc33f82a6a0bbf59e
.PHONY: compiler-b1-requantization-tests compiler-b1-requantization-checkpoint compiler-b1-requantization-inline-checkpoint
compiler-b1-requantization-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_requantization.py' -v
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_project_runtime.py' -v

compiler-b1-requantization-checkpoint: compiler-b1-requantization-tests
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-requantization" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime standalone --requantization nonpositive" \
		B1_CHECKPOINT=B1-requantization B1_PARENT_CAPTURE="$(B1_REQUANTIZATION_PARENT_CAPTURE)"

compiler-b1-requantization-inline-checkpoint: compiler-b1-requantization-tests
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-requantization-inline" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime standalone --requantization inline-nonpositive" \
		B1_CHECKPOINT=B1-requantization-inline B1_PARENT_CAPTURE="$(B1_REQUANTIZATION_PARENT_CAPTURE)"

# Selected by repeated full policy comparisons, never by an ELF PC.
B1_REQUANTIZATION_INLINE_NODES ?= 1 2 3 4 5 6 7 8 9 11 12 14 15 18 19 20 21 22 25 26 29 41 44 48 52
.PHONY: compiler-b1-requantization-selected-checkpoint
compiler-b1-requantization-selected-checkpoint: compiler-b1-requantization-tests
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-requantization-selected" \
		B1_CODEGEN_FLAGS="--stem-unroll --pointwise-block 4 --depthwise-kernels 3 5 --runtime standalone --requantization nonpositive --requantization-inline-nodes $(B1_REQUANTIZATION_INLINE_NODES)" \
		B1_CHECKPOINT=B1-requantization-selected B1_PARENT_CAPTURE="$(B1_REQUANTIZATION_PARENT_CAPTURE)"

# Spatial reuse experiments preserve weights and all non-pointwise selections.
B1_SPATIAL_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/36c3ac40b6ebb1bb8985b0c6990e88b48def27f0ce5af60faa0a6099aca2d291
B1_SPATIAL_INLINE_NODES ?= $(B1_REQUANTIZATION_INLINE_NODES)
B1_SPATIAL_SHARED_INLINE_NODES ?= 1 2 5 8 12 15 19 22 26 41 44 48 52
B1_SPATIAL_COMMON_FLAGS = --stem-unroll --depthwise-kernels 3 5 --runtime standalone --requantization nonpositive
.PHONY: compiler-b1-spatial-checkpoint
compiler-b1-spatial-checkpoint: compiler-b1-spatial2-oc2-checkpoint
.PHONY: compiler-b1-spatial-tests compiler-b1-spatial2-oc2-checkpoint compiler-b1-spatial2-oc4-checkpoint compiler-b1-spatial2-oc2-shared-checkpoint compiler-b1-spatial2-oc4-shared-checkpoint
compiler-b1-spatial-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_spatial_pointwise.py' -v

compiler-b1-spatial2-oc2-checkpoint compiler-b1-spatial2-oc4-checkpoint compiler-b1-spatial2-oc2-shared-checkpoint compiler-b1-spatial2-oc4-shared-checkpoint: compiler-b1-spatial-tests

compiler-b1-spatial2-oc2-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-spatial2-oc2" \
		B1_CODEGEN_FLAGS="$(B1_SPATIAL_COMMON_FLAGS) --pointwise-pixels 2 --pointwise-block 2 --requantization-inline-nodes $(B1_SPATIAL_INLINE_NODES)" \
		B1_CHECKPOINT=B1-spatial2-oc2 B1_PARENT_CAPTURE="$(B1_SPATIAL_PARENT_CAPTURE)"

compiler-b1-spatial2-oc4-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-spatial2-oc4" \
		B1_CODEGEN_FLAGS="$(B1_SPATIAL_COMMON_FLAGS) --pointwise-pixels 2 --pointwise-block 4 --requantization-inline-nodes $(B1_SPATIAL_INLINE_NODES)" \
		B1_CHECKPOINT=B1-spatial2-oc4 B1_PARENT_CAPTURE="$(B1_SPATIAL_PARENT_CAPTURE)"

compiler-b1-spatial2-oc2-shared-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-spatial2-oc2-shared" \
		B1_CODEGEN_FLAGS="$(B1_SPATIAL_COMMON_FLAGS) --pointwise-pixels 2 --pointwise-block 2 --requantization-inline-nodes $(B1_SPATIAL_SHARED_INLINE_NODES)" \
		B1_CHECKPOINT=B1-spatial2-oc2-shared B1_PARENT_CAPTURE="$(B1_SPATIAL_PARENT_CAPTURE)"

compiler-b1-spatial2-oc4-shared-checkpoint:
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(PROJECT_ROOT)/build/compiler/B1-spatial2-oc4-shared" \
		B1_CODEGEN_FLAGS="$(B1_SPATIAL_COMMON_FLAGS) --pointwise-pixels 2 --pointwise-block 4 --requantization-inline-nodes $(B1_SPATIAL_SHARED_INLINE_NODES)" \
		B1_CHECKPOINT=B1-spatial2-oc4-shared B1_PARENT_CAPTURE="$(B1_SPATIAL_PARENT_CAPTURE)"

# Accepted software baseline for subsequent X1/X2 comparisons. Keep legacy B1
# experiment defaults intact; these recipes pass the complete selection.
B1_SOFTWARE_GENERATED ?= $(PROJECT_ROOT)/build/compiler/B1-spatial2-oc2
B1_SOFTWARE_CODEGEN_FLAGS = $(B1_SPATIAL_COMMON_FLAGS) --pointwise-pixels 2 --pointwise-block 2 --requantization-inline-nodes $(B1_SPATIAL_INLINE_NODES)
B1_SOFTWARE_PARENT_CAPTURE ?= $(PROJECT_ROOT)/build/profiling/compiler/be93754b9e78bd63475c266fe05bea45f80541d015b081eb264cdb3534c6b5fd
.PHONY: compiler-b1-software-build compiler-b1-software-verify compiler-b1-software-checkpoint
compiler-b1-software-build:
	$(GMAKE) compiler-b1-build B1_GENERATED="$(B1_SOFTWARE_GENERATED)" B1_CODEGEN_FLAGS="$(B1_SOFTWARE_CODEGEN_FLAGS)"

compiler-b1-software-verify:
	$(GMAKE) compiler-b1-verify B1_GENERATED="$(B1_SOFTWARE_GENERATED)" B1_CODEGEN_FLAGS="$(B1_SOFTWARE_CODEGEN_FLAGS)"

compiler-b1-software-checkpoint: compiler-b1-spatial-tests compiler-b1-requantization-tests
	$(GMAKE) compiler-b1-checkpoint B1_GENERATED="$(B1_SOFTWARE_GENERATED)" \
		B1_CODEGEN_FLAGS="$(B1_SOFTWARE_CODEGEN_FLAGS)" B1_CHECKPOINT=B1-software \
		B1_PARENT_CAPTURE="$(B1_SOFTWARE_PARENT_CAPTURE)"

# Linux/WSL-only RTL simulation of the preserved B0 and accepted software B1.
# These do not download a new model, rebuild frozen workloads, or change B0.
CVW_RUN_LABEL ?= manual
.PHONY: cvw-bootstrap cvw-smoke cvw-b0 cvw-b1 cvw-run
cvw-bootstrap:
	bash tools/cvw/bootstrap.sh

cvw-smoke:
	python3 tools/cvw/smoke.py

cvw-b0:
	python3 tools/cvw/run.py B0 --output "build/cvw/runs/B0-$(CVW_RUN_LABEL)"

cvw-b1:
	python3 tools/cvw/run.py B1 --output "build/cvw/runs/B1-$(CVW_RUN_LABEL)"

cvw-run:
	CVW_RUN_LABEL="$(CVW_RUN_LABEL)" bash tools/cvw/run_suite.sh
