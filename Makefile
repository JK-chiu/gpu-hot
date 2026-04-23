
.DEFAULT_GOAL := help
.PHONY: help build build-nvidia build-intel up intel down restart logs status verify \
        export export-nvidia export-intel export-source \
        import-nvidia import-intel \
        check-nvidia check-intel test clean

##@ 說明

help: ## 顯示說明
	@echo ""
	@echo "-- 建置 --"
	@echo "  make build          建置 NVIDIA + Intel Arc 映像"
	@echo "  make build-nvidia   建置 NVIDIA 映像"
	@echo "  make build-intel    建置 Intel Arc 映像"
	@echo ""
	@echo "-- 容器操作 --"
	@echo "  make up             啟動 NVIDIA 服務"
	@echo "  make intel          啟動 Intel Arc 服務"
	@echo "  make down           停止所有容器"
	@echo "  make restart        重啟服務（down → up）"
	@echo "  make logs           追蹤容器日誌"
	@echo "  make status         查看容器狀態"
	@echo "  make verify         健檢運行中的服務"
	@echo ""
	@echo "-- 打包 / 交付 --"
	@echo "  make export                     匯出 NVIDIA + Intel Arc 映像 → dist/"
	@echo "  make export-nvidia              僅匯出 NVIDIA 映像"
	@echo "  make export-intel               僅匯出 Intel Arc 映像"
	@echo "  make export-source              原始碼 tarball → dist/"
	@echo "  make import-nvidia              匯入 NVIDIA 映像"
	@echo "  make import-intel               匯入 Intel Arc 映像"
	@echo ""
	@echo "-- 測試 / 維護 --"
	@echo "  make test           執行後端 + 前端單元測試"
	@echo "  make check-nvidia   驗證主機 NVIDIA GPU 環境"
	@echo "  make check-intel    驗證主機 Intel GPU 環境"
	@echo "  make clean          移除所有容器、映像、volumes"
	@echo ""

##@ 建置

build: build-nvidia build-intel ## 建置 NVIDIA + Intel Arc 映像

build-nvidia: ## 建置 NVIDIA 映像
	docker compose build

build-intel: ## 建置 Intel Arc 映像
	docker compose -f docker-compose.intel.yml build

##@ 容器操作

up: ## 啟動 NVIDIA 服務
	docker compose up -d

intel: ## 啟動 Intel Arc 服務
	docker compose -f docker-compose.intel.yml up -d

down: ## 停止所有容器
	-docker compose down 2>/dev/null
	-docker compose -f docker-compose.intel.yml down 2>/dev/null

restart: ## 重啟服務（down → up）
	@$(MAKE) -s down
	@$(MAKE) -s up

logs: ## 追蹤容器日誌
	@docker logs -f $$(docker ps --filter "name=gpu-hot" --format "{{.Names}}" | head -1)

status: ## 查看容器狀態
	@docker ps --filter "name=gpu-hot" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

verify: ## 健檢運行中的服務
	@for i in $$(seq 1 15); do \
		if curl -sf http://localhost:1312/api/gpu-data >/dev/null 2>&1; then \
			echo "✅ Service is healthy."; \
			echo ""; echo "--- gpu-data ---"; \
			curl -s http://localhost:1312/api/gpu-data | python3 -m json.tool; \
			echo ""; echo "--- version ---"; \
			curl -s http://localhost:1312/api/version  | python3 -m json.tool; \
			exit 0; \
		fi; \
		echo "  attempt $$i/15 ..."; sleep 3; \
	done; \
	echo "❌ Service did not respond after 45s"; $(MAKE) logs; exit 1

##@ 打包 / 交付

export: export-nvidia export-intel ## 匯出 NVIDIA + Intel Arc 映像

export-nvidia: ## 儲存 NVIDIA 映像 → dist/gpu-hot-nvidia.tar.gz
	@mkdir -p dist
	docker compose build gpu-hot
	docker image save gpu-hot:latest | gzip > dist/gpu-hot-nvidia.tar.gz
	md5sum dist/gpu-hot-nvidia.tar.gz > dist/gpu-hot-nvidia.tar.gz.md5
	@echo "✅ dist/gpu-hot-nvidia.tar.gz"

