"""Tests for core/model_detector.py"""

import importlib
import sys
from unittest.mock import MagicMock, patch


def load_model_detector():
    mock_pynvml = MagicMock()
    mock_pynvml.nvmlInit = MagicMock()
    mock_pynvml.nvmlDeviceGetCount = MagicMock(return_value=0)
    mock_pynvml.nvmlSystemGetDriverVersion = MagicMock(return_value=b"535.0")
    mock_pynvml.NVMLError = type('NVMLError', (Exception,), {})

    with patch.dict(sys.modules, {'pynvml': mock_pynvml}):
        sys.modules.pop('core.model_detector', None)
        module = importlib.import_module('core.model_detector')
    return module


class TestModelDetection:
    def test_returns_empty_when_no_runtime_model_found(self):
        model_detector = load_model_detector()

        with patch.object(model_detector, '_scan_all_procs', return_value=(None, [], False)):
            result = model_detector.get_running_models([], gpu_ids=['0'])

        assert result == {}

    def test_prefers_active_ollama_model_over_configured_fallback(self):
        model_detector = load_model_detector()

        with patch.object(model_detector, '_scan_all_procs', return_value=(None, ['gemma4:e4b'], True)):
            result = model_detector.get_running_models([], gpu_ids=['0'])

        assert result == {'0': 'Ollama: gemma4:e4b'}

    def test_uses_runner_specific_model_for_gpu_process(self):
        model_detector = load_model_detector()

        processes = [{'pid': 123, 'gpu_id': '0'}]
        runner_cmdline = ['/usr/bin/ollama', 'runner', '--ollama-engine']

        with patch.object(model_detector, '_read_cmdline', return_value=runner_cmdline), \
             patch.object(model_detector, '_resolve_ollama_runner_model', return_value='gemma4:e4b'), \
             patch.object(model_detector, '_ollama_api_models', return_value=[]):
            result = model_detector.get_running_models(processes, gpu_ids=['0'])

        assert result == {'0': 'Ollama: gemma4:e4b'}
