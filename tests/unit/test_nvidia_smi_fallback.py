"""Tests for core/nvidia_smi_fallback.py"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from core.nvidia_smi_fallback import parse_nvidia_smi, parse_nvidia_smi_fallback


# Realistic CSV output for comprehensive query (31 fields)
FULL_CSV = (
    "0, NVIDIA GeForce RTX 3090, GPU-abc-1234, 535.129.03, 94.02.42.00.A1, "
    "72, 75, 45, 8192, 24576, 16384, 250.00, 350.00, "
    "65, 1800, 1800, 5001, "
    "2100, 2100, 5505, "
    "4, 4, 16, 16, "
    "0, 0.0, 0.0, "
    "P0, Default, "
    "0, 0"
)

# Realistic CSV output for basic query (14 fields)
BASIC_CSV = (
    "0, NVIDIA GeForce RTX 3090, 72, 75, 45, "
    "8192, 24576, 250.00, 350.00, 65, "
    "1800, 1800, 5001, P0"
)

FULL_CSV_581_50 = FULL_CSV.replace("535.129.03", "581.50")


def _make_result(stdout, returncode=0):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


class TestParseNvidiaSmi:
    @patch('subprocess.run')
    def test_success_single_gpu(self, mock_run):
        mock_run.return_value = _make_result(FULL_CSV + "\n")
        data = parse_nvidia_smi()

        assert '0' in data
        gpu = data['0']
        assert gpu['name'] == 'NVIDIA GeForce RTX 3090'
        assert gpu['temperature'] == 72.0
        assert gpu['utilization'] == 75.0
        assert gpu['memory_used'] == 8192.0
        assert gpu['memory_total'] == 24576.0
        assert gpu['power_draw'] == 250.0
        assert gpu['power_limit'] == 350.0
        assert gpu['fan_speed'] == 65.0
        assert gpu['clock_graphics'] == 1800.0
        assert gpu['performance_state'] == 'P0'

    @patch('subprocess.run')
    def test_preserves_driver_version_581_50(self, mock_run):
        mock_run.return_value = _make_result(FULL_CSV_581_50 + "\n")
        data = parse_nvidia_smi()

        assert data['0']['driver_version'] == '581.50'
        assert data['0']['utilization'] == 75.0
        assert data['0']['memory_total'] == 24576.0

    @patch('subprocess.run')
    def test_multi_gpu(self, mock_run):
        gpu0 = FULL_CSV
        gpu1 = FULL_CSV.replace("0, NVIDIA", "1, NVIDIA", 1)
        mock_run.return_value = _make_result(gpu0 + "\n" + gpu1 + "\n")
        data = parse_nvidia_smi()

        assert '0' in data
        assert '1' in data

    @patch('subprocess.run')
    def test_na_values(self, mock_run):
        csv = FULL_CSV.replace("72", "[N/A]").replace("75", "N/A")
        mock_run.return_value = _make_result(csv + "\n")
        data = parse_nvidia_smi()

        gpu = data['0']
        assert gpu['temperature'] == 0  # [N/A] -> 0
        assert gpu['utilization'] == 0  # N/A -> 0

    @patch('subprocess.run')
    def test_fallback_mode_flag(self, mock_run):
        mock_run.return_value = _make_result(FULL_CSV + "\n")
        data = parse_nvidia_smi()
        assert data['0']['_fallback_mode'] is True

    @patch('subprocess.run')
    def test_timestamp_present(self, mock_run):
        mock_run.return_value = _make_result(FULL_CSV + "\n")
        data = parse_nvidia_smi()
        assert 'timestamp' in data['0']

    @patch('subprocess.run')
    def test_failure_falls_back(self, mock_run):
        # First call fails (comprehensive query), second call succeeds (basic)
        mock_run.side_effect = [
            _make_result("", returncode=1),
            _make_result(BASIC_CSV + "\n")
        ]
        data = parse_nvidia_smi()
        assert '0' in data
        assert data['0']['name'] == 'NVIDIA GeForce RTX 3090'

    @patch('subprocess.run')
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='nvidia-smi', timeout=10)
        data = parse_nvidia_smi()
        assert data == {}

    @patch('subprocess.run')
    def test_exception_falls_back(self, mock_run):
        # First call raises, second (fallback) succeeds
        mock_run.side_effect = [
            Exception("weird error"),
            _make_result(BASIC_CSV + "\n")
        ]
        data = parse_nvidia_smi()
        assert '0' in data

    @patch('subprocess.run')
    def test_empty_output(self, mock_run):
        mock_run.return_value = _make_result("")
        data = parse_nvidia_smi()
        assert data == {}


class TestParseNvidiaSmiBasicFallback:
    @patch('subprocess.run')
    def test_success(self, mock_run):
        mock_run.return_value = _make_result(BASIC_CSV + "\n")
        data = parse_nvidia_smi_fallback()

        assert '0' in data
        gpu = data['0']
        assert gpu['name'] == 'NVIDIA GeForce RTX 3090'
        assert gpu['temperature'] == 72.0
        assert gpu['utilization'] == 75.0
        assert gpu['memory_used'] == 8192.0
        assert gpu['_fallback_mode'] is True
        # Basic query doesn't have UUID
        assert gpu['uuid'] == 'N/A'

    @patch('subprocess.run')
    def test_failure(self, mock_run):
        mock_run.return_value = _make_result("", returncode=1)
        data = parse_nvidia_smi_fallback()
        assert data == {}

    @patch('subprocess.run')
    def test_exception(self, mock_run):
        mock_run.side_effect = Exception("fail")
        data = parse_nvidia_smi_fallback()
        assert data == {}

    @patch('subprocess.run')
    def test_memory_free_calculated(self, mock_run):
        mock_run.return_value = _make_result(BASIC_CSV + "\n")
        data = parse_nvidia_smi_fallback()
        gpu = data['0']
        assert gpu['memory_free'] == gpu['memory_total'] - gpu['memory_used']
