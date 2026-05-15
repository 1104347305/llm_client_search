from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ChangeSet:
    path: Path
    raw: dict[str, Any]
    id: str
    title: str
    owner: str | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    enums: dict[str, Any] = field(default_factory=dict)
    l2_rules: list[dict[str, Any]] = field(default_factory=list)
    value_mappings: dict[str, Any] = field(default_factory=dict)
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    testset_path: Path | None = None
    acceptance: dict[str, Any] = field(default_factory=dict)

    @property
    def iteration_dir(self) -> Path:
        return self.path.parent


def load_change_set(path: str | Path) -> ChangeSet:
    change_set_path = Path(path).resolve()
    with change_set_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    if not isinstance(raw, dict):
        raise ValueError("change set must be a YAML object")

    change_id = str(raw.get("id") or change_set_path.parent.name)
    title = str(raw.get("title") or change_id)
    testset = raw.get("testset_path")
    testset_path = None
    if testset:
        candidate = Path(str(testset))
        testset_path = candidate if candidate.is_absolute() else change_set_path.parent / candidate

    return ChangeSet(
        path=change_set_path,
        raw=raw,
        id=change_id,
        title=title,
        owner=raw.get("owner"),
        fields=list(raw.get("fields") or []),
        enums=dict(raw.get("enums") or {}),
        l2_rules=list(raw.get("l2_rules") or []),
        value_mappings=dict(raw.get("value_mappings") or {}),
        test_cases=list(raw.get("test_cases") or []),
        testset_path=testset_path,
        acceptance=dict(raw.get("acceptance") or {}),
    )


def write_template(path: str | Path) -> Path:
    output_path = Path(path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"change set already exists: {output_path}")

    template = """id: 20260514_customer_temperature
title: 客户温度字段优化
owner: mickey
reason: 支持高温、中温、低温客户查询

fields:
  - id: client_temperature_match
    field: clientTemperature
    operator: MATCH
    value_type: enum
    retrieval_text: 客户温度 高温客户 中温客户 低温客户
    enum_ref: clientTemperature
    description: 客户经营温度标签
    examples:
      - query: 高温客户
        output: {field: clientTemperature, operator: MATCH, value: 高温}
      - query: 找一下中温客户
        output: {field: clientTemperature, operator: MATCH, value: 中温}
    negative_examples:
      - query: 今天温度高的客户
        reason: 天气温度不是客户温度标签

enums:
  clientTemperature:
    values:
      - 冷却
      - 低温
      - 中温
      - 高温
    ordered: true

value_mappings:
  clientTemperature:
    最近没联系: 冷却

l2_rules:
  - name: 客户温度匹配
    field: clientTemperature
    operator: MATCH
    value_type: capture
    enum_ref: clientTemperature
    patterns_template:
      - "{enum}客户"
      - "客户温度是{enum}"

testset_path: generated_testset.jsonl

test_cases:
  - id: ct_001
    query: 高温客户
    expected:
      query_logic: AND
      conditions:
        - field: clientTemperature
          operator: MATCH
          value: 高温
    tags: [positive, l2]
  - id: ct_002
    query: 今天温度高的客户
    expected:
      query_logic: AND
      conditions: []
    tags: [negative]

acceptance:
  min_exact_match_rate: 0.95
  max_empty_rate: 0.02
  max_false_positive_rate: 0.02
  max_avg_latency_ms: 3000
"""
    output_path.write_text(template, encoding="utf-8")
    return output_path
