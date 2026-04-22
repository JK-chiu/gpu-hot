"""Tests for core/handlers.py"""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from core.handlers import monitor_loop


class TestMonitorLoop:
    @pytest.mark.asyncio
    async def test_collects_and_broadcasts(self):
        """Monitor loop collects GPU data and broadcasts to connected clients."""
        monitor = MagicMock()
        monitor.running = True
        monitor.use_smi = {}
        monitor.get_gpu_data = AsyncMock(return_value={'0': {'name': 'RTX 3090', 'utilization': 75}})
        monitor.get_processes = AsyncMock(return_value=[])

        ws = AsyncMock()
        connections = {ws}

        # Stop loop after one iteration
        call_count = [0]
        original_running = True

        async def mock_sleep(interval):
            call_count[0] += 1
            if call_count[0] >= 1:
                monitor.running = False

        with patch('asyncio.sleep', side_effect=mock_sleep), \
             patch('psutil.virtual_memory') as mock_vmem, \
             patch('psutil.cpu_percent', return_value=25.0), \
             patch('psutil.cpu_count', return_value=8), \
             patch('psutil.swap_memory') as mock_swap, \
             patch('psutil.cpu_freq', return_value=None), \
             patch('psutil.getloadavg', return_value=(1.0, 2.0, 3.0)), \
             patch('psutil.net_io_counters') as mock_net, \
             patch('psutil.disk_io_counters', return_value=None):

            mock_vmem.return_value = MagicMock(
                percent=60.0, total=64*1024**3, used=38*1024**3, available=26*1024**3
            )
            mock_swap.return_value = MagicMock(percent=5.0)
            mock_net.return_value = MagicMock(bytes_sent=1000, bytes_recv=2000)

            await monitor_loop(monitor, connections)

        ws.send_text.assert_called_once()
        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert 'gpus' in sent_data
        assert 'system' in sent_data
        assert 'processes' in sent_data

    @pytest.mark.asyncio
    async def test_disconnected_client_removed(self):
        """Clients that raise on send are removed from the connection set."""
        monitor = MagicMock()
        monitor.running = True
        monitor.use_smi = {}
        monitor.get_gpu_data = AsyncMock(return_value={})
        monitor.get_processes = AsyncMock(return_value=[])

        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_text.side_effect = Exception("disconnected")

        connections = {good_ws, bad_ws}

        async def stop_after_one(interval):
            monitor.running = False

        with patch('asyncio.sleep', side_effect=stop_after_one), \
             patch('psutil.virtual_memory') as mock_vmem, \
             patch('psutil.cpu_percent', return_value=10.0), \
             patch('psutil.cpu_count', return_value=4), \
             patch('psutil.swap_memory', side_effect=Exception), \
             patch('psutil.cpu_freq', return_value=None), \
             patch('psutil.getloadavg', side_effect=AttributeError), \
             patch('psutil.net_io_counters', side_effect=Exception), \
             patch('psutil.disk_io_counters', return_value=None):

            mock_vmem.return_value = MagicMock(
                percent=50.0, total=32*1024**3, used=16*1024**3, available=16*1024**3
            )

            await monitor_loop(monitor, connections)

        assert bad_ws not in connections
        assert good_ws in connections

    @pytest.mark.asyncio
    async def test_interval_nvml(self):
        """Uses faster UPDATE_INTERVAL when no GPUs use nvidia-smi."""
        monitor = MagicMock()
        monitor.running = True
        monitor.use_smi = {'0': False}
        monitor.intel_gpus = {}
        monitor.get_gpu_data = AsyncMock(return_value={})
        monitor.get_processes = AsyncMock(return_value=[])

        sleep_intervals = []

        async def capture_sleep(interval):
            sleep_intervals.append(interval)
            monitor.running = False

        with patch('asyncio.sleep', side_effect=capture_sleep), \
             patch('psutil.virtual_memory') as mock_vmem, \
             patch('psutil.cpu_percent', return_value=10.0), \
             patch('psutil.cpu_count', return_value=4), \
             patch('psutil.swap_memory', side_effect=Exception), \
             patch('psutil.cpu_freq', return_value=None), \
             patch('psutil.getloadavg', side_effect=AttributeError), \
             patch('psutil.net_io_counters', side_effect=Exception), \
             patch('psutil.disk_io_counters', return_value=None):

            mock_vmem.return_value = MagicMock(
                percent=50.0, total=32*1024**3, used=16*1024**3, available=16*1024**3
            )

            await monitor_loop(monitor, set())

        assert sleep_intervals[0] == 0.5  # config.UPDATE_INTERVAL

    @pytest.mark.asyncio
    async def test_interval_intel(self):
        """Uses slower NVIDIA_SMI_INTERVAL when Intel GPUs rely on xpu-smi."""
        monitor = MagicMock()
        monitor.running = True
        monitor.use_smi = {'0': False}
        monitor.intel_gpus = {'0': {'name': 'Intel Arc Pro'}}
        monitor.get_gpu_data = AsyncMock(return_value={})
        monitor.get_processes = AsyncMock(return_value=[])

        sleep_intervals = []

        async def capture_sleep(interval):
            sleep_intervals.append(interval)
            monitor.running = False

        with patch('asyncio.sleep', side_effect=capture_sleep), \
             patch('psutil.virtual_memory') as mock_vmem, \
             patch('psutil.cpu_percent', return_value=10.0), \
             patch('psutil.cpu_count', return_value=4), \
             patch('psutil.swap_memory', side_effect=Exception), \
             patch('psutil.cpu_freq', return_value=None), \
             patch('psutil.getloadavg', side_effect=AttributeError), \
             patch('psutil.net_io_counters', side_effect=Exception), \
             patch('psutil.disk_io_counters', return_value=None):

            mock_vmem.return_value = MagicMock(
                percent=50.0, total=32*1024**3, used=16*1024**3, available=16*1024**3
            )

            await monitor_loop(monitor, set())

        assert sleep_intervals[0] == 2.0  # config.NVIDIA_SMI_INTERVAL

    @pytest.mark.asyncio
    async def test_interval_smi(self):
        """Uses slower NVIDIA_SMI_INTERVAL when any GPU uses nvidia-smi."""
        monitor = MagicMock()
        monitor.running = True
        monitor.use_smi = {'0': True}
        monitor.intel_gpus = {}
        monitor.get_gpu_data = AsyncMock(return_value={})
        monitor.get_processes = AsyncMock(return_value=[])

        sleep_intervals = []

        async def capture_sleep(interval):
            sleep_intervals.append(interval)
            monitor.running = False

        with patch('asyncio.sleep', side_effect=capture_sleep), \
             patch('psutil.virtual_memory') as mock_vmem, \
             patch('psutil.cpu_percent', return_value=10.0), \
             patch('psutil.cpu_count', return_value=4), \
             patch('psutil.swap_memory', side_effect=Exception), \
             patch('psutil.cpu_freq', return_value=None), \
             patch('psutil.getloadavg', side_effect=AttributeError), \
             patch('psutil.net_io_counters', side_effect=Exception), \
             patch('psutil.disk_io_counters', return_value=None):

            mock_vmem.return_value = MagicMock(
                percent=50.0, total=32*1024**3, used=16*1024**3, available=16*1024**3
            )

            await monitor_loop(monitor, set())

        assert sleep_intervals[0] == 2.0  # config.NVIDIA_SMI_INTERVAL

    @pytest.mark.asyncio
    async def test_system_info_included(self):
        """System info (CPU, memory, etc.) is included in broadcast."""
        monitor = MagicMock()
        monitor.running = True
        monitor.use_smi = {}
        monitor.get_gpu_data = AsyncMock(return_value={})
        monitor.get_processes = AsyncMock(return_value=[])

        ws = AsyncMock()
        connections = {ws}

        async def stop_after_one(interval):
            monitor.running = False

        with patch('asyncio.sleep', side_effect=stop_after_one), \
             patch('psutil.virtual_memory') as mock_vmem, \
             patch('psutil.cpu_percent', return_value=30.0), \
             patch('psutil.cpu_count', return_value=16), \
             patch('psutil.swap_memory') as mock_swap, \
             patch('psutil.cpu_freq', return_value=MagicMock(current=3600, max=4200)), \
             patch('psutil.getloadavg', return_value=(1.5, 2.0, 1.8)), \
             patch('psutil.net_io_counters') as mock_net, \
             patch('psutil.disk_io_counters') as mock_disk:

            mock_vmem.return_value = MagicMock(
                percent=55.0, total=128*1024**3, used=70*1024**3, available=58*1024**3
            )
            mock_swap.return_value = MagicMock(percent=3.0)
            mock_net.return_value = MagicMock(bytes_sent=5000, bytes_recv=10000)
            mock_disk.return_value = MagicMock(read_bytes=50000, write_bytes=30000)

            await monitor_loop(monitor, connections)

        sent_data = json.loads(ws.send_text.call_args[0][0])
        system = sent_data['system']
        assert system['cpu_percent'] == 30.0
        assert system['memory_percent'] == 55.0
        assert system['cpu_count'] == 16
        assert system['swap_percent'] == 3.0
        assert system['load_avg_1'] == 1.5
        assert system['net_bytes_sent'] == 5000
        assert system['disk_read_bytes'] == 50000
