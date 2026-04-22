# --- shared Python runtime for lightweight targets ---
FROM python:3.11-slim-bookworm AS python-runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py version.py ./
COPY core ./core
COPY static ./static
COPY templates ./templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1


# --- production image (requires NVIDIA Container Toolkit) ---
# NVML and driver libraries are injected by the NVIDIA runtime at container start,
# so the app does not need the full CUDA userspace image.
FROM python-runtime AS prod

CMD ["python", "app.py"]


# --- intel image (Intel Arc GPU via xpu-smi, Ubuntu 24.04 + kobuk PPA for Battlemage) ---
FROM ubuntu:24.04 AS intel-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY docker/kobuk-team-ubuntu-intel-graphics-noble.sources /etc/apt/sources.list.d/kobuk-team-ubuntu-intel-graphics-noble.sources

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xpu-smi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app.py version.py ./
COPY core ./core
COPY static ./static
COPY templates ./templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1


FROM intel-runtime AS intel

CMD ["python3", "app.py"]


# --- mixed image (NVIDIA + Intel Arc simultaneously) ---
# NVIDIA: nvidia-ml-py works via NVML library injected at runtime by NVIDIA Container Toolkit
# Intel:  xpu-smi from kobuk PPA (same as intel target)
FROM intel-runtime AS mixed

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=utility,compute

CMD ["python3", "app.py"]


# --- dev image (no NVIDIA driver required, GPU data will be empty) ---
FROM python-runtime AS dev

CMD ["python", "app.py"]
