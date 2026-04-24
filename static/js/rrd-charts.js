/**
 * Historical RRD charts for each GPU detail tab.
 * Loaded as a global script to match the rest of the dashboard.
 */

const rrdState = {};

const RRD_REFRESH_MS = {
    '1min': 10_000,
    '5min': 30_000,
    '30min': 60_000,
    '2hr': 120_000,
    '1day': 300_000,
};

const RRD_METRICS = {
    utilization: {
        label: 'Utilization',
        unit: '%',
        yMax: 100,
        yStepSize: 50,
        color: 'rgba(255, 255, 255, 0.72)',
        fillTop: 'rgba(255, 255, 255, 0.10)',
        fillBottom: 'rgba(255, 255, 255, 0.01)',
    },
    temperature: {
        label: 'Temperature',
        unit: '°C',
        ySuggestedMax: 90,
        yStepSize: 30,
        color: 'rgba(255, 255, 255, 0.65)',
        fillTop: 'rgba(255, 255, 255, 0.09)',
        fillBottom: 'rgba(255, 255, 255, 0.01)',
    },
    memory_pct: {
        label: 'Memory',
        unit: '%',
        yMax: 100,
        yStepSize: 50,
        color: 'rgba(255, 255, 255, 0.58)',
        fillTop: 'rgba(255, 255, 255, 0.08)',
        fillBottom: 'rgba(255, 255, 255, 0.01)',
    },
    power_draw: {
        label: 'Power',
        unit: 'W',
        ySuggestedMax: 150,
        yStepSize: 100,
        color: 'rgba(255, 255, 255, 0.50)',
        fillTop: 'rgba(255, 255, 255, 0.07)',
        fillBottom: 'rgba(255, 255, 255, 0.01)',
    },
};

function createRRDChartConfig(metricKey, canvas) {
    const metric = RRD_METRICS[metricKey];
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement ? canvas.parentElement.getBoundingClientRect() : { height: 110 };
    const height = rect.height > 0 ? rect.height : 110;
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, metric.fillTop);
    gradient.addColorStop(1, metric.fillBottom);

    const gridColor = typeof SPARK !== 'undefined' ? SPARK.grid : 'rgba(255, 255, 255, 0.04)';
    const tickColor = typeof SPARK !== 'undefined' ? SPARK.tick : 'rgba(255, 255, 255, 0.4)';
    const tooltipBg = typeof SPARK !== 'undefined' ? SPARK.tooltipBg : '#171b22';

    const config = {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: metric.label,
                data: [],
                borderColor: metric.color,
                backgroundColor: gradient,
                borderWidth: 1.5,
                tension: 0.28,
                fill: true,
                spanGaps: true,
                pointRadius: 0,
                pointHitRadius: 8,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                intersect: false,
                mode: 'index',
            },
            elements: {
                point: { radius: 0, hitRadius: 8 },
                line: { borderCapStyle: 'round', borderJoinStyle: 'round' },
            },
            layout: {
                padding: { left: 0, right: 0, top: 2, bottom: 0 },
            },
            scales: {
                x: {
                    display: true,
                    grid: { display: false },
                    ticks: {
                        color: tickColor,
                        maxTicksLimit: 6,
                        autoSkip: true,
                        font: { size: 10, family: "'SF Mono', 'Menlo', 'Consolas', monospace" },
                    },
                    border: { display: false },
                },
                y: {
                    min: 0,
                    display: true,
                    position: 'right',
                    grid: {
                        color: gridColor,
                        drawBorder: false,
                        lineWidth: 1,
                    },
                    ticks: {
                        color: tickColor,
                        padding: 8,
                        maxTicksLimit: 4,
                        font: { size: 10, family: "'SF Mono', 'Menlo', 'Consolas', monospace" },
                    },
                    border: { display: false },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: tooltipBg,
                    titleColor: '#eef0f4',
                    bodyColor: 'rgba(238, 240, 244, 0.7)',
                    borderWidth: 0,
                    cornerRadius: 4,
                    padding: 8,
                    titleFont: { size: 11, weight: '600' },
                    bodyFont: { size: 11 },
                    callbacks: {
                        label(context) {
                            const value = context.parsed.y;
                            if (value == null) return `${metric.label}: --`;
                            return `${metric.label}: ${formatRRDValue(metricKey, value)}${metric.unit}`;
                        },
                    },
                },
            },
        },
    };

    if (metric.yMax !== undefined) {
        config.options.scales.y.max = metric.yMax;
    }
    if (metric.ySuggestedMax !== undefined) {
        config.options.scales.y.suggestedMax = metric.ySuggestedMax;
    }
    if (metric.yStepSize !== undefined) {
        config.options.scales.y.ticks.stepSize = metric.yStepSize;
    }
    config.options.scales.y.ticks.callback = (value) => `${value}${metric.unit}`;

    return config;
}

function formatRRDValue(metricKey, value) {
    if (value == null || !isFinite(value)) return '--';
    if (metricKey === 'temperature' || metricKey === 'power_draw') {
        return value.toFixed(1).replace(/\.0$/, '');
    }
    return Math.round(value).toString();
}

