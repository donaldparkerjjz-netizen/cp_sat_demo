# -*- coding: utf-8 -*-
"""weaving_demo/api/store.py -- 内存排程结果存储。"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class ScheduleStore:
    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._latest_id: Optional[str] = None

    def save(self, schedule_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._data[schedule_id] = payload
            self._latest_id = schedule_id

    def get(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(schedule_id)

    def latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._latest_id is None:
                return None
            return self._data.get(self._latest_id)

    def latest_id(self) -> Optional[str]:
        with self._lock:
            return self._latest_id

    def all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._data)


STORE = ScheduleStore()
