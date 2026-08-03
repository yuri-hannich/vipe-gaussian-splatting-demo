PYTHON ?= python3
DATASET_DIR ?= data/raw/zavod70
MANIFEST_DIR ?= data/manifests
INTERIM_DIR ?= data/interim
SMOKE_FRAMES ?= 24
SMOKE_WIDTH ?= 1280
FULL_WIDTH ?= 1600
FPS ?= 1
PROFILE ?= quality

RUN := PYTHONPATH=src $(PYTHON) -m vipe_demo

.PHONY: help check download inspect prepare-smoke prepare-full local-smoke test verify gpu-preflight pipeline pipeline-dry-run runpod runpod-dry-run

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Local macOS/Linux development"
	@echo "  check          Check local CPU-side dependencies"
	@echo "  download       Download the public assignment dataset"
	@echo "  inspect        Validate all source images and write a manifest"
	@echo "  prepare-smoke  Build and validate a short contiguous 1 FPS video"
	@echo "  prepare-full   Build and validate the complete 1 FPS video"
	@echo "  local-smoke    Run check, inspect, and prepare-smoke"
	@echo "  test           Run the unit test suite"
	@echo "  verify         Run syntax checks, tests, and a quality pipeline dry-run"
	@echo ""
	@echo "CUDA host"
	@echo "  gpu-preflight  Require Linux and an accessible NVIDIA GPU"
	@echo "  pipeline       Run the complete resumable pipeline (PROFILE=quality)"
	@echo "  pipeline-dry-run  Print all stages without executing them"
	@echo "  runpod         Provision RunPod locally, run the pipeline, fetch artifacts"
	@echo "  runpod-dry-run Validate local RunPod configuration without provisioning"

check:
	$(RUN) check

download:
	DATASET_DIR="$(abspath $(DATASET_DIR))" bash scripts/download_dataset.sh

inspect:
	$(RUN) inspect \
		--input "$(DATASET_DIR)" \
		--manifest "$(MANIFEST_DIR)/source.json" \
		--expected-count 126

prepare-smoke:
	$(RUN) prepare \
		--input "$(DATASET_DIR)" \
		--output "$(INTERIM_DIR)/smoke/zavod70-smoke.mp4" \
		--manifest "$(MANIFEST_DIR)/smoke-video.json" \
		--max-frames "$(SMOKE_FRAMES)" \
		--width "$(SMOKE_WIDTH)" \
		--fps "$(FPS)"

prepare-full:
	$(RUN) prepare \
		--input "$(DATASET_DIR)" \
		--output "$(INTERIM_DIR)/full/zavod70.mp4" \
		--manifest "$(MANIFEST_DIR)/full-video.json" \
		--width "$(FULL_WIDTH)" \
		--fps "$(FPS)"

local-smoke: check prepare-smoke test

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

verify: test pipeline-dry-run
	@for script in scripts/*.sh scripts/lib/*.sh; do bash -n "$$script" || exit 1; done
	@bash -n .env.runpod.example
	@echo "Repository verification passed"

gpu-preflight:
	$(RUN) check --require-gpu

pipeline:
	DATASET_DIR="$(abspath $(DATASET_DIR))" $(RUN) pipeline --profile "$(PROFILE)"

pipeline-dry-run:
	DATASET_DIR="$(abspath $(DATASET_DIR))" $(RUN) pipeline --profile "$(PROFILE)" --dry-run

runpod:
	PROFILE="$(PROFILE)" bash scripts/runpod_pipeline.sh

runpod-dry-run:
	PROFILE="$(PROFILE)" RUNPOD_DRY_RUN=true bash scripts/runpod_pipeline.sh
