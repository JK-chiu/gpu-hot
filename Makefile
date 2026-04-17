.DEFAULT_GOAL := help
COMPOSE      := docker compose
URL          := http://localhost:1312

.PHONY: help build up intel mixed dev down logs test verify clean status check-intel

help:
	@echo "GPU Hot – Docker targets"
	@echo ""
	@echo "  make up          Start NVIDIA-only service (requires NVIDIA Container Toolkit)"
	@echo "  make intel       Start Intel Arc-only service (requires /dev/dri + xpu-smi)"
	@echo "  make mixed       Start NVIDIA + Intel Arc simultaneously"
	@echo "  make dev         Start dev image (no GPU required, empty data)"
	@echo "  make down        Stop all containers"
	@echo "  make logs        Follow active container logs"
	@echo "  make status      Show container & health status"
	@echo "  make verify      Wait for service then hit health endpoints"
	@echo "  make test        Run backend + frontend unit tests"
	@echo "  make clean       Remove all containers, images, volumes"
	@echo "  make check-intel Verify host is ready for Intel GPU passthrough"
	@echo ""
	@echo "Dashboard port: 1312  →  $(URL)"

build:
	$(COMPOSE) build

up: build
	$(COMPOSE) up -d
	@echo "NVIDIA dashboard → $(URL)"

intel:
	$(COMPOSE) -f docker-compose.intel.yml up -d --build
	@echo ""
	@echo "Intel Arc dashboard → $(URL)"
	@echo "Run 'make verify' to confirm GPU data is flowing"

mixed:
	$(COMPOSE) -f docker-compose.mixed.yml up -d --build
	@echo ""
	@echo "NVIDIA + Intel Arc dashboard → $(URL)"
	@echo "Run 'make verify' to confirm GPU data is flowing"

dev:
	$(COMPOSE) -f docker-compose.dev.yml up -d --build
	@echo "Dev dashboard → $(URL)"

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
