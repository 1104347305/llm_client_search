from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum


class QueryLogic(str, Enum):
    AND = "AND"
    OR = "OR"


class Operator(str, Enum):
    MATCH = "MATCH"
    GTE = "GTE"
    LTE = "LTE"
    RANGE = "RANGE"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT_CONTAINS"
    EXISTS = "EXISTS"           # 字段存在且不为空（V3 新增，无需传 value）
    NOT_EXISTS = "NOT_EXISTS"   # 字段不存在或为空（V3 新增，无需传 value）
    NESTED_MATCH = "NESTED_MATCH"  # 内部兼容，发送时自动转为 MATCH（V3 点号自动识别嵌套）


class RangeValue(BaseModel):
    min: Optional[Union[int, float, str]] = None  # 支持数值范围和日期字符串范围
    max: Optional[Union[int, float, str]] = None


class Condition(BaseModel):
    field: str
    operator: Operator
    value: Optional[Union[str, int, float, RangeValue, Dict[str, Any], List[str]]] = None
    # EXISTS/NOT_EXISTS 无需 value；ENUM_GTE/ENUM_LTE value 为枚举列表，发送前转为 CONTAINS


class LogicNode(BaseModel):
    """逻辑树节点，支持嵌套的 AND/OR 逻辑"""
    operator: QueryLogic
    conditions: List[Union[Condition, 'LogicNode']]

    class Config:
        # 允许递归引用
        arbitrary_types_allowed = True


# 更新递归引用
LogicNode.model_rebuild()


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class Sort(BaseModel):
    field: str
    order: SortOrder = SortOrder.DESC


class RequestHeader(BaseModel):
    agent_id: str
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class SearchRequest(BaseModel):
    header: RequestHeader
    query_logic: QueryLogic = QueryLogic.AND
    conditions: List[Condition]
    sort: Optional[List[Sort]] = None


class NaturalLanguageSearchRequest(BaseModel):
    query: str
    agent_id: str
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    sort: Optional[List[Sort]] = None


class SearchResponse(BaseModel):
    success: bool = True
    message: str = "success"
    data: Dict[str, Any]
    matched_level: int = 0
    confidence: float = 1.0
    conditions: Optional[List[Condition]] = None
    query_logic: Optional[QueryLogic] = None


class ParsedQuery(BaseModel):
    """LLM 解析后的结构化查询"""
    conditions: List[Condition]  # 扁平列表（向后兼容）
    query_logic: QueryLogic = QueryLogic.AND
    logic_tree: Optional[LogicNode] = None  # 复杂逻辑用树表示
    sort: Optional[List[Sort]] = None
    confidence: float = 1.0
    matched_level: int  # 1=规则, 2=模板, 3=缓存, 4=LLM
