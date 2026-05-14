from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Optional, Dict, Any, Union
from enum import Enum


class QueryLogic(str, Enum):
    AND = "AND"
    OR = "OR"


class Operator(str, Enum):
    MATCH = "MATCH"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    RANGE = "RANGE"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT_CONTAINS"
    EXISTS = "EXISTS"           # 字段存在且不为空（V3 新增，无需传 value）
    NOT_EXISTS = "NOT_EXISTS"   # 字段不存在或为空（V3 新增，无需传 value）
    GEO_RADIUS = "GEO_RADIUS"          # 地理半径内含
    NOT_GEO_RADIUS = "NOT_GEO_RADIUS"  # 地理半径外不含


class RangeValue(BaseModel):
    min: Optional[Union[int, float, str]] = None  # 支持数值范围和日期字符串范围
    max: Optional[Union[int, float, str]] = None


class GeoRadiusValue(BaseModel):
    """地理半径值 — 本服务只提取地名和半径，不做地理编码"""
    place_name: Optional[str] = None  # null = 以客户自身地址坐标为中心
    radius: Optional[int] = None      # 单位：米，null = 无半径限制


class Condition(BaseModel):
    field: str
    operator: Operator
    value: Optional[Union[str, int, float, RangeValue, GeoRadiusValue, Dict[str, Any], List[str]]] = None

    @model_validator(mode="after")
    def normalize_value_shape(self):
        """统一约束 condition.value 结构，避免不同层输出不一致。"""
        if self.value is None:
            return self

        if self.operator in (Operator.CONTAINS, Operator.NOT_CONTAINS):
            if not isinstance(self.value, list):
                self.value = [self.value]
            return self

        if isinstance(self.value, list):
            self.value = self.value[0] if self.value else None

        return self


class LogicNode(BaseModel):
    """逻辑树节点，支持嵌套的 AND/OR 逻辑"""
    operator: QueryLogic
    conditions: List[Union[Condition, 'LogicNode']]
    model_config = ConfigDict(arbitrary_types_allowed=True)


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
    elapsed_ms: Optional[float] = None  # 查询总耗时（毫秒）
    prompt: Optional[str] = None  # L4解析时的RAG prompt；非L4时为空
    rewritten_query: Optional[str] = None  # value_mapping 归一化后的查询
    matched_patterns: Optional[List[Dict[str, Any]]] = None  # 命中的规则/正则调试信息


class ParseApiRequest(BaseModel):
    """AskBob 标准协议入参"""
    source: str = "askbob"
    user_text: str
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    user_id: Optional[str] = None
    ts: Optional[int] = None
    user_action: str = "write"
    action_scenario: str = "customerSearch"
    extra_input_params: Dict[str, Any] = Field(default_factory=dict)


class ParseApiExtraOutput(BaseModel):
    """extra_output_params 内的解析结果"""
    query: str
    query_logic: Optional[QueryLogic] = None
    conditions: List[Condition] = Field(default_factory=list)
    matched_level: int = 0
    rewritten_query: Optional[str] = None
    matched_patterns: Optional[str] = None
    cost_times: Optional[float] = None
    confidence: Optional[float] = None
    intent_summary: Optional[str] = None  # 人类可读的查询意图摘要


class ParseApiData(BaseModel):
    """响应 data 层"""
    robot_text: str
    end_flag: int = 1
    extra_output_params: Union[ParseApiExtraOutput, Dict[str, str]]
    trace_id: Optional[str] = None


class ParseApiResponse(BaseModel):
    """AskBob 标准协议响应"""
    code: int = 0
    msg: str = "操作成功"
    data: Optional[ParseApiData] = None


class ParsedQuery(BaseModel):
    """LLM 解析后的结构化查询"""
    conditions: List[Condition]  # 扁平列表（向后兼容）
    query_logic: QueryLogic = QueryLogic.AND
    logic_tree: Optional[LogicNode] = None  # 复杂逻辑用树表示
    sort: Optional[List[Sort]] = None
    confidence: float = 1.0
    matched_level: int  # 1=规则, 2=模板, 3=缓存, 4=LLM
    prompt: Optional[str] = None  # L4解析时的RAG prompt；非L4时为空
    rewritten_query: Optional[str] = None  # value_mapping 归一化后的查询
    matched_patterns: Optional[List[Dict[str, Any]]] = None  # 命中的规则/正则调试信息
