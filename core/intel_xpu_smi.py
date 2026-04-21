"""Intel GPU monitoring via xpu-smi and sysfs hwmon (for Intel Arc discrete GPUs)"""

import subprocess
import json
import os
import glob
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Metric IDs for xpu-smi dump — order determines column positions below
# 1=Power(W)  2=Freq(MHz)  3=CoreTemp(C)  4=MemTemp(C)  5=MemUtil(%)
# 6=MemRead(kB/s)  7=MemWrite(kB/s)  8=EnergyConsumed(J)
# 17=MemBWUtil(%)  18=MemUsed(MiB)  19=PCIeRead(kB/s)  20=PCIeWrite(kB/s)  22=Compute(%)
_DUMP_METRICS = '1,2,3,4,5,6,7,8,17,18,19,20,22'
_METRIC_POSITIONS = {
    # offset from column 2 (after Timestamp + DeviceId)
    'power_draw':                   0,
    'clock_graphics':               1,
    'temperature':                  2,  # N/A on some GPUs; hwmon pkg used as fallback
    'temperature_memory':           3,  # N/A on some GPUs; hwmon vram used as fallback
    'memory_utilization':           4,
    'memory_read_bandwidth':        5,
    'memory_write_bandwidth':       6,
    '_energy_consumed_j':           7,  # Joules since driver load; converted to Wh below
    'memory_bandwidth_utilization': 8,
    'memory_used':                  9,
    'pcie_rx_throughput':           10,  # kB/s — same field name as NVIDIA
    'pcie_tx_throughput':           11,
    'utilization':                  12,  # Compute Engine %; N/A on some GPUs
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


# PCIe link speed string → generation number
_PCIE_SPEED_TO_GEN = {
    '2.5': 1, '5.0': 2, '8.0': 3,
    '16.0': 4, '32.0': 5, '64.0': 6,
}


def _parse_pcie_gen(speed_str):
    """'16.0 GT/s PCIe' → 4,  unknown → 'N/A'"""
    num = speed_str.strip().split()[0] if speed_str else ''
    return _PCIE_SPEED_TO_GEN.get(num, 'N/A')


def _sysfs_str(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _hwmon_power_limit_w(drm_device):
    """Read power cap in Watts from hwmon power1_cap (microwatts)."""
    d = _hwmon_dir(drm_device)
    if not d:
        return None
    raw = _read_sysfs_int(f'{d}/power1_cap')
    if raw and raw > 0:
        return raw / 1_000_000.0
    return None


def _throttle_reasons(drm_device):
    """
    Read throttle state from xe driver sysfs.
    Returns 'None' when not throttled, or comma-separated active reason names.
    """
    card = os.path.basename(drm_device)
    base = f'/sys/class/drm/{card}/device'
    active = []
    try:
        for tile in sorted(glob.glob(f'{base}/tile*/gt*/freq0/throttle')):
            status = _sysfs_str(f'{tile}/status')
            if status != '1':
                continue
            for reason_file in sorted(glob.glob(f'{tile}/reason_*')):
                if _sysfs_str(reason_file) == '1':
                    active.append(os.path.basename(reason_file).replace('reason_', ''))
    except Exception:
        pass
    return ', '.join(active) if active else 'None'


def _pcie_info(pci_bdf):
    """Read PCIe gen/width from /sys/bus/pci/devices/{bdf}/."""
    base = f'/sys/bus/pci/devices/{pci_bdf}'
    cur_speed  = _sysfs_str(f'{base}/current_link_speed')
    cur_width  = _sysfs_str(f'{base}/current_link_width')
    max_speed  = _sysfs_str(f'{base}/max_link_speed')
    max_width  = _sysfs_str(f'{base}/max_link_width')
    return {
        'pcie_gen':       _parse_pcie_gen(cur_speed) if cur_speed else 'N/A',
        'pcie_width':     f'x{cur_width}' if cur_width else 'N/A',
        'pcie_gen_max':   _parse_pcie_gen(max_speed) if max_speed else 'N/A',
        'pcie_width_max': f'x{max_width}' if max_width else 'N/A',
    }


def _xe_driver_version():
    """
    xe is a kernel module with no standalone version file.
    Containers share the host kernel, so platform.release() returns the real version.
    """
    import platform
    try:
        return f'xe/{platform.release()}'
    except Exception:
        return 'xe'


# ---------------------------------------------------------------------------
# sysfs hwmon helpers
# ---------------------------------------------------------------------------

def _hwmon_dir(drm_device):
    """Return first hwmon directory for the DRM device, or None."""
    card = os.path.basename(drm_device)
    base = f'/sys/class/drm/{card}/device/hwmon'
    try:
        dirs = [d for d in glob.glob(f'{base}/hwmon*') if os.path.isdir(d)]
        return dirs[0] if dirs else None
    except Exception:
        return None


def _read_sysfs_int(path):
    """Read an integer from a sysfs file, return None on failure."""
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _hwmon_temps(drm_device):
    """
    Read all temp sensors from hwmon.
    Returns dict of {label: celsius_float}, e.g. {'pkg': 49.0, 'vram': 48.0}
    """
    d = _hwmon_dir(drm_device)
    if not d:
        return {}
    result = {}
    for input_path in glob.glob(f'{d}/temp*_input'):
        raw = _read_sysfs_int(input_path)
        if raw is None:
            continue
        label_path = input_path.replace('_input', '_label')
        if os.path.exists(label_path):
            try:
                label = open(label_path).read().strip()
            except Exception:
                label = os.path.basename(input_path).replace('_input', '')
        else:
            label = os.path.basename(input_path).replace('_input', '')
        result[label] = raw / 1000.0
    return result


def _hwmon_fan_rpm(drm_device):
    """
    Read fan RPM values from hwmon.
    Returns max non-zero RPM across all fans, or 0.
    """
    d = _hwmon_dir(drm_device)
    if not d:
        return 0
    max_rpm = 0
    for fan_path in glob.glob(f'{d}/fan*_input'):
        raw = _read_sysfs_int(fan_path)
        if raw and raw > max_rpm:
            max_rpm = raw
    return max_rpm


# ---------------------------------------------------------------------------
# xpu-smi helpers
# ---------------------------------------------------------------------------

def discover_intel_gpus():
    """
    Detect Intel GPUs via xpu-smi discovery.
    Returns {xpu_id_str: {name, drm_device, pci_bus_id, uuid}} or {}.
    memory_total is not available from discovery; it is derived at collection time.
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
            gpus[xpu_id] = {
                'name':        device.get('device_name', 'Intel GPU'),
                'drm_device':  device.get('drm_device', ''),
                'pci_bus_id':  device.get('pci_bdf_address', 'N/A'),
                'uuid':        device.get('uuid', f'intel-{xpu_id}'),
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
    Collect live metrics for all detected Intel GPUs.
    intel_gpu_info: dict returned by discover_intel_gpus()
    Returns {xpu_id_str: metrics_dict} matching the NVIDIA GPU schema.
    """
    if not intel_gpu_info:
        return {}

    results = {}
    for xpu_id, static_info in intel_gpu_info.items():
        metrics = _dump_single_device(xpu_id)
        if metrics is None:
            continue

        drm = static_info.get('drm_device', '')

        # Supplement N/A temperatures from sysfs hwmon
        hwtemps = _hwmon_temps(drm) if drm else {}
        if _safe_float(metrics.get('temperature')) == 0.0 and 'pkg' in hwtemps:
            metrics['temperature'] = hwtemps['pkg']
        if _safe_float(metrics.get('temperature_memory')) == 0.0 and 'vram' in hwtemps:
            metrics['temperature_memory'] = hwtemps['vram']

        # Fan speed and power limit from hwmon
        fan_rpm = _hwmon_fan_rpm(drm) if drm else 0
        power_limit = _hwmon_power_limit_w(drm) if drm else None

        # Throttle reasons from xe sysfs
        throttle = _throttle_reasons(drm) if drm else 'None'

        # Derive memory_total from used/util ratio (no direct API available)
        mem_used = _safe_float(metrics.get('memory_used'))
        mem_util = _safe_float(metrics.get('memory_utilization'))
        if mem_util > 0:
            memory_total = round(mem_used / mem_util * 100)
        else:
            memory_total = 0.0

        pci_bdf = static_info.get('pci_bus_id', '')
        pcie = _pcie_info(pci_bdf) if pci_bdf and pci_bdf != 'N/A' else {}

        data = {
            'index':          xpu_id,
            'name':           static_info['name'],
            'vendor':         'Intel',
            'driver_version': _xe_driver_version(),
            'vbios_version':  '',
            'pci_bus_id':     pci_bdf or 'N/A',
            'memory_total':   memory_total,
            'memory_free':    max(0.0, memory_total - mem_used),
            'timestamp':      datetime.now().isoformat(),
            'uuid':           static_info.get('uuid', f'intel-{xpu_id}'),
            'performance_state':    '',
            'compute_mode':         '',
            'throttle_reasons':     throttle,
            'fan_speed':            fan_rpm,
            'power_limit':          power_limit if power_limit else 1,
            'encoder_utilization':  0,
            'decoder_utilization':  0,
            'encoder_sessions':     0,
            'decoder_sessions':     0,
            'pcie_gen':             pcie.get('pcie_gen', 'N/A'),
            'pcie_gen_max':         pcie.get('pcie_gen_max', 'N/A'),
            'pcie_width':           pcie.get('pcie_width', 'N/A'),
            'pcie_width_max':       pcie.get('pcie_width_max', 'N/A'),
            '_backend':             'xpu-smi',
        }
        data.update(metrics)

        # Arc Battlemage (Xe2): xpu-smi Compute Engine util is N/A on this GPU model.
        # Fall back to memory_utilization as the best activity proxy for LLM workloads.
        if data.get('utilization', 0.0) == 0.0 and data.get('memory_utilization', 0.0) > 0:
            data['utilization'] = data['memory_utilization']

        # Convert energy from Joules → Wh (same field name as NVIDIA path)
        energy_j = _safe_float(data.pop('_energy_consumed_j', None))
        if energy_j > 0:
            data['energy_consumption_wh'] = energy_j / 3600.0

        results[xpu_id] = data

    return results


def _dump_single_device(xpu_id):
    """Run xpu-smi dump for one device and return a partial metrics dict, or None."""
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
    Parse CSV output from xpu-smi dump.

    Header + one data row, columns after Timestamp and DeviceId match _METRIC_POSITIONS.
    Example (metrics 1,2,3,4,5,6,7,17,18,22):
      Timestamp, DeviceId, GPU Power (W), GPU Frequency (MHz), GPU Core Temperature ...
      20:32:58, 0, 32.94, 400, N/A, 50.00, 1.61, 1598, 276, 0, 396.00, N/A
    """
    lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        logger.warning(f"xpu-smi dump: unexpected output for device {device_id}")
        return None

    data_parts = None
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2 + len(_METRIC_POSITIONS) and parts[1].strip() == device_id:
            data_parts = parts
            break

    if data_parts is None:
        last = [p.strip() for p in lines[-1].split(',')]
        if len(last) >= 2 + len(_METRIC_POSITIONS):
            data_parts = last

    if data_parts is None:
        logger.warning(f"xpu-smi dump: no usable data row for device {device_id}")
        return None

    offset = 2
    metrics = {}
    for field, pos in _METRIC_POSITIONS.items():
        col_idx = offset + pos
        if col_idx < len(data_parts):
            metrics[field] = _safe_float(data_parts[col_idx])

    return metrics
