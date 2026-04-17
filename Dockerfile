# --- production image (requires NVIDIA Container Toolkit) ---
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04 AS prod

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1

CMD ["python3", "app.py"]

# --- intel image (Intel Arc GPU via xpu-smi, Ubuntu 24.04 + kobuk PPA for Battlemage) ---
FROM ubuntu:24.04 AS intel

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps + Python + PPA tooling
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip curl wget gpg ca-certificates \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# kobuk-team/intel-graphics PPA — same source as host, supports Battlemage (Xe2/G21)
RUN add-apt-repository -y ppa:kobuk-team/intel-graphics \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        xpu-smi \
        intel-opencl-icd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .
RUN mkdir -p templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1

CMD ["python3", "app.py"]

# --- mixed image (NVIDIA + Intel Arc simultaneously) ---
# NVIDIA: nvidia-ml-py works via NVML library injected at runtime by NVIDIA Container Toolkit
# Intel:  xpu-smi from kobuk PPA (same as intel target)
FROM ubuntu:24.04 AS mixed

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=utility,compute

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip curl wget gpg ca-certificates \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository -y ppa:kobuk-team/intel-graphics \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        xpu-smi \
        intel-opencl-icd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .
RUN mkdir -p templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1

CMD ["python3", "app.py"]

# --- dev image (no NVIDIA driver required, GPU data will be empty) ---
FROM python:3.11-slim AS dev

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1

CMD ["python3", "app.py"]

