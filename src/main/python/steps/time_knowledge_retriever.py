from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from loguru import logger

from src.main.python.config.settings import settings
from src.main.python.steps.time_range_resolver import resolve_dynamic_date_range


class TimeKnowledgeRetriever:
    """召回用户查询中的独立时间表达，并在代码侧计算具体日期范围。"""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or settings.TIME_KNOWLEDGE_PATH)
        self.items: List[Dict[str, Any]] = []
        self._alias_entries: List[Dict[str, Any]] = []
        self.load_config()

    def load_config(self) -> None:
        if not self.path.exists():
            logger.warning(f"time knowledge file not found: {self.path}")
            self.items = []
            self._alias_entries = []
            return

        with open(self.path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        self.items = raw.get("time_knowledge", []) or []
        entries: List[Dict[str, Any]] = []
        for item in self.items:
            for alias in item.get("aliases", []) or []:
                alias_text = str(alias).strip()
                if not alias_text:
                    continue
                entries.append({
                    "alias": alias_text,
                    "item": item,
                    "length": len(alias_text),
                })

        self._alias_entries = sorted(entries, key=lambda entry: entry["length"], reverse=True)

    def recall(
        self,
        query: str,
        top_k: int = 5,
        now: Optional[Union[date, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for entry in self._alias_entries:
            alias = entry["alias"]
            start = query.find(alias)
            while start >= 0:
                end = start + len(alias)
                candidates.append({
                    "start": start,
                    "end": end,
                    "alias": alias,
                    "item": entry["item"],
                    "score": len(alias),
                })
                start = query.find(alias, start + 1)

        selected: List[Dict[str, Any]] = []
        occupied: List[tuple[int, int]] = []
        seen_ids = set()
        for candidate in sorted(candidates, key=lambda item: (-item["score"], item["start"])):
            item = candidate["item"]
            item_id = item.get("id")
            if item_id in seen_ids:
                continue
            if any(candidate["start"] < end and start < candidate["end"] for start, end in occupied):
                continue

            value = resolve_dynamic_date_range(item.get("resolver", {}), now=now)
            if value is None:
                continue

            selected.append({
                "id": item_id,
                "matched": candidate["alias"],
                "min": value.min,
                "max": value.max,
                "score": candidate["score"],
            })
            occupied.append((candidate["start"], candidate["end"]))
            seen_ids.add(item_id)
            if len(selected) >= top_k:
                break

        return selected
