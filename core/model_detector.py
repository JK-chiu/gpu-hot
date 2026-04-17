"""Detect which AI model is running on each GPU via process inspection."""

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)


def _read_cmdline(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().decode('utf-8', errors='replace').split('\x00')
    except Exception:
        return []


def _ollama_api_models():
    """Return list of model names currently loaded in Ollama."""
    try:
        with urllib.request.urlopen('http://localhost:11434/api/ps', timeout=1) as resp:
            data = json.loads(resp.read())
            return [m['name'] for m in data.get('models', [])]
    except Exception:
        return []


def _extract_vllm_model(cmdline):
    joined = ' '.join(cmdline)
    if 'vllm' not in joined:
        return None
    for i, arg in enumerate(cmdline):
        if arg == '--model' and i + 1 < len(cmdline):
            return cmdline[i + 1].split('/')[-1]
        if arg.startswith('--model='):
            return arg.split('=', 1)[1].split('/')[-1]
    # vllm serve <model>
    for i, arg in enumerate(cmdline):
        if arg == 'serve' and i + 1 < len(cmdline):
            candidate = cmdline[i + 1]
            if candidate and not candidate.startswith('-'):
                return candidate.split('/')[-1]
    return None


def _is_ollama_runner(cmdline):
    # Match only the model runner subprocess, not the server daemon (ollama serve)
    joined = ' '.join(cmdline)
    return 'ollama' in joined and 'runner' in joined


def _scan_all_procs():
    """Scan all /proc/*/cmdline entries, return (vllm_model, ollama_found)."""
    vllm_model = None
    ollama_found = False
    try:
        import os
        for entry in os.scandir('/proc'):
            if not entry.name.isdigit():
                continue
            try:
                cmdline = _read_cmdline(int(entry.name))
                if not cmdline or not any(cmdline):
                    continue
                if not vllm_model:
                    m = _extract_vllm_model(cmdline)
                    if m:
                        vllm_model = m
                if not ollama_found and _is_ollama_runner(cmdline):
                    ollama_found = True
                if vllm_model and ollama_found:
                    break
            except Exception:
                continue
    except Exception:
        pass
    return vllm_model, ollama_found


def get_running_models(processes, gpu_ids=None):
    """
    Return a dict mapping gpu_id -> model_name.
    First tries to match via GPU process PIDs (NVIDIA/NVML path).
    Falls back to scanning all /proc entries (Intel/xpu-smi path).
    """
    gpu_models = {}
    ollama_gpu_ids = set()

    # --- Pass 1: match via GPU-reported PIDs (works with NVML) ---
    for proc in processes:
        pid = proc.get('pid')
        gpu_id = proc.get('gpu_id')
        if not pid or gpu_id is None:
            continue
        try:
            cmdline = _read_cmdline(int(pid))
        except (ValueError, TypeError):
            continue
        if not cmdline:
            continue
        vllm_model = _extract_vllm_model(cmdline)
        if vllm_model:
            gpu_models[gpu_id] = f'vLLM: {vllm_model}'
            continue
        if _is_ollama_runner(cmdline):
            ollama_gpu_ids.add(gpu_id)

    if ollama_gpu_ids:
        names = _ollama_api_models()
        if names:
            for gid in ollama_gpu_ids:
                if gid not in gpu_models:
                    gpu_models[gid] = f'Ollama: {names[0]}'

    # --- Pass 2: fallback full /proc scan (Intel xpu-smi doesn't report PIDs) ---
    if not gpu_models and gpu_ids:
        vllm_model, ollama_found = _scan_all_procs()
        if vllm_model:
            for gid in gpu_ids:
                gpu_models[gid] = f'vLLM: {vllm_model}'
        elif ollama_found:
            names = _ollama_api_models()
            if names:  # Only show when a model is actually loaded
                for gid in gpu_ids:
                    gpu_models[gid] = f'Ollama: {names[0]}'

    return gpu_models
