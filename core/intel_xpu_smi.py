"""Intel GPU monitoring via xpu-smi (for Intel Arc discrete GPUs)"""

import subprocess
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Metric IDs requested from xpu-smi dump (in order)
# 0=GPU Utilization, 1=GPU Power, 2=GPU Frequency, 3=Core Temp, 4=Mem Temp, 5=Mem Used, 6=Mem Utilization
_DUMP_METRICS = '0,1,2,3,4,5,6'
_METRIC_POSITIONS = {
    # column index offset (after Timestamp and DeviceId columns = offset 2)
    'utilization': 0,
    'power_draw': 1,
    'clock_graphics': 2,
    'temperature': 3,
    'temperature_memory': 4,
    'memory_used': 5,
    'memory_utilization': 6,
}


def _safe_float(value, default=0.0):
    if value is None:
        return default
    s = str(value).strip()
    if s in ('N/A', '', '-', 'null'):
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def discover_intel_gpus():
    """
    Detect Intel GPUs via xpu-smi discovery.
    Returns dict of {xpu_device_id_str: {name, memory_total, driver_version, ...}}
    or empty dict if xpu-smi is unavailable or no Intel GPUs are found.
    """
    try:
        result = subprocess.run(
            ['xpu-smi', 'discovery', '-j'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            logger.debug(f"xpu-smi discovery exited {result.returncode}: {result.stderr.strip()}")
            return {}

        data = json.loads(result.stdout)
        gpus = {}
        for device in data.get('device_list', []):
            xpu_id = str(device.get('device_id', 0))
            mem_mib = _safe_float(device.get('max_mem_size_mib', 0))
            gpus[xpu_id] = {
                'name': device.get('device_name', 'Intel GPU'),
                'driver_version': device.get('driver_version', 'N/A'),
                'memory_total': mem_mib,
                'pci_bus_id': device.get('pci_bdf_address', 'N/A'),
                'firmware_version': device.get('gfx_firmware_version', 'N/A'),
            }
        return gpus

    except FileNotFoundError:
        logger.debug("xpu-smi not found — Intel GPU monitoring unavailable")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"xpu-smi discovery JSON parse error: {e}")
        return {}
    except subprocess.TimeoutExpired:
        logger.error("xpu-smi discovery timed out")
        return {}
    except Exception as e:
        logger.error(f"xpu-smi discovery error: {e}")
        return {}


def collect_intel_gpu_metrics(intel_gpu_info):
    """
    Collect live metrics for all detected Intel GPUs in one pass.
    intel_gpu_info: dict returned by discover_intel_gpus()

    Returns dict of {xpu_device_id_str: metrics_dict} with fields that
    match the schema used by NVIDIA GPUs (name, utilization, memory_used, etc.)
    """
    if not intel_gpu_info:
        return {}

    results = {}
    for xpu_id, static_info in intel_gpu_info.items():
        metrics = _dump_single_device(xpu_id)
        if metrics is None:
            continue

        # Merge static info (from discovery) with live metrics
        data = {
            'index': xpu_id,
            'name': static_info['name'],
            'vendor': 'Intel',
            'driver_version': static_info['driver_version'],
            'vbios_version': static_info.get('firmware_version', 'N/A'),
            'pci_bus_id': static_info.get('pci_bus_id', 'N/A'),
            'memory_total': static_info['memory_total'],
            'timestamp': datetime.now().isoformat(),
            # Defaults for fields the frontend may expect
            'uuid': f"intel-{xpu_id}",
            'performance_state': 'N/A',
            'compute_mode': 'N/A',
            'throttle_reasons': 'None',
            'fan_speed': 0,
            'encoder_utilization': 0,
            'decoder_utilization': 0,
            'encoder_sessions': 0,
            'decoder_sessions': 0,
            'pcie_gen': 'N/A',
            'pcie_gen_max': 'N/A',
            'pcie_width': 'N/A',
            'pcie_width_max': 'N/A',
        }
        data.update(metrics)

        # Derive memory_free if both totals are known
        if data['memory_total'] > 0 and 'memory_used' in data:
            data['memory_free'] = max(0.0, data['memory_total'] - data['memory_used'])

        results[xpu_id] = data

    return results


def _dump_single_device(xpu_id):
    """
    Run xpu-smi dump for one device and return a partial metrics dict.
    Returns None on failure.
    """
    try:
        result = subprocess.run(
            ['xpu-smi', 'dump', '-d', xpu_id, '-m', _DUMP_METRICS, '-n', '1'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            logger.warning(f"xpu-smi dump failed for device {xpu_id}: {result.stderr.strip()}")
            return None

        return _parse_dump_output(result.stdout, xpu_id)

    except subprocess.TimeoutExpired:
        logger.error(f"xpu-smi dump timed out for device {xpu_id}")
        return None
    except Exception as e:
        logger.error(f"xpu-smi dump error for device {xpu_id}: {e}")
        return None


def _parse_dump_output(output, device_id):
    """
    Parse xpu-smi dump CSV output.

    Expected format (header + one data row):
      Timestamp, DeviceId, GPU Utilization (%), GPU Power (W), GPU Frequency (MHz),
      GPU Core Temperature (Celsius Degree), GPU Memory Temperature (Celsius Degree),
      GPU Memory Used (MiB), GPU Memory Utilization (%)
      2024-01-15T10:00:00.123, 0, 50.00, 80.00, 2050.00, 62.00, 56.00, 4096.00, 25.00
    """
    lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        logger.warning(f"xpu-smi dump: unexpected output for device {device_id}")
        return None

    # Find data row: skip header, pick the row whose DeviceId column matches
    data_parts = None
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(',')]
        # Column layout: [Timestamp, DeviceId, metric0, metric1, ...]
        if len(parts) >= 2 + len(_METRIC_POSITIONS) and parts[1] == device_id:
            data_parts = parts
            break

    if data_parts is None:
        # Fallback: use the last non-header line
        last = [p.strip() for p in lines[-1].split(',')]
        if len(last) >= 2 + len(_METRIC_POSITIONS):
            data_parts = last

    if data_parts is None:
        logger.warning(f"xpu-smi dump: no usable data row for device {device_id}")
        return None

    # data_parts[0] = timestamp, [1] = device_id, [2..] = metrics in _DUMP_METRICS order
    offset = 2
    metrics = {}
    for field, pos in _METRIC_POSITIONS.items():
        col_idx = offset + pos
        if col_idx < len(data_parts):
            metrics[field] = _safe_float(data_parts[col_idx])

    return metrics
