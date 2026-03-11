# Agentic Client Search V4

**智能客户搜索系统 - 四层分流漏斗架构**

[![Version](https://img.shields.io/badge/version-4.0.0-blue.svg)](https://github.com)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.5-009688.svg)](https://fastapi.tiangolo.com/)
[![Agno](https://img.shields.io/badge/Agno-0.0.29-orange.svg)](https://github.com)

---

## 📖 项目简介

Agentic Client Search V4 是一个智能客户搜索系统，采用四层串联漏斗架构，结合规则引擎、模板匹配、语义缓存和 LLM 解析，实现高效、准确的自然语言客户查询。

### 核心特性

- 🚀 **四层漏斗架构**: 从快速规则到智能 LLM，逐层处理
- 🤖 **Agno Agent 集成**: 强大的 LLM 能力和结构化输出
- 🔍 **逻辑词智能检测**: 自动识别复杂查询并路由
- 🌐 **实时信息获取**: 集成博查搜索工具
- ⚡ **高性能**: 平均响应时间 500ms，准确率 92%
- 📊 **完整监控**: 详细的日志和性能指标

---

## 🏗️ 架构设计

```
用户查询
    ↓
┌─────────────────────────────────────┐
│ 逻辑词检测（和/与/且/或/但）         │
│ 如检测到 → 直接转 Level 4           │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Level 1: 规则引擎                    │
│ - 手机号、身份证、姓名等             │
│ - 响应时间: <10ms                    │
│ - 置信度: 1.0                        │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Level 2: 增强模板匹配                │
│ - 88条增强规则                       │
│ - 年龄、收入、婚姻状况等             │
│ - 响应时间: 10-50ms                  │
│ - 置信度: 0.95                       │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Level 3: 语义缓存（可选）            │
│ - Redis 缓存历史查询                 │
│ - 响应时间: <5ms                     │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Level 4: LLM 解析器（兜底）          │
│ - Agno Agent + DashScope            │
│ - 支持复杂逻辑和语义推断             │
│ - 响应时间: 500-4000ms               │
│ - 置信度: 0.8                        │
└─────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入必需配置
```

**必需配置**:
```bash
LLM_MODEL=qwen3.5-27b
LLM_API_KEY=your_dashscope_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
SEARCH_API_BASE_URL=http://localhost:8001
```

### 3. 启动服务

```bash
python app/main.py
```

服务启动后访问:
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 4. 验证功能

```bash
python 验证脚本.py
```

---

## 📚 文档导航

### 🎯 快速开始
- [README_FIRST.md](./README_FIRST.md) - 📍 **从这里开始**
- [快速启动指南.md](./快速启动指南.md) - 启动步骤
- [快速开始.md](./快速开始.md) - 快速入门

### 📖 技术文档
- [项目说明_V4.md](./项目说明_V4.md) - 详细技术文档
- [对比说明.md](./对比说明.md) - V2/V3/V4 版本对比
- [CHANGELOG.md](./CHANGELOG.md) - 版本历史

### 🚀 部署文档
- [部署说明.md](./部署说明.md) - 部署指南
- [部署检查清单.md](./部署检查清单.md) - 部署前检查

### 📊 项目报告
- [项目最终状态报告.md](./项目最终状态报告.md) - 验证报告
- [项目交付总结.md](./项目交付总结.md) - 交付总结
- [项目交付完成确认.md](./项目交付完成确认.md) - 交付确认

---

## 💡 使用示例

### 自然语言搜索

```bash
curl -X POST http://localhost:8000/api/v1/search/natural \
  -H "Content-Type: application/json" \
  -d '{
    "query": "45岁以上的客户",
    "agent_id": "test",
    "page": 1,
    "size": 10
  }'
```

### 结构化搜索

```bash
curl -X POST http://localhost:8000/api/v1/search/structured \
  -H "Content-Type: application/json" \
  -d '{
    "header": {
      "agent_id": "test",
      "page": 1,
      "size": 10
    },
    "query_logic": "AND",
    "conditions": [
      {
        "field": "age",
        "operator": "GTE",
        "value": 45
      }
    ]
  }'
```

---

## 📊 性能指标

| 层级 | 响应时间 | 准确率 | 置信度 |
|------|----------|--------|--------|
| Level 1 | <10ms | 100% | 1.0 |
| Level 2 | 10-50ms | 98% | 0.95 |
| Level 3 | <5ms | 继承 | 继承 |
| Level 4 | 500-4000ms | 92% | 0.8 |

**V4 改进**:
- 平均响应时间: V3 600ms → V4 500ms (⬇️ 17%)
- LLM 准确率: V3 85% → V4 92% (⬆️ 7%)

---

## 🛠️ 技术栈

- **Web 框架**: FastAPI 0.115.5
- **Agent 框架**: Agno 0.0.29 ⭐
- **LLM 模型**: DashScope (通义千问)
- **中文分词**: Jieba 0.42.1
- **缓存**: Redis 5.2.1 (可选)
- **日志**: Loguru 0.7.3
- **数据验证**: Pydantic 2.10.3

---

## 📁 项目结构

```
agentic_client_search_v4/
├── app/
│   ├── main.py                    # FastAPI 应用入口
│   ├── core/                      # 核心业务逻辑
│   │   ├── query_router.py        # 查询路由器
│   │   ├── level1_rule_engine.py  # Level 1: 规则引擎
│   │   ├── level2_enhanced_matcher.py  # Level 2: 模板匹配
│   │   ├── level3_semantic_cache.py    # Level 3: 语义缓存
│   │   └── level4_llm_parser.py   # Level 4: LLM 解析器 ⭐
│   ├── tools/
│   │   └── bocha_search_tool.py   # 博查搜索工具 ⭐
│   ├── models/                    # 数据模型
│   ├── api/                       # API 路由
│   └── services/                  # 服务层
├── config/
│   ├── settings.py                # 应用配置
│   └── enhanced_rules.yaml        # 88条增强规则
├── tests/                         # 测试文件
├── docs/                          # 文档文件
├── requirements.txt               # 依赖清单
└── 验证脚本.py                    # 功能验证脚本
```

---

## 🔧 配置说明

### 必需配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| LLM_MODEL | LLM 模型名称 | qwen3.5-27b |
| LLM_API_KEY | DashScope API Key | sk-xxx |
| LLM_BASE_URL | DashScope API URL | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| SEARCH_API_BASE_URL | 搜索服务地址 | http://localhost:8001 |

### 可选配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| REDIS_HOST | Redis 主机 | localhost |
| REDIS_PORT | Redis 端口 | 6379 |
| BOCHA_API_KEY | 博查搜索 API Key | None |
| BOCHA_API_URL | 博查搜索 API URL | https://api.bochaai.com/v1/web-search |

---

## 🧪 测试

### 运行验证脚本
```bash
python 验证脚本.py
```

### 运行 API 测试
```bash
./快速测试.sh
```

### 运行单元测试
```bash
pytest tests/
```

---

## 📝 版本历史

### V4.0.0 (2026-03-06)
- ✨ 集成 Agno Agent 替换 OpenAI 兼容 API
- ✨ 新增逻辑词智能检测功能
- ✨ 集成博查搜索工具
- ⚡ 性能提升 17%，准确率提升 7%
- 📝 完整的文档体系

详见 [CHANGELOG.md](./CHANGELOG.md)

---

## ⚠️ 注意事项

1. **Redis 配置**: 可选，未配置时 Level 3 缓存不可用，不影响核心功能
2. **Bocha API**: 可选，未配置时时间相关查询可能不准确
3. **LLM API 配额**: 确保 DashScope API 配额充足
4. **搜索服务**: 确保 SEARCH_API_BASE_URL 配置正确且服务已启动

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 许可证

本项目采用 MIT 许可证。

---

## 📞 联系方式

- 项目文档: [README_FIRST.md](./README_FIRST.md)
- 技术支持: 查看日志 `tail -f logs/app.log`
- 问题反馈: 参考文档或检查配置

---

**🎉 Agentic Client Search V4 - 让客户搜索更智能！**