export-intel: ## 儲存 Intel Arc 映像 → dist/gpu-hot-intel.tar.gz
	@mkdir -p dist
	docker compose -f docker-compose.intel.yml build gpu-hot
	docker image save gpu-hot:intel | gzip > dist/gpu-hot-intel.tar.gz
	md5sum dist/gpu-hot-intel.tar.gz > dist/gpu-hot-intel.tar.gz.md5
	@echo "✅ dist/gpu-hot-intel.tar.gz"

export-source: ## 原始碼 tarball → dist/gpu-hot-source.tar.gz
	@mkdir -p dist
	tar -czf dist/gpu-hot-source.tar.gz \
		--exclude-vcs --exclude=dist --exclude=.venv --exclude=venv \
		--exclude=__pycache__ --exclude=.pytest_cache --exclude=node_modules \
		--exclude='*.pyc' .
	@echo "✅ dist/gpu-hot-source.tar.gz"

import-nvidia: ## 從 gpu-hot-nvidia.tar.gz 匯入 NVIDIA 映像
	@test -f gpu-hot-nvidia.tar.gz || { echo "❌ gpu-hot-nvidia.tar.gz not found"; exit 1; }
	@if [ -f gpu-hot-nvidia.tar.gz.md5 ]; then \
		[ "$$(md5sum gpu-hot-nvidia.tar.gz | awk '{print $$1}')" = "$$(awk '{print $$1}' gpu-hot-nvidia.tar.gz.md5)" ] \
		&& echo "✅ MD5 OK" || { echo "❌ MD5 mismatch"; exit 1; }; \
	else echo "⚠️  no md5 file, skipping check"; fi
	docker load -i gpu-hot-nvidia.tar.gz

import-intel: ## 從 gpu-hot-intel.tar.gz 匯入 Intel Arc 映像
	@test -f gpu-hot-intel.tar.gz || { echo "❌ gpu-hot-intel.tar.gz not found"; exit 1; }
	@if [ -f gpu-hot-intel.tar.gz.md5 ]; then \
		[ "$$(md5sum gpu-hot-intel.tar.gz | awk '{print $$1}')" = "$$(awk '{print $$1}' gpu-hot-intel.tar.gz.md5)" ] \
		&& echo "✅ MD5 OK" || { echo "❌ MD5 mismatch"; exit 1; }; \
	else echo "⚠️  no md5 file, skipping check"; fi
	docker load -i gpu-hot-intel.tar.gz

##@ 測試 / 維護

test: ## 執行後端 + 前端單元測試
	docker compose -f tests/docker-compose.unittest.yml run --build --rm unittest

check-nvidia: ## 驗證主機 NVIDIA GPU 環境
	@echo "=== NVIDIA GPU host check ==="
	@echo "[nvidia-smi]";   nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader 2>/dev/null || echo "  WARN: nvidia-smi not found"
	@echo "[docker runtime]"; docker info 2>/dev/null | grep -i nvidia || echo "  WARN: NVIDIA Container Toolkit not detected"
	@echo "[kernel module]"; lsmod | grep -E '^nvidia\s' || echo "  WARN: nvidia module not loaded"

check-intel: ## 驗證主機 Intel GPU 環境
	@echo "=== Intel GPU host check ==="
	@echo "[/dev/dri]";     ls -la /dev/dri/ 2>/dev/null || echo "  WARN: /dev/dri not found"
	@echo "[xpu-smi]";      which xpu-smi 2>/dev/null && xpu-smi discovery 2>/dev/null || echo "  INFO: xpu-smi not on host"
	@echo "[render group]"; getent group render || echo "  WARN: render group not found"
	@echo "[kernel module]"; lsmod | grep -E '^(i915|xe)\s' || echo "  WARN: i915/xe not loaded"

clean: ## 移除所有容器、映像、volumes
	-docker compose down --rmi all --volumes --remove-orphans 2>/dev/null
	-docker compose -f docker-compose.intel.yml down --rmi all --volumes --remove-orphans 2>/dev/null
	-docker compose -f tests/docker-compose.unittest.yml down --rmi all --volumes --remove-orphans 2>/dev/null
