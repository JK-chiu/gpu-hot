"""Persistent RRD-style storage for historical GPU metrics."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class RRDBuffer:
    """Keep short-term samples in memory and roll them into SQLite tiers."""

    DEQUE_SECONDS = 300
    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    RANGE_CONFIG = {
        # source=deque: read from RAM ring buffer
        # source=db: direct SELECT, one row per point
        # source=db_group: GROUP BY step bucket on rrd_30min
        "1min":  {"source": "deque",    "points": 60,  "step": 1},
        "5min":  {"source": "db",       "table": "rrd_5min",  "points": 288, "step": 300},
        "30min": {"source": "db",       "table": "rrd_30min", "points": 336, "step": 1800},
        "2hr":   {"source": "db_group", "table": "rrd_30min", "points": 360, "step": 7200},
        "1day":  {"source": "db_group", "table": "rrd_30min", "points": 365, "step": 86400},
    }
    METRICS = ("utilization", "temperature", "memory_pct", "power_draw")

    def __init__(self, db_path: str = "data/rrd.db"):
        self.db_path = db_path
        self._buffers = defaultdict(lambda: deque(maxlen=self.DEQUE_SECONDS))
        self._buffer_lock = threading.Lock()

    async def init_db(self):
        """Create SQLite tables and indexes."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._init_db_sync)

    def record(self, gpu_id, gpu_metrics):
        """Record one tier-0 sample at 1-second resolution."""
        ts = int(time.time())
        sample = (
            ts,
            self._to_number(gpu_metrics.get("utilization")),
            self._to_number(gpu_metrics.get("temperature")),
            self._to_number(gpu_metrics.get("memory_used")),
            self._to_number(gpu_metrics.get("memory_total")),
            self._to_number(gpu_metrics.get("power_draw")),
        )

        with self._buffer_lock:
            bucket = self._buffers[str(gpu_id)]
            if bucket and bucket[-1][0] == ts:
                bucket[-1] = sample
            else:
                bucket.append(sample)

    async def consolidate_loop(self):
        """Wake up on minute boundaries and roll data into SQLite tiers."""
        loop = asyncio.get_running_loop()

        try:
            while True:
                now = time.time()
                sleep_for = 60 - (now % 60)
                await asyncio.sleep(sleep_for)
                minute_ts = int(time.time() // 60 * 60)
                await loop.run_in_executor(None, self._consolidate_sync, minute_ts)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RRD consolidation loop crashed")
            raise

    def query(self, gpu_id, range_key) -> dict:
        """Return labels, series and stats for one history range."""
        config = self.RANGE_CONFIG[range_key]
        if config["source"] == "deque":
            labels, timestamps, series = self._query_deque(str(gpu_id), range_key)
        elif config["source"] == "db":
            labels, timestamps, series = self._query_db(
                str(gpu_id),
                config["table"],
                config["points"],
                config["step"],
                range_key,
            )
        else:  # db_group
            labels, timestamps, series = self._query_db_group(
                str(gpu_id),
                config["table"],
                config["points"],
                config["step"],
                range_key,
            )

        return {
            "gpu_id": str(gpu_id),
            "range": range_key,
            "labels": labels,
            "timestamps": timestamps,
            "series": series,
            "stats": {metric: self._calculate_stats(values) for metric, values in series.items()},
        }

    def _init_db_sync(self):
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rrd_1min (
                    gpu_id TEXT,
                    ts INTEGER,
                    util REAL,
                    temp REAL,
                    mem_pct REAL,
                    power REAL,
                    PRIMARY KEY (gpu_id, ts)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rrd_5min (
                    gpu_id TEXT,
                    ts INTEGER,
                    util REAL,
                    temp REAL,
                    mem_pct REAL,
                    power REAL,
                    PRIMARY KEY (gpu_id, ts)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rrd_30min (
                    gpu_id TEXT,
                    ts INTEGER,
                    util REAL,
                    temp REAL,
                    mem_pct REAL,
                    power REAL,
                    PRIMARY KEY (gpu_id, ts)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_1min_gpu_ts ON rrd_1min(gpu_id, ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_5min_gpu_ts ON rrd_5min(gpu_id, ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_30min_gpu_ts ON rrd_30min(gpu_id, ts)"
            )
            conn.commit()

    def _consolidate_sync(self, now):
        minute_ts = int(now // 60 * 60)
        minute_start = minute_ts - 60

        with self._buffer_lock:
            samples_by_gpu = {
                gpu_id: [sample for sample in samples if minute_start <= sample[0] < minute_ts]
                for gpu_id, samples in self._buffers.items()
            }

        with sqlite3.connect(self.db_path, timeout=30) as conn:
            for gpu_id, samples in samples_by_gpu.items():
                if not samples:
                    continue

                util, temp, mem_pct, power = self._aggregate_samples(samples)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO rrd_1min (gpu_id, ts, util, temp, mem_pct, power)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (gpu_id, minute_ts, util, temp, mem_pct, power),
                )

                if minute_ts % 300 == 0:
                    self._cascade_rows(conn, "rrd_1min", "rrd_5min", gpu_id, minute_ts, 5)
                if minute_ts % 1800 == 0:
                    self._cascade_rows(conn, "rrd_5min", "rrd_30min", gpu_id, minute_ts, 6)

            conn.execute("DELETE FROM rrd_1min WHERE ts < ?", (minute_ts - 7200,))
            conn.execute("DELETE FROM rrd_5min WHERE ts < ?", (minute_ts - 604800,))
            conn.execute(
                "DELETE FROM rrd_30min WHERE ts < ?",
                (minute_ts - self.ONE_YEAR_SECONDS,),
            )
            conn.commit()

    def _cascade_rows(self, conn, source_table, target_table, gpu_id, ts, limit):
        rows = conn.execute(
            f"""
            SELECT util, temp, mem_pct, power
            FROM {source_table}
            WHERE gpu_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (gpu_id, limit),
        ).fetchall()

        if not rows:
            return

        columns = list(zip(*rows))
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {target_table} (gpu_id, ts, util, temp, mem_pct, power)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                gpu_id,
                ts,
                self._average(columns[0]),
                self._average(columns[1]),
                self._average(columns[2]),
                self._average(columns[3]),
            ),
        )

    def _query_deque(self, gpu_id, range_key):
        config = self.RANGE_CONFIG[range_key]
        step = config["step"]
        points = config["points"]
        end_ts = int(time.time())
        if step > 1:
            end_ts = int(end_ts // step * step)
        start_ts = end_ts - (points * step)

        with self._buffer_lock:
            samples = list(self._buffers.get(gpu_id, ()))

        return self._build_series_from_samples(samples, start_ts, points, step, range_key)

    def _query_db(self, gpu_id, table, points, step, range_key):
        end_ts = int(time.time() // step * step)
        start_ts = end_ts - (points * step)
        rows = self._query_db_sync(gpu_id, table, start_ts, end_ts)
        return self._build_series_from_rows(rows, start_ts, points, step, range_key)

    def _query_db_group(self, gpu_id, table, points, step, range_key):
        end_ts = int(time.time() // step * step)
        start_ts = end_ts - (points * step)
        rows = self._query_db_group_sync(gpu_id, table, start_ts, end_ts, step)
        return self._build_series_from_rows(rows, start_ts, points, step, range_key)

    def _query_db_sync(self, gpu_id, table, start_ts, end_ts):
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            return conn.execute(
                f"""
                SELECT ts, util, temp, mem_pct, power
                FROM {table}
                WHERE gpu_id = ? AND ts BETWEEN ? AND ?
                ORDER BY ts ASC
                """,
                (gpu_id, start_ts, end_ts),
            ).fetchall()

    def _query_db_group_sync(self, gpu_id, table, start_ts, end_ts, step):
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            return conn.execute(
                f"""
                SELECT ts / ? * ? AS bucket_ts,
                       avg(util), avg(temp), avg(mem_pct), avg(power)
                FROM {table}
                WHERE gpu_id = ? AND ts BETWEEN ? AND ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts ASC
                """,
                (step, step, gpu_id, start_ts, end_ts),
            ).fetchall()

    def _build_series_from_samples(self, samples, start_ts, points, step, range_key):
        buckets = [
            {
                "utilization": [],
                "temperature": [],
                "memory_pct": [],
                "power_draw": [],
            }
            for _ in range(points)
        ]

        end_ts = start_ts + (points * step)
        for ts, util, temp, mem_used, mem_total, power in samples:
            if ts < start_ts or ts >= end_ts:
                continue
            idx = int((ts - start_ts) // step)
            bucket = buckets[idx]
            self._append_number(bucket["utilization"], util)
            self._append_number(bucket["temperature"], temp)
            self._append_number(bucket["power_draw"], power)

            mem_pct = None
            if mem_used is not None and mem_total and mem_total > 0:
                mem_pct = (mem_used / mem_total) * 100
            self._append_number(bucket["memory_pct"], mem_pct)

        labels = [self._format_label(start_ts + (idx * step), range_key) for idx in range(points)]
        timestamps = [self._format_tooltip(start_ts + (idx * step), range_key) for idx in range(points)]
        series = {
            metric: [self._average(bucket[metric]) for bucket in buckets]
            for metric in self.METRICS
        }
        return labels, timestamps, series

    def _build_series_from_rows(self, rows, start_ts, points, step, range_key):
        row_map = {row[0]: row[1:] for row in rows}
        labels = []
        timestamps = []
        series = {metric: [] for metric in self.METRICS}

        for idx in range(points):
            ts = start_ts + (idx * step)
            labels.append(self._format_label(ts, range_key))
            timestamps.append(self._format_tooltip(ts, range_key))
            row = row_map.get(ts)
            if row is None:
                for metric in self.METRICS:
                    series[metric].append(None)
                continue

            series["utilization"].append(row[0])
            series["temperature"].append(row[1])
            series["memory_pct"].append(row[2])
            series["power_draw"].append(row[3])

        return labels, timestamps, series

    def _aggregate_samples(self, samples):
        util = [sample[1] for sample in samples if sample[1] is not None]
        temp = [sample[2] for sample in samples if sample[2] is not None]
        power = [sample[5] for sample in samples if sample[5] is not None]

        mem_pct = []
        for _, _, _, mem_used, mem_total, _ in samples:
            if mem_used is None or mem_total in (None, 0):
                continue
            mem_pct.append((mem_used / mem_total) * 100)

        return (
            self._average(util),
            self._average(temp),
            self._average(mem_pct),
            self._average(power),
        )

    @staticmethod
    def _append_number(bucket, value):
        if value is not None:
            bucket.append(value)

    @staticmethod
    def _average(values):
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _calculate_stats(values):
        valid = [value for value in values if value is not None]
        if not valid:
            return {"current": None, "avg": None, "max": None, "min": None}

        return {
            "current": valid[-1],
            "avg": sum(valid) / len(valid),
            "max": max(valid),
            "min": min(valid),
        }

    @staticmethod
    def _format_tooltip(ts, range_key):
        dt = datetime.fromtimestamp(ts)
        if range_key == "1min":
            return dt.strftime("%H:%M:%S")
        if range_key in ("5min", "30min"):
            return dt.strftime("%H:%M")
        if range_key == "2hr":
            return dt.strftime("%m/%d %H:%M")
        # 1day
        return dt.strftime("%m/%d")

    @staticmethod
    def _format_label(ts, range_key):
        dt = datetime.fromtimestamp(ts)
        if range_key == "1min":
            return dt.strftime("%H:%M:%S")
        if range_key == "5min":
            return dt.strftime("%H:%M")   # HH:00 HH:05 HH:10 ...
        if range_key == "30min":
            return dt.strftime("%H:%M")   # 22:00 22:30 ...
        if range_key == "2hr":
            return dt.strftime("%m/%d")
        # 1day
        return dt.strftime("%m/%d")

    @staticmethod
    def _to_number(value):
        if value in (None, "", "N/A", "Unknown"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
