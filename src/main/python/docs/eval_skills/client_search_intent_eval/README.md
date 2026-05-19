# client_search_intent_eval

用于客户搜索解析结果的 Skill 式评估。当前实现先使用确定性预检规则生成结构化评估结果；`SKILL.md` 作为 Rubric 文档，后续可接入 LLM Judge。

运行：

```bash
python -m src.main.python.tools.iteration_pipeline skill-eval \
  --input src/main/python/docs/evaluations/my_queries_observe/batch_eval_result.xlsx \
  --skill src/main/python/docs/eval_skills/client_search_intent_eval/SKILL.md \
  --output-dir src/main/python/docs/evaluations/my_queries_skill_eval
```
