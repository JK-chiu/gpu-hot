# syntax=docker/dockerfile:1.7

# --- shared Python runtime for lightweight targets ---
FROM python:3.11-slim-bookworm AS python-runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::ForceIPv4=true update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

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


# --- intel image (Intel Arc GPU via xpu-smi, host-matched Ubuntu 25.10 userspace) ---
FROM ubuntu:25.10 AS intel-base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY docker/ubuntu-questing.sources /etc/apt/sources.list.d/ubuntu.sources
COPY docker/debs/ /tmp/debs/

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::ForceIPv4=true update \
    && apt-get install -y --no-install-recommends \
    python3 \
    curl \
    ca-certificates \
    /tmp/debs/*.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/debs

FROM intel-base AS intel-builder

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::ForceIPv4=true update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt


FROM intel-base AS intel-runtime

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY --from=intel-builder /opt/venv /opt/venv

COPY app.py version.py ./
COPY core ./core
COPY static ./static
COPY templates ./templates

EXPOSE 1312

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:1312/api/gpu-data || exit 1


FROM intel-runtime AS intel

CMD ["python", "app.py"]


# --- mixed image (NVIDIA + Intel Arc simultaneously) ---
# NVIDIA: nvidia-ml-py works via NVML library injected at runtime by NVIDIA Container Toolkit
# Intel:  xpu-smi from kobuk PPA (same as intel target)
FROM intel-runtime AS mixed

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=utility,compute

CMD ["python", "app.py"]


# --- dev image (no NVIDIA driver required, GPU data will be empty) ---
FROM python-runtime AS dev

CMD ["python", "app.py"]
