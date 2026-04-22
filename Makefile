.DEFAULT_GOAL := help
COMPOSE      := docker compose
URL          := http://localhost:1312
ARCHIVE_DIR  ?= dist
# Set the image variant exported by `make export`: nvidia or intel.
EXPORT_VARIANT := nvidia
VERSION      := $(shell sed -n 's/__version__ = "\(.*\)"/\1/p' version.py)

ifeq ($(EXPORT_VARIANT),nvidia)
EXPORT_COMPOSE := $(COMPOSE)
EXPORT_IMAGE   := gpu-hot:latest
else ifeq ($(EXPORT_VARIANT),intel)
EXPORT_COMPOSE := $(COMPOSE) -f docker-compose.intel.yml
EXPORT_IMAGE   := gpu-hot:intel
else
$(error Unsupported EXPORT_VARIANT '$(EXPORT_VARIANT)'. Use nvidia or intel)
endif

EXPORT_ARCHIVE ?= $(ARCHIVE_DIR)/gpu-hot-$(VERSION)-$(EXPORT_VARIANT)-image.tar.gz
SOURCE_ARCHIVE ?= $(ARCHIVE_DIR)/gpu-hot-$(VERSION)-source.tar.gz

.PHONY: help build nvidia up intel down logs test verify clean status check-intel export export-source

help:
	@echo "GPU Hot – Docker targets"
	@echo ""
	@echo "  make nvidia      Start NVIDIA service (requires NVIDIA Container Toolkit)"
	@echo "  make intel       Start Intel Arc service (requires /dev/dri + xpu-smi)"
	@echo "  make up          Alias for make nvidia"
	@echo "  make down        Stop all containers"
	@echo "  make logs        Follow active container logs"
	@echo "  make status      Show container & health status"
	@echo "  make verify      Wait for service then hit health endpoints"
	@echo "  make test        Run backend + frontend unit tests"
	@echo "  make export      Build and export the image selected by EXPORT_VARIANT at the top of this file"
	@echo "  make export-source  Create a source tarball for rebuilds on another machine"
	@echo "  make clean       Remove all containers, images, volumes"
	@echo "  make check-intel Verify host is ready for Intel GPU passthrough"
	@echo ""
	@echo "Dashboard port: 1312  →  $(URL)"

build:
	$(COMPOSE) build

nvidia:
	$(COMPOSE) up -d --build
	@echo "NVIDIA dashboard → $(URL)"

up: nvidia

intel:
	$(COMPOSE) -f docker-compose.intel.yml up -d --build
	@echo ""
	@echo "Intel Arc dashboard → $(URL)"
	@echo "Run 'make verify' to confirm GPU data is flowing"

down:
	-$(COMPOSE) down 2>/dev/null
	-$(COMPOSE) -f docker-compose.intel.yml down 2>/dev/null
	-$(COMPOSE) -f docker-compose.mixed.yml down 2>/dev/null
	-$(COMPOSE) -f docker-compose.dev.yml down 2>/dev/null

logs:
	@docker logs -f $$(docker ps --filter "name=gpu-hot" --format "{{.Names}}" | head -1)

status:
	@docker ps --filter "name=gpu-hot" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

verify:
	@echo "Waiting for service at $(URL) ..."
	@for i in $$(seq 1 15); do \
		if curl -sf $(URL)/api/gpu-data > /dev/null 2>&1; then \
			echo ""; \
			echo "Service is healthy."; \
			echo ""; \
			echo "--- /api/gpu-data ---"; \
			curl -s $(URL)/api/gpu-data | python3 -m json.tool; \
			echo ""; \
			echo "--- /api/version ---"; \
			curl -s $(URL)/api/version | python3 -m json.tool; \
			exit 0; \
		fi; \
		echo "  attempt $$i/15 ..."; \
		sleep 3; \
	done; \
	echo "Service did not respond after 45s"; \
	$(MAKE) logs; \
	exit 1

export:
	@mkdir -p $(ARCHIVE_DIR)
	@echo "Building $(EXPORT_VARIANT) image ($(EXPORT_IMAGE)) ..."
	$(EXPORT_COMPOSE) build gpu-hot
	@echo "Writing $(EXPORT_ARCHIVE) ..."
	@tmp="$(EXPORT_ARCHIVE).tmp"; \
	rm -f "$$tmp"; \
	docker image save $(EXPORT_IMAGE) | gzip > "$$tmp"; \
	mv "$$tmp" "$(EXPORT_ARCHIVE)"
	@echo "Image archive ready: $(EXPORT_ARCHIVE)"
	@echo "Load on target machine with: docker load -i $(EXPORT_ARCHIVE)"

export-source:
	@mkdir -p $(ARCHIVE_DIR)
	@echo "Writing $(SOURCE_ARCHIVE) ..."
	@tar -czf $(SOURCE_ARCHIVE) \
		--exclude-vcs \
		--exclude='dist' \
		--exclude='build' \
		--exclude='.venv' \
		--exclude='venv' \
		--exclude='__pycache__' \
		--exclude='.pytest_cache' \
		--exclude='node_modules' \
		--exclude='*.pyc' \
		.
	@echo "Source archive ready: $(SOURCE_ARCHIVE)"
	@echo "Rebuild on target machine with: tar xzf $(SOURCE_ARCHIVE) && cd gpu-hot && docker compose up -d --build"

check-intel:
	@echo "=== Intel GPU host check ==="
	@echo ""
	@echo "[/dev/dri devices]"
	@ls -la /dev/dri/ 2>/dev/null || echo "  WARN: /dev/dri not found — Intel driver may not be loaded"
	@echo ""
	@echo "[xpu-smi on host]"
	@which xpu-smi 2>/dev/null && xpu-smi discovery 2>/dev/null || echo "  INFO: xpu-smi not on host (will run inside container)"
	@echo ""
	@echo "[render group GID]"
	@getent group render || echo "  WARN: render group not found"
	@echo ""
	@echo "[kernel modules]"
	@lsmod | grep -E '^(i915|xe)\s' || echo "  WARN: i915/xe module not loaded"

test:
	docker compose -f tests/docker-compose.unittest.yml run --rm unittest

clean:
	-$(COMPOSE) down --rmi all --volumes --remove-orphans 2>/dev/null
	-$(COMPOSE) -f docker-compose.intel.yml down --rmi all --volumes --remove-orphans 2>/dev/null
	-$(COMPOSE) -f docker-compose.dev.yml down --rmi all --volumes --remove-orphans 2>/dev/null
	-$(COMPOSE) -f tests/docker-compose.unittest.yml down --rmi all --volumes --remove-orphans 2>/dev/null
