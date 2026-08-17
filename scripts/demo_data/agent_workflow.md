# Agent 工作流与 LangGraph 编排

## 1. 什么是 Agent

Agent（智能体）是一个能"感知—决策—行动"的 AI 系统：它把大模型作为大脑，通过**规划**把任务拆解成步骤，通过**工具调用（Function Calling / Tool Use）**去执行检索、计算、调用 API 等动作，并根据执行结果决定下一步。与"一问一答"的普通 Chatbot 相比，Agent 能在一次任务中做多步推理、调用外部工具、自己纠正错误。

## 2. Agent 的三要素

- **模型（Model）**：负责推理与决策，是大脑。
- **工具（Tools）**：模型可以调用的外部能力，比如检索知识库、查数据库、执行代码。
- **编排（Orchestration）**：决定"模型何时思考、何时调用工具、如何根据结果继续"，常用状态机或图来描述。

## 3. LangGraph 的核心概念

LangGraph 把 Agent 流程建模成**图（Graph）**：

- **节点（Node）**：一个处理步骤，如"检索""生成""保存"。
- **边（Edge）**：节点之间的流转方向。
- **条件边（Conditional Edge）**：根据状态决定下一步去哪个节点，这是 Agent 能"自主决策"的关键。
- **状态（State）**：在图执行过程中共享的数据，每个节点都可以读写状态。

典型写法是 `StateGraph(AppState)` 建图、`add_node` 加节点、`add_edge`/`add_conditional_edges` 连边、最后 `compile()` 得到可执行图，用 `invoke`（同步）/`astream`（异步流式）执行。

## 4. Supervisor 模式与子图

当任务种类多、彼此差异大时，单个 Agent 难以兼顾。常用的模式是 **Supervisor（主管）模式**：

- 一个 Supervisor 节点用大模型对用户输入做**意图分类**，决定派给哪个子 Agent。
- 每个子 Agent 是一个独立的子图（subgraph），职责单一，可以单独迭代和测试。
- 子图之间通过共享状态传递信息，Supervisor 充当"路由 + 协调者"。

例如教育助手场景：答疑、批改作业、错题分析、出题、推送五个子 Agent 各管一类任务，Supervisor 根据用户意图路由。这样做的价值是**职责单一、可独立迭代、避免单个巨大 prompt 无法兼顾多类任务**。

## 5. Agentic RAG：Agent 与 RAG 结合

把 RAG 放进 Agent 里就得到 Agentic RAG：Agent 不只是"一次检索一次生成"，而是可以自己规划"要不要检索、检索几次、检索完要不要再追问"，支持多跳推理，能显著提升复杂问题的回答质量。

## 6. 小结

- Agent = 模型 + 工具 + 编排；核心价值是能自主规划、调用工具、多步执行。
- LangGraph 用"图"建模流程：节点、边、条件边、共享状态。
- Supervisor 模式适合"任务多、差异大"的场景，用意图路由把请求分发给专业子 Agent。
- 面试常问：为什么用多 Agent 而不是一个大 prompt？答：职责单一、可独立迭代、可测试。
