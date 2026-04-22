"""Detect which AI model is running on each GPU via process inspection."""

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger(__name__)

OLLAMA_MANIFEST_CACHE_TTL = 10
_ollama_manifest_cache = {}


def _read_cmdline(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().decode('utf-8', errors='replace').split('\x00')
    except Exception:
        return []


def _read_environ(pid):
    try:
        with open(f'/proc/{pid}/environ', 'rb') as f:
            raw = f.read().decode('utf-8', errors='replace').split('\x00')
    except Exception:
        return {}

    env = {}
    for entry in raw:
        if not entry or '=' not in entry:
            continue
        key, value = entry.split('=', 1)
        env[key] = value
    return env


def _read_ppid(pid):
    try:
        with open(f'/proc/{pid}/status', 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('PPid:'):
                    return int(line.split(':', 1)[1].strip())
    except Exception:
        return None
    return None


def _ollama_api_models():
    """Return list of model names currently loaded in Ollama."""
    try:
        with urllib.request.urlopen('http://localhost:11434/api/ps', timeout=1) as resp:
            data = json.loads(resp.read())
            return [m['name'] for m in data.get('models', [])]
    except Exception:
        return []


def _extract_ollama_blob(cmdline):
    for i, arg in enumerate(cmdline):
        if arg == '--model' and i + 1 < len(cmdline):
            return os.path.basename(cmdline[i + 1]).removeprefix('sha256-')
        if arg.startswith('--model='):
            return os.path.basename(arg.split('=', 1)[1]).removeprefix('sha256-')
    return None


def _iter_ollama_manifest_roots(pid):
    env = _read_environ(pid)

    ollama_models = env.get('OLLAMA_MODELS', '')
    if ollama_models.startswith('/'):
        yield f'/proc/{pid}/root{ollama_models}/manifests'

    home = env.get('HOME', '/root')
    if home.startswith('/'):
        yield f'/proc/{pid}/root{home}/.ollama/models/manifests'

    yield f'/proc/{pid}/root/root/.ollama/models/manifests'


def _format_ollama_manifest_name(manifest_path, manifest_root):
    rel = os.path.relpath(manifest_path, manifest_root)
    parts = rel.split(os.sep)
    if len(parts) < 3:
        return None

    namespace = parts[1]
    repo_parts = parts[2:-1]
    tag = parts[-1]

    if not repo_parts:
        return None

    repo = '/'.join(repo_parts)
    if namespace == 'library':
        return f'{repo}:{tag}'
    return f'{namespace}/{repo}:{tag}'


def _load_ollama_manifest_index(serve_pid):
    now = time.time()
    cached = _ollama_manifest_cache.get(serve_pid)
    if cached and (now - cached['loaded_at']) < OLLAMA_MANIFEST_CACHE_TTL:
        return cached['by_blob']

    by_blob = {}

    for manifest_root in _iter_ollama_manifest_roots(serve_pid):
        if not os.path.isdir(manifest_root):
            continue

        try:
            for root, _, files in os.walk(manifest_root):
                for filename in files:
                    manifest_path = os.path.join(root, filename)
                    try:
                        with open(manifest_path, 'r', encoding='utf-8', errors='replace') as f:
                            manifest = json.load(f)
                    except Exception:
                        continue

                    model_name = _format_ollama_manifest_name(manifest_path, manifest_root)
                    if not model_name:
                        continue

                    for layer in manifest.get('layers', []):
                        digest = layer.get('digest', '')
                        if not digest.startswith('sha256:'):
                            continue
                        by_blob[digest.removeprefix('sha256:')] = model_name
        except Exception:
            continue

        if by_blob:
            break

    _ollama_manifest_cache[serve_pid] = {
        'loaded_at': now,
        'by_blob': by_blob,
    }
    return by_blob


def _resolve_ollama_runner_model(pid, cmdline=None):
    if cmdline is None:
        cmdline = _read_cmdline(pid)

    if not _is_ollama_runner(cmdline):
        return None

    blob = _extract_ollama_blob(cmdline)
    if not blob:
        return None

    serve_pid = _read_ppid(pid)
    if not serve_pid:
        return None

    manifests = _load_ollama_manifest_index(serve_pid)
    return manifests.get(blob)


def _format_model_summary(prefix, models):
    unique = []
    for model in models:
        if model and model not in unique:
            unique.append(model)

    if not unique:
        return None
    if len(unique) == 1:
        return f'{prefix}: {unique[0]}'
    if len(unique) == 2:
        return f'{prefix}: {unique[0]}, {unique[1]}'
    return f'{prefix}: {unique[0]} +{len(unique) - 1}'


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
    """Scan all /proc/*/cmdline entries, return (vllm_model, ollama_models, ollama_found)."""
    vllm_model = None
    ollama_models = []
    ollama_found = False
    try:
        for entry in os.scandir('/proc'):
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
                cmdline = _read_cmdline(pid)
                if not cmdline or not any(cmdline):
                    continue
                if not vllm_model:
                    m = _extract_vllm_model(cmdline)
                    if m:
                        vllm_model = m
                if _is_ollama_runner(cmdline):
                    ollama_found = True
                    model = _resolve_ollama_runner_model(pid, cmdline)
                    if model and model not in ollama_models:
                        ollama_models.append(model)
                if vllm_model and ollama_models:
                    break
            except Exception:
                continue
    except Exception:
        pass
    return vllm_model, ollama_models, ollama_found


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
            model = _resolve_ollama_runner_model(int(pid), cmdline)
            if model:
                gpu_models[gpu_id] = f'Ollama: {model}'
            else:
                ollama_gpu_ids.add(gpu_id)

    if ollama_gpu_ids:
        names = _ollama_api_models()
        if names:
            for gid in ollama_gpu_ids:
                if gid not in gpu_models:
                    gpu_models[gid] = f'Ollama: {names[0]}'

    # --- Pass 2: fallback full /proc scan (Intel xpu-smi doesn't report PIDs) ---
    if not gpu_models and gpu_ids:
        vllm_model, ollama_models, ollama_found = _scan_all_procs()
        if vllm_model:
            for gid in gpu_ids:
                gpu_models[gid] = f'vLLM: {vllm_model}'
        elif ollama_models:
            label = _format_model_summary('Ollama', ollama_models)
            if label:
                for gid in gpu_ids:
                    gpu_models[gid] = label
        elif ollama_found:
            names = _ollama_api_models()
            if names:  # Only show when a model is actually loaded
                for gid in gpu_ids:
                    gpu_models[gid] = f'Ollama: {names[0]}'

    return gpu_models
