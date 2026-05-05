"""Tests for core.rrd_buffer."""

import sqlite3
from unittest.mock import patch

from core.rrd_buffer import RRDBuffer


def make_metrics(util=50, temp=70, mem_used=4000, mem_total=8000, power=200):
    return {
        'utilization': util,
        'temperature': temp,
        'memory_used': mem_used,
        'memory_total': mem_total,
        'power_draw': power,
    }


def record_window(rrd, gpu_id, start_ts, end_ts, **metrics):
    payload = make_metrics(**metrics)
    for ts in range(start_ts, end_ts):
        with patch('time.time', return_value=float(ts) + 0.1):
            rrd.record(gpu_id, payload)


class TestRRDBuffer:
    def test_query_1min_uses_deque_buckets(self, tmp_path):
        rrd = RRDBuffer(str(tmp_path / 'rrd.db'))

        for offset, ts in enumerate(range(100, 105)):
            with patch('time.time', return_value=float(ts) + 0.1):
                rrd.record('0', make_metrics(util=50 + offset, temp=70 + offset, power=200 + offset))

        with patch('time.time', return_value=105.0):
            data = rrd.query('0', '1min')

        assert len(data['labels']) == 60
        assert data['series']['utilization'][-1] == 54
        assert data['stats']['temperature']['current'] == 74
        assert data['stats']['power_draw']['max'] == 204

    def test_query_1min_fills_short_sparse_sampling_gaps(self, tmp_path):
        rrd = RRDBuffer(str(tmp_path / 'rrd.db'))

        for ts in (100, 102, 104):
            with patch('time.time', return_value=float(ts) + 0.1):
                rrd.record('i0', make_metrics(util=40, temp=65, mem_used=1000, mem_total=4000, power=55))

        with patch('time.time', return_value=105.0):
            data = rrd.query('i0', '1min')

        assert data['series']['utilization'][-5:] == [40, 40, 40, 40, 40]
        assert data['series']['memory_pct'][-1] == 25
        assert data['stats']['power_draw']['current'] == 55

    def test_consolidate_sync_persists_1min_and_5min_rows(self, tmp_path):
        db_path = tmp_path / 'rrd.db'
        rrd = RRDBuffer(str(db_path))
        rrd._init_db_sync()

        record_window(rrd, '0', 0, 60, util=10, temp=60, power=150)
        rrd._consolidate_sync(60)
        record_window(rrd, '0', 60, 120, util=20, temp=61, power=160)
        rrd._consolidate_sync(120)
        record_window(rrd, '0', 120, 180, util=30, temp=62, power=170)
        rrd._consolidate_sync(180)
        record_window(rrd, '0', 180, 240, util=40, temp=63, power=180)
        rrd._consolidate_sync(240)
        record_window(rrd, '0', 240, 300, util=50, temp=64, power=190)
        rrd._consolidate_sync(300)

        with sqlite3.connect(db_path) as conn:
            one_min_rows = conn.execute("SELECT COUNT(*) FROM rrd_1min").fetchone()[0]
            five_min_rows = conn.execute("SELECT COUNT(*) FROM rrd_5min").fetchone()[0]

        assert one_min_rows == 5
        assert five_min_rows == 1

        with patch('time.time', return_value=300.0):
            data = rrd.query('0', '2hr')

        # 2hr now reads rrd_30min at 7200s step, 360 points (30-day window)
        # rrd_30min is not populated until a 30-min cascade fires, so all null here
        assert len(data['labels']) == 360
        assert all(v is None for v in data['series']['utilization'])

    def test_query_1day_reads_30min_table(self, tmp_path):
        db_path = tmp_path / 'rrd.db'
        rrd = RRDBuffer(str(db_path))
        rrd._init_db_sync()

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO rrd_30min (gpu_id, ts, util, temp, mem_pct, power)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ('0', 86400, 55.0, 71.0, 42.0, 210.0),  # ts = 1 day from epoch
            )
            conn.commit()

        # Query at 2 days from epoch: end_ts=172800, window covers ts=86400
        with patch('time.time', return_value=172800.0):
            data = rrd.query('0', '1day')

        # 1day now has 365 points (1-year window at daily step)
        assert len(data['labels']) == 365
        assert data['series']['memory_pct'][-1] == 42.0
        assert data['stats']['utilization']['current'] == 55.0

    def test_history_query_is_independent_of_driver_version_581_50(self, tmp_path):
        rrd = RRDBuffer(str(tmp_path / 'rrd.db'))

        metrics = make_metrics(util=88, temp=73, mem_used=6000, mem_total=12000, power=220)
        metrics['driver_version'] = '581.50'

        for ts in range(100, 105):
            with patch('time.time', return_value=float(ts) + 0.1):
                rrd.record('0', metrics)

        with patch('time.time', return_value=104.9):
            data = rrd.query('0', '1min')

        assert data['series']['utilization'][-1] == 88
        assert data['series']['memory_pct'][-1] == 50
        assert data['stats']['power_draw']['current'] == 220
