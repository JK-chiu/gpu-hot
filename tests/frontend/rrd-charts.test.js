/**
 * Tests for static/js/rrd-charts.js
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';

function setupRRDDOM(gpuId = '0') {
    document.body.innerHTML = `
        <section class="rrd-history" id="rrd-section-${gpuId}">
            <div class="rrd-tabs">
                <button class="rrd-tab active" data-range="1min">1 min</button>
                <button class="rrd-tab" data-range="5min">5 min</button>
            </div>
            <div class="rrd-charts-grid">
                <div class="rrd-chart-wrap">
                    <span id="rrd-stat-utilization-cur-${gpuId}"></span>
                    <span id="rrd-stat-utilization-avg-${gpuId}"></span>
                    <span id="rrd-stat-utilization-max-${gpuId}"></span>
                    <span id="rrd-stat-utilization-min-${gpuId}"></span>
                    <canvas id="rrd-utilization-${gpuId}"></canvas>
                </div>
                <div class="rrd-chart-wrap">
                    <span id="rrd-stat-temperature-cur-${gpuId}"></span>
                    <span id="rrd-stat-temperature-avg-${gpuId}"></span>
                    <span id="rrd-stat-temperature-max-${gpuId}"></span>
                    <span id="rrd-stat-temperature-min-${gpuId}"></span>
                    <canvas id="rrd-temperature-${gpuId}"></canvas>
                </div>
                <div class="rrd-chart-wrap">
                    <span id="rrd-stat-memory_pct-cur-${gpuId}"></span>
                    <span id="rrd-stat-memory_pct-avg-${gpuId}"></span>
                    <span id="rrd-stat-memory_pct-max-${gpuId}"></span>
                    <span id="rrd-stat-memory_pct-min-${gpuId}"></span>
                    <canvas id="rrd-memory_pct-${gpuId}"></canvas>
                </div>
                <div class="rrd-chart-wrap">
                    <span id="rrd-stat-power_draw-cur-${gpuId}"></span>
                    <span id="rrd-stat-power_draw-avg-${gpuId}"></span>
                    <span id="rrd-stat-power_draw-max-${gpuId}"></span>
                    <span id="rrd-stat-power_draw-min-${gpuId}"></span>
                    <canvas id="rrd-power_draw-${gpuId}"></canvas>
                </div>
            </div>
        </section>
    `;
}

describe('rrd charts', () => {
    beforeEach(() => {
        setupRRDDOM();
    });

    afterEach(() => {
        Object.keys(rrdState).forEach((gpuId) => destroyRRDSection(gpuId));
    });

    it('initializes four charts for a GPU section', () => {
        initRRDSection('0');
        expect(Object.keys(rrdState['0'].charts)).toHaveLength(4);
    });

    it('renders labels and series into charts', () => {
        initRRDSection('0');
        renderRRDCharts('0', {
            labels: ['12:00', '12:01'],
            series: {
                utilization: [40, 60],
                temperature: [70, 71],
                memory_pct: [30, 32],
                power_draw: [200, 210],
            },
        });

        expect(rrdState['0'].charts.utilization.data.labels).toEqual(['12:00', '12:01']);
        expect(rrdState['0'].charts.power_draw.data.datasets[0].data).toEqual([200, 210]);
    });

    it('updates legend values with units', () => {
        updateRRDLegend('0', {
            utilization: { current: 60, avg: 50, max: 75, min: 25 },
            temperature: { current: 71.4, avg: 70.4, max: 72.1, min: 68.9 },
            memory_pct: { current: 32, avg: 31, max: 32, min: 30 },
            power_draw: { current: 210.2, avg: 205.1, max: 212, min: 200 },
        });

        expect(document.getElementById('rrd-stat-utilization-cur-0').textContent).toBe('60%');
        expect(document.getElementById('rrd-stat-temperature-avg-0').textContent).toBe('70.4°C');
        expect(document.getElementById('rrd-stat-power_draw-min-0').textContent).toBe('200W');
    });

    it('destroys charts and removes state', () => {
        initRRDSection('0');
        destroyRRDSection('0');
        expect(rrdState['0']).toBeUndefined();
    });
});
