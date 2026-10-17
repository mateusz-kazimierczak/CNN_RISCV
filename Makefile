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

# Standalone live debugger; existing explorer launch targets are unchanged.
.PHONY: simulator-spike simulator-dev simulator-serve simulator-tests
simulator-spike: spike
	python3 tools/spike_debug/build.py --jobs $(JOBS)

simulator-dev: simulator-spike
	uv run --python 3.12 --with aiohttp==3.14.5 --with pyelftools==0.32 python -m tools.spike_debug.dev --configuration "$(PROFILE_CONFIGURATION)" --elf "$(RV64_PROFILE_ELF)" --model "$(MODEL)" --bundle "$(EXPLORER_BUNDLE)"

simulator-serve: simulator-spike explorer-build
	uv run --python 3.12 --with aiohttp==3.14.5 --with pyelftools==0.32 python -m tools.spike_debug.server --configuration "$(PROFILE_CONFIGURATION)" --elf "$(RV64_PROFILE_ELF)" --model "$(MODEL)" --bundle "$(EXPLORER_BUNDLE)"

simulator-tests: simulator-spike
	uv run --python 3.12 --with aiohttp==3.14.5 --with pyelftools==0.32 python -m unittest discover -s tools -p 'test_spike_debug.py' -v
	cd explorer && npm test

# Stages 0–1 of the fixed-model compiler. The oracle has its own objects/library;
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

compiler-tests: compiler-freeze-b0 compiler-oracle
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_*.py' -v

compiler-frontend-tests:
	$(COMPILER_FRONTEND_PYTHON) -m unittest discover -s tests/compiler -p 'test_frontend.py' -v

compiler-import:
	$(COMPILER_FRONTEND_PYTHON) -m compiler import "$(MODEL)" --output-dir "$(PROJECT_ROOT)/build/compiler/import"

compiler-validate:
	$(COMPILER_FRONTEND_PYTHON) -m compiler validate "$(MODEL)"

compiler-inspect:
	$(COMPILER_FRONTEND_PYTHON) -m compiler inspect "$(MODEL)"