function _getRRDPowerMax(gpuId) {
    if (typeof chartData !== 'undefined' && chartData[gpuId] && chartData[gpuId]._powerLimit > 0) {
        return chartData[gpuId]._powerLimit;
    }
    return null;
}

function applyRRDPowerMax(gpuId, powerMax) {
    const state = rrdState[gpuId];
    if (!state || !state.charts.power_draw) return;
    const chart = state.charts.power_draw;
    if (powerMax > 0) {
        chart.options.scales.y.max = powerMax;
        const step = powerMax <= 200 ? 50 : powerMax <= 400 ? 100 : 200;
        chart.options.scales.y.ticks.stepSize = step;
    } else {
        delete chart.options.scales.y.max;
        chart.options.scales.y.suggestedMax = RRD_METRICS.power_draw.ySuggestedMax;
    }
    chart.update('none');
}

function initRRDSection(gpuId) {
    const section = document.getElementById(`rrd-section-${gpuId}`);
    if (!section || typeof Chart === 'undefined') return;

    if (!rrdState[gpuId]) {
        rrdState[gpuId] = {
            charts: {},
            activeRange: '1min',
            refreshTimer: null,
            requestToken: 0,
        };
    }

    const state = rrdState[gpuId];
    Object.keys(RRD_METRICS).forEach((metricKey) => {
        if (state.charts[metricKey]) return;
        const canvas = document.getElementById(`rrd-${metricKey}-${gpuId}`);
        if (!canvas) return;
        state.charts[metricKey] = new Chart(canvas, createRRDChartConfig(metricKey, canvas));
    });

    const powerMax = _getRRDPowerMax(gpuId);
    if (powerMax) applyRRDPowerMax(gpuId, powerMax);
}

function setActiveRRDRange(gpuId, range) {
    initRRDSection(gpuId);
    const state = rrdState[gpuId];
    if (!state) return;

    state.activeRange = range;
    state.requestToken += 1;

    const section = document.getElementById(`rrd-section-${gpuId}`);
    if (section) {
        section.querySelectorAll('.rrd-tab').forEach((button) => {
            button.classList.toggle('active', button.dataset.range === range);
        });
    }

    if (state.refreshTimer) {
        clearInterval(state.refreshTimer);
        state.refreshTimer = null;
    }

    loadRRDRange(gpuId, range);
    state.refreshTimer = window.setInterval(() => {
        loadRRDRange(gpuId, range);
    }, RRD_REFRESH_MS[range] || RRD_REFRESH_MS['1min']);
}

async function loadRRDRange(gpuId, range) {
    const state = rrdState[gpuId];
    if (!state) return;

    const requestToken = state.requestToken;

    try {
        const response = await fetch(`/api/rrd/${encodeURIComponent(gpuId)}?range=${encodeURIComponent(range)}`);
        if (!response.ok) {
            throw new Error(`RRD request failed: ${response.status}`);
        }

        const data = await response.json();
        if (!rrdState[gpuId] || rrdState[gpuId].requestToken !== requestToken) return;
        renderRRDCharts(gpuId, data);
        updateRRDLegend(gpuId, data.stats || {});
    } catch (error) {
        console.error(`Failed to load RRD data for GPU ${gpuId}:`, error);
    }
}

function renderRRDCharts(gpuId, data) {
    const state = rrdState[gpuId];
    if (!state || !data) return;

    Object.entries(state.charts).forEach(([metricKey, chart]) => {
        if (!chart) return;
        const series = data.series && Array.isArray(data.series[metricKey]) ? data.series[metricKey] : [];
        chart.data.labels = Array.isArray(data.labels) ? data.labels : [];
        if (chart.data.datasets[0]) {
            chart.data.datasets[0].data = series;
        }
        chart.update('none');
    });
}

function updateRRDLegend(gpuId, stats) {
    Object.keys(RRD_METRICS).forEach((metricKey) => {
        const metricStats = stats[metricKey] || {};
        const pairs = {
            cur: metricStats.current,
            avg: metricStats.avg,
            max: metricStats.max,
            min: metricStats.min,
        };

        Object.entries(pairs).forEach(([kind, value]) => {
            const el = document.getElementById(`rrd-stat-${metricKey}-${kind}-${gpuId}`);
            if (!el) return;
            const formatted = formatRRDValue(metricKey, value);
            el.textContent = formatted === '--' ? '--' : `${formatted}${RRD_METRICS[metricKey].unit}`;
        });
    });
}

function destroyRRDSection(gpuId) {
    const state = rrdState[gpuId];
    if (!state) return;

    if (state.refreshTimer) {
        clearInterval(state.refreshTimer);
    }

    Object.values(state.charts).forEach((chart) => {
        if (chart && typeof chart.destroy === 'function') {
            chart.destroy();
        }
    });

    delete rrdState[gpuId];
}

window.rrdState = rrdState;
window.initRRDSection = initRRDSection;
window.setActiveRRDRange = setActiveRRDRange;
window.loadRRDRange = loadRRDRange;
window.renderRRDCharts = renderRRDCharts;
window.updateRRDLegend = updateRRDLegend;
window.destroyRRDSection = destroyRRDSection;
window.applyRRDPowerMax = applyRRDPowerMax;
