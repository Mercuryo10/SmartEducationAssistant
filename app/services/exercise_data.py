"""练习生成模板数据（docs/09 阶段五「模板数据」交付物）。

设计：**参数化模板 + 标准陈述库**（docs/01 §2.4 / docs/05 §5.4 / docs/06 §4.5），
程序化保证题目「可解、答案唯一自洽」（docs/09 §5 验收「答案代入验算通过」）。

本文件是种子数据源：`scripts/init_db.py` 的 `seed_exercise_templates()` 读取后写入
`exercises` 表（template / answer_template / params_schema）；运行期生成时从
`exercises.params_schema` 读取事实库，**本文件不参与运行期逻辑**（仅在初始化时使用）。

每个知识点的事实结构（facts 列表，单元素为 dict）：
- `concept`: 题干中使用的概念名。
- `true_statements`: 3 条**正确**表述。`[0]` 用于 easy/medium 单选正确项；
  全部 3 条用于 hard「选错误项」题的正确干扰项。
- `distractors`: 3 条**似是而非**的错误项（easy/medium 单选干扰项）。
- `false_statement`: 1 条**明显错误**表述（hard「下列说法错误的是」的答案）。
- `fill_question` / `fill_answer`: 填空题干（含 ____ 填空位）与答案。

难度差异体现在**题干语句 + 解析深度**（easy 基础识别 / medium 理解对比 / hard
原理推导与易错点），见 `STEM_TEMPLATES` 与 `exercise_service._DIFFICULTY_RULES`。
"""
from typing import Any

