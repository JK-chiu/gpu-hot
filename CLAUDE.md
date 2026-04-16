# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

GPU Hot is a real-time NVIDIA GPU monitoring dashboard. FastAPI serves WebSocket-based live metrics from NVML (or nvidia-smi fallback) to a vanilla JS frontend. It supports single-node and multi-node "hub" aggregation modes.

## Commands

```bash
# Run all tests (backend + frontend, Docker-based)
./run_tests.sh

# Run only the test container manually
docker compose -f tests/docker-compose.unittest.yml run --rm unittest

# Run individual backend tests locally (without Docker)
pytest tests/unit/test_monitor.py::TestGPUMonitorInit::test_init_success

# Run individual frontend tests locally (without Docker)
npm test --prefix tests -- gpu-cards.test.js

# Start dev environment
docker-compose up --build

# Load test with mock cluster
cd tests && docker compose -f docker-compose.test.yml up --build
```

## Architecture

**Data flow:**

```
NVIDIA GPU
  → NVML (nvidia-ml-py) or nvidia-smi fallback
  → GPUMonitor (core/monitor.py) — async, uses thread pool for blocking calls
  → WebSocket broadcast (core/handlers.py)
  → Browser (static/js/ via socket.io-compatible WebSocket)
```

**Hub mode** (`GPU_HOT_MODE=hub`): `core/hub.py` opens WebSocket client connections to upstream node URLs, aggregates their data, and re-broadcasts to the dashboard. Hub handlers are separate from single-node handlers.

**Key files:**

| File | Role |
|------|------|
| `app.py` | FastAPI app, routing, WebSocket endpoint, mode selection |
| `core/config.py` | All env-var configuration (port, intervals, node URLs, mode) |
| `core/monitor.py` | `GPUMonitor` — metric collection loop, per-GPU auto-detection |
| `core/metrics/collector.py` | `MetricsCollector` — parses NVML data into metric dicts |
| `core/nvidia_smi_fallback.py` | Subprocess-based fallback for GPUs without NVML support |
| `core/handlers.py` | Single-node WebSocket handler loop |
| `core/hub.py` + `core/hub_handlers.py` | Multi-node aggregation |
| `static/js/gpu-cards.js` | GPU card DOM rendering (largest frontend file) |
| `static/js/chart-manager.js` | Chart.js lifecycle management |
| `static/js/socket-handlers.js` | WebSocket connection + batched rendering |

**GPU auto-detection:** At startup, each detected GPU is tested to determine whether it can use NVML directly or needs the nvidia-smi subprocess fallback. This per-GPU flag is stored on the monitor instance.

**Frontend:** Pure vanilla JS, no framework. Modular files loaded via `<script type="module">`. `app.js` initializes; `socket-handlers.js` receives WebSocket data and triggers batched DOM/chart updates.

**Testing:** Backend uses pytest with pytest-asyncio. Frontend uses Vitest with jsdom. Both run inside `tests/Dockerfile.unittest`. There is no Makefile.
