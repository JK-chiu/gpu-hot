/**
 * Tests for static/js/chart-manager.js
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Functions are loaded into global scope by setup.js

describe('initGPUData', () => {
    beforeEach(() => {
        // Clear global chart data
        for (const key of Object.keys(chartData)) {
            delete chartData[key];
        }
    });

    it('creates structure with all chart types', () => {
        initGPUData('gpu0');
        const data = chartData['gpu0'];

        expect(data).toBeDefined();
        expect(data.utilization).toBeDefined();
        expect(data.temperature).toBeDefined();
        expect(data.memory).toBeDefined();
        expect(data.power).toBeDefined();
        expect(data.fanSpeed).toBeDefined();
        expect(data.clocks).toBeDefined();
        expect(data.efficiency).toBeDefined();
        expect(data.pcie).toBeDefined();
        expect(data.appclocks).toBeDefined();
        expect(data.encoderDecoder).toBeDefined();
        expect(data.systemCpu).toBeDefined();
        expect(data.systemMemory).toBeDefined();
    });

    it('creates 240 data points per chart', () => {
        initGPUData('gpu0');
        expect(chartData['gpu0'].utilization.data.length).toBe(240);
        expect(chartData['gpu0'].utilization.labels.length).toBe(240);
    });

    it('pre-fills with initial values', () => {
        initGPUData('gpu0', { utilization: 50, temperature: 60 });
        expect(chartData['gpu0'].utilization.data[0]).toBe(50);
        expect(chartData['gpu0'].temperature.data[0]).toBe(60);
    });

    it('defaults to zero when no initial values', () => {
        initGPUData('gpu0');
        expect(chartData['gpu0'].utilization.data[0]).toBe(0);
    });

    it('stores power limit', () => {
        initGPUData('gpu0', { powerLimit: 350 });
        expect(chartData['gpu0']._powerLimit).toBe(350);
    });

    it('clocks has separate data arrays', () => {
        initGPUData('gpu0');
        const clocks = chartData['gpu0'].clocks;
        expect(clocks.graphicsData).toBeDefined();
        expect(clocks.smData).toBeDefined();
        expect(clocks.memoryData).toBeDefined();
        expect(clocks.graphicsData.length).toBe(240);
    });
});

describe('calculateStats', () => {
    it('computes correct stats', () => {
        const stats = calculateStats([10, 20, 30]);
        expect(stats.min).toBe(10);
        expect(stats.max).toBe(30);
        expect(stats.avg).toBe(20);
        expect(stats.current).toBe(30);
    });

    it('returns zeros for empty array', () => {
        const stats = calculateStats([]);
        expect(stats).toEqual({ min: 0, max: 0, avg: 0, current: 0 });
    });

    it('returns zeros for null', () => {
        const stats = calculateStats(null);
        expect(stats).toEqual({ min: 0, max: 0, avg: 0, current: 0 });
    });

    it('filters out non-finite values', () => {
        const stats = calculateStats([10, Infinity, 20, NaN, 30]);
        expect(stats.min).toBe(10);
        expect(stats.max).toBe(30);
        expect(stats.avg).toBe(20);
    });

    it('returns zeros when all values are non-finite', () => {
        const stats = calculateStats([Infinity, NaN, -Infinity]);
        expect(stats).toEqual({ min: 0, max: 0, avg: 0, current: 0 });
    });

    it('handles single value', () => {
        const stats = calculateStats([42]);
        expect(stats.min).toBe(42);
        expect(stats.max).toBe(42);
        expect(stats.avg).toBe(42);
        expect(stats.current).toBe(42);
    });
});

describe('updateChart', () => {
    beforeEach(() => {
        for (const key of Object.keys(chartData)) {
            delete chartData[key];
        }
        for (const key of Object.keys(charts)) {
            delete charts[key];
        }
        // Stub stat display elements
        document.body.innerHTML = '';
    });

    it('auto-initializes missing GPU data', () => {
        updateChart('newGpu', 'utilization', 50);
        expect(chartData['newGpu']).toBeDefined();
    });

    it('pushes single-line value', () => {
        initGPUData('gpu0');
        // Rolling window: starts at 240, push adds 1 then shift removes 1 = still 240
        updateChart('gpu0', 'utilization', 75);
        expect(chartData['gpu0'].utilization.data.length).toBe(240);
        // Last element should be 75
        expect(chartData['gpu0'].utilization.data[239]).toBe(75);
    });

    it('pushes multi-line clocks values', () => {
        initGPUData('gpu0');
        updateChart('gpu0', 'clocks', 1800, 1800, 5001);
        const clocks = chartData['gpu0'].clocks;
        expect(clocks.graphicsData[clocks.graphicsData.length - 1]).toBe(1800);
        expect(clocks.smData[clocks.smData.length - 1]).toBe(1800);
        expect(clocks.memoryData[clocks.memoryData.length - 1]).toBe(5001);
    });

    it('pushes pcie RX/TX values', () => {
        initGPUData('gpu0');
        updateChart('gpu0', 'pcie', 100, 200);
        const pcie = chartData['gpu0'].pcie;
        expect(pcie.dataRX[pcie.dataRX.length - 1]).toBe(100);
        expect(pcie.dataTX[pcie.dataTX.length - 1]).toBe(200);
    });

    it('pushes encoder/decoder values', () => {
        initGPUData('gpu0');
        updateChart('gpu0', 'encoderDecoder', 25, 10);
        const ed = chartData['gpu0'].encoderDecoder;
        expect(ed.dataEnc[ed.dataEnc.length - 1]).toBe(25);
        expect(ed.dataDec[ed.dataDec.length - 1]).toBe(10);
    });

    it('clamps NaN to zero', () => {
        initGPUData('gpu0');
        updateChart('gpu0', 'utilization', NaN);
        const data = chartData['gpu0'].utilization.data;
        expect(data[data.length - 1]).toBe(0);
    });

    it('clamps negative to zero', () => {
        initGPUData('gpu0');
        updateChart('gpu0', 'temperature', -5);
        const data = chartData['gpu0'].temperature.data;
        expect(data[data.length - 1]).toBe(0);
    });

    it('maintains rolling window of 240 points', () => {
        initGPUData('gpu0');
        // Push 5 more values (already 240)
        for (let i = 0; i < 5; i++) {
            updateChart('gpu0', 'utilization', 50 + i);
        }
        expect(chartData['gpu0'].utilization.data.length).toBe(240);
        expect(chartData['gpu0'].utilization.labels.length).toBe(240);
    });

    it('does nothing for null gpuId', () => {
        updateChart(null, 'utilization', 50);
        // Should not throw
    });

    it('does nothing for null chartType', () => {
        initGPUData('gpu0');
        updateChart('gpu0', null, 50);
        // Should not throw
    });
});

describe('isMobile', () => {
    it('returns false for desktop width', () => {
        Object.defineProperty(window, 'innerWidth', { value: 1920, writable: true });
        expect(isMobile()).toBe(false);
    });

    it('returns true for mobile width', () => {
        Object.defineProperty(window, 'innerWidth', { value: 375, writable: true });
        expect(isMobile()).toBe(true);
    });

    it('returns true at threshold', () => {
        Object.defineProperty(window, 'innerWidth', { value: 768, writable: true });
        expect(isMobile()).toBe(true);
    });
});