# 知识点名（与 knowledge_points 表一致，docs/03 §4.4 / scripts/init_db.py）→ 事实库
FACT_LIBRARIES: dict[str, list[dict[str, Any]]] = {
    "Transformer 与注意力机制": [
        {
            "concept": "自注意力机制",
            "true_statements": [
                "自注意力通过 Q、K、V 三个矩阵计算输入序列中各位置的加权表示",
                "自注意力中 Q 与 K 的点积经 softmax 归一化后得到注意力权重",
                "注意力权重对 V 加权求和，得到融合上下文信息的输出表示",
            ],
            "distractors": [
                "自注意力只能处理单个位置，无法建模序列依赖",
                "自注意力的注意力权重由 Q 与 V 相乘得到，无需归一化",
                "自注意力计算时完全不需要位置编码信息",
            ],
            "false_statement": "自注意力无法建模序列中任意两个位置之间的依赖关系",
            "fill_question": "自注意力机制中，注意力权重通过对 Q 与 K 的____结果进行 softmax 归一化得到。",
            "fill_answer": "点积（dot product）",
        },
        {
            "concept": "多头注意力",
            "true_statements": [
                "多头注意力将输入切分为多个子空间并行计算注意力，再拼接融合",
                "多头注意力能让模型在不同表示子空间捕获多样的依赖关系",
                "多头注意力的每个头都执行一次独立的注意力计算",
            ],
            "distractors": [
                "多头注意力把所有头的输出直接相加，不做任何变换",
                "多头注意力只有一个头参与计算，其余头被丢弃",
                "多头注意力的输入必须比单头注意力短得多",
            ],
            "false_statement": "多头注意力每个头学习完全相同的表示，是冗余计算",
            "fill_question": "Transformer 中把注意力拆分为多个子空间并行计算、再融合的机制称为____注意力。",
            "fill_answer": "多头（Multi-Head）",
        },
    ],
    "检索增强生成（RAG）": [
        {
            "concept": "检索增强生成",
            "true_statements": [
                "RAG 通过检索相关证据片段并约束生成，降低模型对参数化记忆的依赖",
                "RAG 的基本流程是检索（Retrieval）、增强（Augmentation）、生成（Generation）",
                "RAG 检索到的外部证据能够帮助缓解大模型的幻觉问题",
            ],
            "distractors": [
                "RAG 只是把检索结果机械拼进 prompt，对生成质量没有帮助",
                "RAG 必须重新微调整个大模型才能生效",
                "RAG 的检索发生在模型生成答案之后",
            ],
            "false_statement": "RAG 用检索到的证据替换掉模型的全部参数化知识",
            "fill_question": "RAG 的完整流程是：检索（Retrieval）→ ____（Augmentation）→ 生成（Generation）。",
            "fill_answer": "增强",
        },
    ],
    "多 Agent 编排（LangGraph）": [
        {
            "concept": "LangGraph 子图",
            "true_statements": [
                "LangGraph 用 StateGraph 定义节点与边，并以子图形式实现模块化编排",
                "LangGraph 子图可以作为一个节点挂载进主图复用",
                "LangGraph 节点通过读写共享状态完成数据传递",
            ],
            "distractors": [
                "LangGraph 子图只能独立运行，不能嵌入主图",
                "LangGraph 节点之间只能通过全局数据库表传递数据",
                "LangGraph 不支持条件分支路由",
            ],
            "false_statement": "LangGraph 的每个节点都必须调用一次大模型",
            "fill_question": "LangGraph 中定义图结构的核心类是____。",
            "fill_answer": "StateGraph",
        },
    ],
    "向量检索与语义嵌入": [
        {
            "concept": "语义嵌入",
            "true_statements": [
                "语义嵌入把文本映射为稠密向量，语义相近的文本在向量空间距离更近",
                "嵌入向量的相似度常用余弦相似度衡量",
                "向量检索通过比较嵌入向量距离实现语义级召回",
            ],
            "distractors": [
                "语义嵌入把文本映射为稀疏的 one-hot 向量",
                "语义相近的文本在向量空间中距离更远",
                "嵌入向量维度越高一定检索越准确",
            ],
            "false_statement": "语义嵌入无法反映文本的语义信息，只编码字面拼写",
            "fill_question": "衡量两个嵌入向量语义相似度最常用的指标是____相似度。",
            "fill_answer": "余弦",
        },
    ],
    "提示词工程": [
        {
            "concept": "思维链（CoT）",
            "true_statements": [
                "思维链提示引导模型分步推理，显著提升复杂推理任务的表现",
                "思维链提示通常在 prompt 中给出逐步推理的示例",
                "思维链让模型在得出答案前先输出中间推理步骤",
            ],
            "distractors": [
                "思维链提示会降低模型在算术推理上的准确率",
                "思维链提示要求模型直接输出最终答案，不展示推理过程",
                "思维链提示只在图像分类任务中有效",
            ],
            "false_statement": "思维链提示就是让模型随机联想，与推理无关",
            "fill_question": "在 prompt 中给出少量示例来引导模型输出格式与风格，称为____提示。",
            "fill_answer": "few-shot（少样本）",
        },
    ],
}

# 题干模板：题型 × 难度。难度差异由题干深度体现（easy 识别 / medium 理解 / hard 推导）。
STEM_TEMPLATES: dict[str, dict[str, str]] = {
    "choice": {
        "easy": "下列关于{concept}的说法，正确的是（　）",
        "medium": "关于{concept}，下列表述正确的是（　）",
        "hard": "关于{concept}，下列说法错误的是（　）",
    },
    "fill": {
        "easy": "{fill_question}",
        "medium": "{fill_question}",
        "hard": "{fill_question}",
    },
    "solve": {
        "easy": "请简述{concept}的核心要点。",
        "medium": "请解释{concept}的工作原理，并说明其关键步骤。",
        "hard": "请阐述{concept}的完整原理，分析初学者常见误区，并总结易错点。",
    },
}

# 答案模板：题型 → 格式（填充实际值）。
ANSWER_TEMPLATES: dict[str, str] = {
    "choice": "{letter}（{statement}）",
    "fill": "{fill_answer}",
    "solve": "{points}",
}

# 题型清单（docs/04 §7.1：choice / fill / solve）
QUESTION_TYPES = ("choice", "fill", "solve")
# 难度清单（docs/04 §7.1：easy / medium / hard）
DIFFICULTIES = ("easy", "medium", "hard")
