/**
 * Tests for static/js/ui.js
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Globals loaded by setup.js: switchToView, ensureGPUTab, removeGPUTab,
// autoSwitchSingleGPU, currentTab, registeredGPUs, charts, chartData

function setupDOM() {
    document.body.innerHTML = `
        <div id="view-selector">
            <button class="sidebar-btn active" data-view="overview">Overview</button>
        </div>
        <div id="tab-overview" class="tab-content active">
            <div id="overview-grid"></div>
        </div>
    `;
}

beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
            labels: ['00:00:00'],
            series: {
                utilization: [50],
                temperature: [70],
                memory_pct: [40],
                power_draw: [200],
            },
            stats: {
                utilization: { current: 50, avg: 50, max: 50, min: 50 },
                temperature: { current: 70, avg: 70, max: 70, min: 70 },
                memory_pct: { current: 40, avg: 40, max: 40, min: 40 },
                power_draw: { current: 200, avg: 200, max: 200, min: 200 },
            },
        }),
    });
});

afterEach(() => {
    Object.keys(rrdState).forEach((gpuId) => destroyRRDSection(gpuId));
    vi.restoreAllMocks();
});

describe('switchToView', () => {
    beforeEach(() => {
        setupDOM();
        global.currentTab = 'overview';
    });

    it('updates currentTab', () => {
        switchToView('overview');
        expect(global.currentTab).toBe('overview');
    });

    it('sets active class on correct button', () => {
        switchToView('overview');
        const btn = document.querySelector('[data-view="overview"]');
        expect(btn.classList.contains('active')).toBe(true);
    });

    it('does nothing for null viewName', () => {
        switchToView(null);
        // Should not throw
    });

    it('makes target tab visible', () => {
        const tab = document.getElementById('tab-overview');
        switchToView('overview');
        expect(tab.classList.contains('active')).toBe(true);
    });
});

describe('ensureGPUTab', () => {
    beforeEach(() => {
        setupDOM();
        global.registeredGPUs = new Set();
        global.charts = {};
        for (const key of Object.keys(chartData)) {
            delete chartData[key];
        }
    });

    it('creates sidebar button on first call', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('0', gpuInfo, false);

        const btn = document.querySelector('[data-view="gpu-0"]');
        expect(btn).not.toBeNull();
        expect(global.registeredGPUs.has('0')).toBe(true);
    });

    it('creates tab content', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('0', gpuInfo, false);

        const tab = document.getElementById('tab-gpu-0');
        expect(tab).not.toBeNull();
    });

    it('initializes RRD history section on first render', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50, memory_used: 4096, memory_total: 8192 };
        ensureGPUTab('0', gpuInfo, false);

        expect(document.getElementById('rrd-section-0')).not.toBeNull();
        expect(rrdState['0']).toBeDefined();
        expect(fetch).toHaveBeenCalledWith('/api/rrd/0?range=1min');
    });

    it('is idempotent — does not duplicate', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('0', gpuInfo, false);
        ensureGPUTab('0', gpuInfo, false);

        const buttons = document.querySelectorAll('[data-view="gpu-0"]');
        expect(buttons.length).toBe(1);
    });

    it('shows last segment for cluster IDs', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('server-2-0', gpuInfo, false);

        const btn = document.querySelector('[data-view="gpu-server-2-0"]');
        expect(btn.textContent).toBe('0');
    });
});

describe('removeGPUTab', () => {
    beforeEach(() => {
        setupDOM();
        global.registeredGPUs = new Set();
        global.charts = {};
        global.currentTab = 'overview';
        for (const key of Object.keys(chartData)) {
            delete chartData[key];
        }
    });

    it('removes button and tab', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('0', gpuInfo, false);
        removeGPUTab('0');

        expect(document.querySelector('[data-view="gpu-0"]')).toBeNull();
        expect(document.getElementById('tab-gpu-0')).toBeNull();
        expect(global.registeredGPUs.has('0')).toBe(false);
    });

    it('switches to overview if current tab removed', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('0', gpuInfo, false);
        global.currentTab = 'gpu-0';
        removeGPUTab('0');

        expect(global.currentTab).toBe('overview');
    });

    it('destroys charts', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50 };
        ensureGPUTab('0', gpuInfo, false);

        const mockChart = { destroy: () => {} };
        global.charts['0'] = { utilization: mockChart };
        removeGPUTab('0');

        expect(global.charts['0']).toBeUndefined();
    });

    it('destroys RRD state', () => {
        const gpuInfo = { name: 'RTX 3090', utilization: 50, memory_used: 4096, memory_total: 8192 };
        ensureGPUTab('0', gpuInfo, false);
        expect(rrdState['0']).toBeDefined();

        removeGPUTab('0');

        expect(rrdState['0']).toBeUndefined();
    });

    it('no-op for unregistered GPU', () => {
        removeGPUTab('999');
        // Should not throw
    });
});

describe('autoSwitchSingleGPU', () => {
    beforeEach(() => {
        setupDOM();
        global.hasAutoSwitched = false;
        global.currentTab = 'overview';
    });

    it('switches to single GPU view', async () => {
        // Create a tab for the GPU so switchToView has a target
        const tab = document.createElement('div');
        tab.id = 'tab-gpu-0';
        tab.className = 'tab-content';
        document.body.appendChild(tab);

        const btn = document.createElement('button');
        btn.className = 'sidebar-btn';
        btn.dataset.view = 'gpu-0';
        document.getElementById('view-selector').appendChild(btn);

        autoSwitchSingleGPU(1, ['0']);

        // Wait for setTimeout(300ms)
        await new Promise(r => setTimeout(r, 350));
        expect(global.currentTab).toBe('gpu-0');
        expect(global.hasAutoSwitched).toBe(true);
    });

    it('does not switch with multiple GPUs', () => {
        autoSwitchSingleGPU(2, ['0', '1']);
        expect(global.currentTab).toBe('overview');
        expect(global.hasAutoSwitched).toBe(false);
    });

    it('only switches once', async () => {
        const tab = document.createElement('div');
        tab.id = 'tab-gpu-0';
        tab.className = 'tab-content';
        document.body.appendChild(tab);

        const btn = document.createElement('button');
        btn.className = 'sidebar-btn';
        btn.dataset.view = 'gpu-0';
        document.getElementById('view-selector').appendChild(btn);

        autoSwitchSingleGPU(1, ['0']);
        autoSwitchSingleGPU(1, ['0']);

        await new Promise(r => setTimeout(r, 350));
        expect(global.hasAutoSwitched).toBe(true);
    });
});
