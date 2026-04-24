"""Async WebSocket handlers for real-time monitoring"""

import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import datetime

import psutil
from fastapi import WebSocket

from . import config
from .model_detector import get_running_models

logger = logging.getLogger(__name__)

# Global WebSocket connections
websocket_connections = set()


def _has_detected_intel_gpus(monitor):
    """Return True only when monitor exposes a real non-empty Intel GPU mapping."""
    intel_gpus = getattr(monitor, 'intel_gpus', None)
    return isinstance(intel_gpus, Mapping) and bool(intel_gpus)


def register_handlers(app, monitor, rrd_buffer=None):
    """Register FastAPI WebSocket handlers"""
    
    @app.websocket("/socket.io/")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        websocket_connections.add(websocket)
        logger.debug('Dashboard client connected')
        
        if not monitor.running:
            monitor.running = True
            asyncio.create_task(monitor_loop(monitor, websocket_connections, rrd_buffer))
        
        try:
            # Keep connection alive
            while True:
                await websocket.receive_text()
        except Exception as e:
            logger.debug(f'Dashboard client disconnected: {e}')
        finally:
            websocket_connections.discard(websocket)


async def monitor_loop(monitor, connections, rrd_buffer=None):
    """Async background loop that collects and emits GPU data"""
    # Use slower interval when any GPU relies on a subprocess tool (nvidia-smi or xpu-smi)
    uses_nvidia_smi = any(monitor.use_smi.values()) if hasattr(monitor, 'use_smi') else False
    has_intel = _has_detected_intel_gpus(monitor)
    uses_subprocess = uses_nvidia_smi or has_intel
    update_interval = config.NVIDIA_SMI_INTERVAL if uses_subprocess else config.UPDATE_INTERVAL

    if uses_nvidia_smi and has_intel:
        logger.info(f"Using subprocess polling interval: {update_interval}s (nvidia-smi + xpu-smi)")
    elif has_intel:
        logger.info(f"Using xpu-smi polling interval: {update_interval}s")
    elif uses_nvidia_smi:
        logger.info(f"Using nvidia-smi polling interval: {update_interval}s")
    else:
        logger.info(f"Using NVML polling interval: {update_interval}s")
    
    while monitor.running:
        try:
            # Collect data concurrently
            gpu_data, processes = await asyncio.gather(
                monitor.get_gpu_data(),
                monitor.get_processes()
            )

            if rrd_buffer is not None:
                try:
                    for gpu_id, gpu_info in gpu_data.items():
                        rrd_buffer.record(str(gpu_id), gpu_info)
                except Exception as e:
                    logger.debug(f"RRD record error: {e}")
            
            # Core system metrics
            vmem = psutil.virtual_memory()
            system_info = {
                'cpu_percent': psutil.cpu_percent(percpu=False),
                'memory_percent': vmem.percent,
                'memory_total_gb': round(vmem.total / (1024 ** 3), 2),
                'memory_used_gb': round(vmem.used / (1024 ** 3), 2),
                'memory_available_gb': round(vmem.available / (1024 ** 3), 2),
                'cpu_count': psutil.cpu_count(),
                'timestamp': datetime.now().isoformat()
            }

            # Swap memory
            try:
                swap = psutil.swap_memory()
                system_info['swap_percent'] = swap.percent
            except Exception:
                pass

            # CPU frequency
            try:
                freq = psutil.cpu_freq()
                if freq:
                    system_info['cpu_freq_current'] = round(freq.current, 0)
                    system_info['cpu_freq_max'] = round(freq.max, 0)
            except Exception:
                pass

            # Load average (Linux/Mac only)
            try:
                load = psutil.getloadavg()
                system_info['load_avg_1'] = round(load[0], 2)
                system_info['load_avg_5'] = round(load[1], 2)
                system_info['load_avg_15'] = round(load[2], 2)
            except (AttributeError, OSError):
                pass

            # Network I/O (cumulative bytes — frontend computes rate)
            try:
                net = psutil.net_io_counters()
                system_info['net_bytes_sent'] = net.bytes_sent
                system_info['net_bytes_recv'] = net.bytes_recv
            except Exception:
                pass

            # Disk I/O (cumulative bytes — frontend computes rate)
            try:
                disk = psutil.disk_io_counters()
                if disk:
                    system_info['disk_read_bytes'] = disk.read_bytes
                    system_info['disk_write_bytes'] = disk.write_bytes
            except Exception:
                pass
            
            try:
                running_models = get_running_models(processes, gpu_ids=list(gpu_data.keys()))
                for gpu_id, model in running_models.items():
                    if gpu_id in gpu_data:
                        gpu_data[gpu_id]['_running_model'] = model
            except Exception as e:
                logger.debug(f"Model detection error: {e}")

            data = {
                'mode': config.MODE,
                'node_name': config.NODE_NAME,
                'gpus': gpu_data,
                'processes': processes,
                'system': system_info,
            }
            
            # Send to all connected clients (iterate over copy to avoid "Set changed size during iteration")
            if connections:
                disconnected = set()
                for websocket in list(connections):
                    try:
                        await websocket.send_text(json.dumps(data))
                    except Exception:
                        disconnected.add(websocket)
                connections -= disconnected
            
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
        
        await asyncio.sleep(update_interval)
