<div align="center">

# GPU Hot

Real-time NVIDIA GPU monitoring dashboard. Lightweight, web-based, and self-hosted.

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![NVIDIA](https://img.shields.io/badge/NVIDIA-GPU-76B900?style=flat-square&logo=nvidia&logoColor=white)](https://www.nvidia.com/)

<img src="gpu-hot.png" alt="GPU Hot Dashboard" width="800" />

<p>
<a href="https://psalias2006.github.io/gpu-hot/demo.html">
<img src="https://img.shields.io/badge/%E2%96%B6%20%20Live_Demo-try_it_in_your_browser-1a1a1a?style=for-the-badge&labelColor=76B900" alt="Live Demo" />
</a>
</p>

</div>

---

## Usage

GPU Hot now exposes two deployment variants from the project root:

- `make nvidia` for NVIDIA hosts
- `make intel` for Intel Arc hosts

Monitor a single machine or an entire cluster with the same Docker image.

**Single machine:**
```bash
docker run -d --gpus all -p 1312:1312 ghcr.io/psalias2006/gpu-hot:latest
```

**Multiple machines:**
```bash
# On each GPU server
docker run -d --gpus all -p 1312:1312 -e NODE_NAME=$(hostname) ghcr.io/psalias2006/gpu-hot:latest

# On a hub machine (no GPU required)
docker run -d -p 1312:1312 -e GPU_HOT_MODE=hub -e NODE_URLS=http://server1:1312,http://server2:1312,http://server3:1312 ghcr.io/psalias2006/gpu-hot:latest
```

Open `http://localhost:1312`

**Older GPUs:** Add `-e NVIDIA_SMI=true` if metrics don't appear.

**Process monitoring:** Add `--init --pid=host` to see process names. Note: This allows the container to access host process information.

**From source:**
```bash
git clone https://github.com/psalias2006/gpu-hot
cd gpu-hot
make nvidia
```

**Requirements:** Docker + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

## Transfer to another machine

Use the built-in export targets when you need an offline handoff.

**On the source machine:**
```bash
# In Makefile, set EXPORT_VARIANT := nvidia or intel
make export                       # image -> dist/gpu-hot-<version>-<variant>-image.tar.gz
make export-source                 # optional source bundle -> dist/gpu-hot-<version>-source.tar.gz
```

Copy the archive in `dist/` to the target machine with `scp`, `rsync`, a USB drive, or any other transfer method.

**On the target machine (image archive):**
```bash
docker load -i gpu-hot-<version>-nvidia-image.tar.gz
docker run -d --gpus all -p 1312:1312 gpu-hot:latest
```

**On the target machine (source bundle):**
```bash
tar xzf gpu-hot-<version>-source.tar.gz
cd gpu-hot
make nvidia
```

Use `make intel` instead when rebuilding on an Intel Arc host.

Image archives should be loaded on a compatible CPU architecture. If the source and target machines differ, transfer the source bundle and rebuild on the target instead.

---

## Features

- Real-time metrics (sub-second)
- Automatic multi-GPU detection
- Process monitoring (PID, memory usage)
- Historical charts (utilization, temperature, power, clocks)
- System metrics (CPU, RAM)
- Scale from 1 to 100+ GPUs

**Metrics:** Utilization, temperature, memory, power draw, fan speed, clock speeds, PCIe info, P-State, throttle status, encoder/decoder sessions

---

## Configuration

**Environment variables:**
```bash
NVIDIA_VISIBLE_DEVICES=0,1     # Specific GPUs (default: all)
NVIDIA_SMI=true                # Force nvidia-smi mode for older GPUs
GPU_HOT_MODE=hub               # Set to 'hub' for multi-node aggregation (default: single node)
NODE_NAME=gpu-server-1         # Node display name (default: hostname)
NODE_URLS=http://host:1312...  # Comma-separated node URLs (required for hub mode)
```

**Backend (`core/config.py`):**
```python
UPDATE_INTERVAL = 0.5  # Polling interval in seconds
PORT = 1312            # Server port
```

---

## API

### HTTP
```bash
GET /              # Dashboard
GET /api/gpu-data  # JSON metrics snapshot
GET /api/version   # Version and update info
```

### WebSocket
```javascript
const ws = new WebSocket('ws://localhost:1312/socket.io/');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // data.gpus      — per-GPU metrics
  // data.processes  — active GPU processes
  // data.system     — host CPU, RAM, swap, disk, network
};
```

---

## Project Structure

```
gpu-hot/
├── app.py                      # FastAPI server + routes
├── version.py                  # Version info
├── core/
│   ├── config.py               # Configuration
│   ├── monitor.py              # NVML GPU monitoring
│   ├── handlers.py             # WebSocket handlers
│   ├── hub.py                  # Multi-node hub aggregator
│   ├── hub_handlers.py         # Hub WebSocket handlers
│   ├── nvidia_smi_fallback.py  # nvidia-smi fallback for older GPUs
│   └── metrics/
│       ├── collector.py        # Metrics collection
│       └── utils.py            # Metric utilities
├── static/
│   ├── css/
│   │   ├── tokens.css          # Design tokens (colors, spacing)
│   │   ├── layout.css          # Page layout (sidebar, main)
│   │   └── components.css      # UI components (cards, charts)
│   ├── js/
│   │   ├── chart-config.js     # Chart.js configurations
│   │   ├── chart-manager.js    # Chart data + lifecycle
│   │   ├── chart-drawer.js     # Correlation drawer
│   │   ├── gpu-cards.js        # GPU card rendering
│   │   ├── socket-handlers.js  # WebSocket + batched rendering
│   │   ├── ui.js               # Sidebar navigation
│   │   └── app.js              # Init + version check
│   └── favicon.svg
├── templates/index.html
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Troubleshooting

**No GPUs detected:**
```bash
nvidia-smi  # Verify drivers work
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi  # Test Docker GPU access
```

**Hub can't connect to nodes:**
```bash
curl http://node-ip:1312/api/gpu-data  # Test connectivity
sudo ufw allow 1312/tcp                # Check firewall
```

**Performance issues:** Increase `UPDATE_INTERVAL` in `core/config.py`

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=psalias2006/gpu-hot&type=date&legend=top-left)](https://www.star-history.com/#psalias2006/gpu-hot&type=date&legend=top-left)

## Contributing

PRs welcome. Open an issue for major changes.

## License

MIT - see [LICENSE](LICENSE)
