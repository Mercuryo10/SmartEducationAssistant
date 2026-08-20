"""md_enhancer 单测（阶段 7.2 增强，docs/08 §10）。

覆盖：
- 表格→key:value：基础表/多行/加粗清洗/非表格保留/代码块内不转换
- 图片→VL 描述：替换引用、上文/下文各 100 字上下文、base64 data URI、
  找不到图片的引用原样保留、enhance 编排
全部离线：视觉 LLM 用 _FakeLLM stub，不调真实 qwen-vl。
"""
from app.services.md_enhancer import describe_images, enhance_markdown, tables_to_key_value


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """记录调用的视觉 LLM stub：invoke([SystemMessage, HumanMessage]) -> BaseMessage。"""

    def __init__(self, answer: str = "图片文字描述。") -> None:
        self.answer = answer
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        return _Resp(self.answer)


# ---------- 表格 → key:value ----------


def test_tables_to_key_value_basic() -> None:
    md = "| 名称 | 版本 |\n|------|------|\n| Python | 3.11 |\n| MySQL | 8.0 |"
    assert tables_to_key_value(md) == "第一行：名称: Python; 版本: 3.11; 第二行：名称: MySQL; 版本: 8.0"


def test_tables_to_key_value_single_column_separator() -> None:
    md = "| 模型 |\n|:---:|\n| qwen-vl-plus |"
    assert tables_to_key_value(md) == "第一行：模型: qwen-vl-plus"


def test_tables_to_key_value_strips_bold() -> None:
    md = "| **名称** | 值 |\n|------|:---:|\n| **A** | 1 |"
    assert tables_to_key_value(md) == "第一行：名称: A; 值: 1"


def test_tables_to_key_value_no_separator_preserved() -> None:
    """缺分隔行不算表格，原样保留（可能是普通文本）。"""
    md = "| 名称 | 版本 |\n| 说明文字 |"
    assert tables_to_key_value(md) == md


def test_tables_to_key_value_ignores_fenced_code() -> None:
    md = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```\n\n正文 | 不转换 |\n|---|---|"
    out = tables_to_key_value(md)
    assert "| a | b |" in out  # 代码块内保留
    assert "正文 | 不转换 |" in out  # 无分隔行的普通行保留


def test_tables_to_key_value_short_row_pads_empty() -> None:
    md = "| A | B | C |\n|---|---|---|\n| 1 | 2 |"
    assert tables_to_key_value(md) == "第一行：A: 1; B: 2; C: "


# ---------- HTML 表格（MinerU 主输出）→ key:value ----------


def test_html_table_to_kv_basic() -> None:
    html = "<table><tr><td>模型</td><td>参数</td></tr><tr><td>qwen-vl-plus</td><td>20B</td></tr></table>"
    assert tables_to_key_value(html) == "第一行：模型: qwen-vl-plus; 参数: 20B"


def test_html_table_to_kv_rowspan_fills_merged_rows() -> None:
    """rowspan 单元格的值填充到其覆盖的多行，每行单行 + 第N行标注。"""
    html = (
        "<table><tr><td>Dataset</td><td>Metric</td><td>SBERT</td></tr>"
        '<tr><td rowspan="2">NCIT-DOID</td><td>MRR</td><td>0.879</td></tr>'
        "<tr><td>Hits@1</td><td>84.15</td></tr>"
        "<tr><td>OMIM-ORDO</td><td>MRR</td><td>0.707</td></tr>"
        "</table>"
    )
    out = tables_to_key_value(html)
    assert "第一行：Dataset: NCIT-DOID; Metric: MRR; SBERT: 0.879" in out
    assert "第二行：Dataset: NCIT-DOID; Metric: Hits@1; SBERT: 84.15" in out  # rowspan 已填充
    assert "第三行：Dataset: OMIM-ORDO; Metric: MRR; SBERT: 0.707" in out
    assert "\n" not in out  # 整表连成一行（行间无换行）


def test_html_table_to_kv_colspan_fills_columns() -> None:
    html = (
        "<table><tr><td colspan=\"2\">合并标题</td><td>C</td></tr>"
        "<tr><td>1</td><td>2</td><td>3</td></tr></table>"
    )
    assert tables_to_key_value(html) == "第一行：合并标题: 1; 合并标题: 2; C: 3"


def test_tables_to_key_value_handles_inline_html() -> None:
    """HTML 表格嵌在 md 正文里也能被替换为 kv。"""
    md = "见表：\n\n<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>\n\n后文。"
    out = tables_to_key_value(md)
    assert "<table" not in out
    assert "第一行：A: 1; B: 2" in out
    assert "见表：" in out and "后文。" in out


def test_html_table_to_kv_no_data_row_preserved() -> None:
    """只有表头没有数据行 → 视为非表格，原样保留。"""
    html = "<table><tr><td>A</td><td>B</td></tr></table>"
    assert tables_to_key_value(html) == html


# ---------- 图片 → VL 描述 ----------


def test_describe_images_replaces_ref() -> None:
    md = "上文填充" * 30 + "![](images/1.jpg)" + "下文填充" * 30
    images = {"images/1.jpg": b"\xff\xd8\xff"}
    llm = _FakeLLM(answer="描述：这是系统架构图。")
    out = describe_images(md, images, llm)
    assert "![](images/1.jpg)" not in out
    assert "描述：这是系统架构图。" in out
    assert len(llm.calls) == 1


def test_describe_images_context_exact_100_chars() -> None:
    """上文/下文各恰好 100 字传入 VL，且图片为 base64 data URI。"""
    md = "前" * 200 + "![](images/1.jpg)" + "后" * 200
    llm = _FakeLLM()
    describe_images(md, {"images/1.jpg": b"\xff\xd8\xff"}, llm)

    human = llm.calls[0][1]  # [System, Human]
    content = human.content
    text_part = next(p for p in content if p["type"] == "text")
    assert "上文：" + "前" * 100 in text_part["text"]
    assert "前" * 101 not in text_part["text"]
    assert "下图：" + "后" * 100 in text_part["text"]
    img_part = next(p for p in content if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_describe_images_trims_at_doc_boundary() -> None:
    """文档开头无上文时，上文截取为空而不报错。"""
    md = "![](images/1.jpg)" + "正文" * 50
    llm = _FakeLLM()
    describe_images(md, {"images/1.jpg": b"x"}, llm)
    text_part = next(p for p in llm.calls[0][1].content if p["type"] == "text")
    assert text_part["text"].startswith("上文：\n")


def test_describe_images_unknown_ref_preserved() -> None:
    md = "见下图：![](missing/1.jpg)。"
    out = describe_images(md, {"images/2.jpg": b"x"}, _FakeLLM())
    assert out == md


def test_enhance_markdown_combines_both() -> None:
    md = "正文前\n\n| 名 | 值 |\n|---|---|\n| A | 1 |\n\n流程图：![](images/1.jpg)"
    images = {"images/1.jpg": b"\xff\xd8\xff"}
    llm = _FakeLLM(answer="图：流程示意。")
    out = enhance_markdown(md, images, llm)
    assert "第一行：名: A; 值: 1" in out
    assert "图：流程示意。" in out
    assert "![](images/1.jpg)" not in out
    assert "| 名 | 值 |" not in out
