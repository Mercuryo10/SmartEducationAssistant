"""Markdown 后处理（阶段 7.2 增强）：图片→VL 文本描述、表格→key:value。

MinerU 转出的 Markdown 含 `![](images/xxx.jpg)` 图片引用、GFM 管道表格与
**HTML 表格**（`<table><tr><td>...`，常为单行、含 rowspan/colspan 合并单元格）。本模块：
1. `describe_images`：把每张图片与其「上文/下文各 100 字」喂给千问 qwen-vl-plus，
   生成文本描述替换图片，使产物成为纯文本，可被阶段 7.1 标题感知分块、进入向量库。
2. `tables_to_key_value`：把 HTML 表格（MinerU 主输出）与 GFM 管道表格**确定性**转换
   为 key:value 形式（表头作 key、每行数据单行且行首加「第N行」标注、**整表连成一行**
   行间无换行；合并单元格的值填充到其覆盖的行/列），不消耗 LLM 额度。

VL 客户端一律经 `app/services/llm.py` 的 `get_vision_llm()` 工厂获取（docs/08 §4）；
本模块只依赖其 `.invoke([SystemMessage, HumanMessage]) -> BaseMessage` 接口，
便于单测注入 stub（离线跑）。同步实现（脚本场景）。
"""
import base64
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.logging import get_logger

logger = get_logger("md_enhancer")

DEFAULT_CONTEXT_CHARS = 100  # 图片上文/下文各取字数（docs/09 阶段 7.2）

_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
_SYSTEM_PROMPT = (
    "你是教材图片描述助手。请结合图片内容和给定的上下文，生成一段准确、自包含的中文"
    "文字描述，用于在 Markdown 教材中替换该图片。直接输出描述正文，不要提及「图片」等"
    "字样，不要输出 Markdown 图片语法。"
)


def _content_to_text(content: Any) -> str:
    """把 LLM 返回的 content（字符串或分段列表）归一为纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def _data_uri(path: str, data: bytes) -> str:
    """构造 VL 可识别的 base64 data URI（mime 由文件后缀推断）。"""
    mime = _IMAGE_MIME.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _describe_one(llm: Any, key: str, data: bytes, before: str, after: str) -> str:
    """调用视觉 LLM 生成单张图片描述（带上下文与耗时日志）。"""
    t0 = time.perf_counter()
    content = [
        {"type": "text", "text": f"上文：{before}\n\n下图：{after}"},
        {"type": "image_url", "image_url": {"url": _data_uri(key, data)}},
    ]
    resp = llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=content)])
    desc = _content_to_text(resp.content).strip()
    logger.info("qwen-vl 图片描述: %s desc_chars=%d cost=%.1fs", key, len(desc), time.perf_counter() - t0)
    return desc


def describe_images(
    md: str,
    images: dict[str, bytes],
    llm: Any,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> str:
    """把 md 中每张可解析的图片替换为 qwen-vl-plus 生成的文本描述。

    Args:
        md: 含 `![](path)` 引用的 Markdown 文本。
        images: 图片字典（key 为 md 引用路径，如 `images/1.jpg`）。
        llm: 视觉 LLM（get_vision_llm() 或测试 stub），需实现 `.invoke(messages)`。
        context_chars: 图片上文/下文各取的字数。

    Returns:
        图片被描述替换后的 Markdown；images 中找不到的引用原样保留。
    """
    matches = list(_IMG_RE.finditer(md))
    if not matches:
        logger.info("md 中无图片引用，跳过图片增强")
        return md

    out: list[str] = []
    last, described = 0, 0
    for m in matches:
        path = m.group(1).strip()
        start, end = m.start(), m.end()
        out.append(md[last:start])

        key = path[2:] if path.startswith("./") else path
        data = images.get(key)
        if data is None or key.startswith("http"):
            out.append(md[start:end])  # 找不到图片 → 原样保留
        else:
            before = md[max(0, start - context_chars):start]
            after = md[end:end + context_chars]
            out.append(_describe_one(llm, key, data, before, after))
            described += 1
        last = end
    out.append(md[last:])
    logger.info("图片描述完成：%d/%d 张", described, len(matches))
    return "".join(out)


_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE_RE = re.compile(r"^\s*```")
_HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.DOTALL | re.IGNORECASE)


class _TableHTMLParser(HTMLParser):
    """解析 `<table>` HTML，提取行结构：每行 -> [(文本, rowspan, colspan), ...]。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int]]] = []
        self._cur_row: list[tuple[str, int, int]] | None = None
        self._cur_cell: list[str | int] | None = None  # [text, rowspan, colspan]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        a = dict(attrs)
        if tag == "table":
            pass
        elif tag == "tr":
            self._cur_row = []
        elif tag in ("td", "th") and self._cur_row is not None:
            self._cur_cell = ["" , _int_or(a.get("rowspan"), 1), _int_or(a.get("colspan"), 1)]

    def handle_data(self, data: str) -> None:
        if self._cur_cell is not None:
            self._cur_cell[0] = str(self._cur_cell[0]) + data  # type: ignore[operator]

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._cur_cell is not None and self._cur_row is not None:
            text = str(self._cur_cell[0]).strip().replace("\xa0", " ")
            self._cur_row.append((text, int(self._cur_cell[1]), int(self._cur_cell[2])))
            self._cur_cell = None
        elif tag == "tr" and self._cur_row is not None:
            self.rows.append(self._cur_row)
            self._cur_row = None


def _int_or(value: str | None, default: int) -> int:
    """解析 rowspan/colspan 属性；非法/空值回退默认 1。"""
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _expand_table(rows: list[list[tuple[str, int, int]]]) -> list[list[str]]:
    """把含 rowspan/colspan 的单元格展开为规整矩阵（合并值填充到被覆盖的行/列）。"""
    grid: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}  # col -> (文本, 剩余行数)
    for row in rows:
        out: list[str] = []
        col = 0
        i = 0
        while i < len(row) or col in pending:
            if col in pending:
                text, remain = pending[col]
                out.append(text)
                if remain <= 1:
                    del pending[col]
                else:
                    pending[col] = (text, remain - 1)
                col += 1
            elif i < len(row):
                text, rs, cs = row[i]
                for _ in range(cs):
                    out.append(text)
                    if rs > 1:
                        pending[col] = (text, rs - 1)
                    col += 1
                i += 1
        grid.append(out)
    return grid


def _html_table_to_kv(html: str) -> str | None:
    """把单个 `<table>` HTML 转「每行单行 key:value（行首第N行标注）」；缺数据行/解析失败返回 None（原样保留）。"""
    parser = _TableHTMLParser()
    parser.feed(html)
    rows = parser.rows
    if len(rows) < 2:
        return None
    grid = _expand_table(rows)
    header = grid[0]
    lines = [f"第{_cn_num(idx)}行：{_kv_one_line(header, row)}" for idx, row in enumerate(grid[1:], start=1)]
    return "; ".join(lines) if lines else None  # 整表连成一行（行间无换行）


def _split_cells(line: str) -> list[str]:
    """拆分 GFM 表格行单元格：去首尾管道、去加粗/行内代码符号、去空白。"""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return [re.sub(r"\*+|`", "", c) for c in cells]


def _is_separator(cells: list[str]) -> bool:
    """表头分隔行：全部单元格仅含 : 与 -（如 |---|:---:|）。"""
    return bool(cells) and all(re.fullmatch(r":?-+:?", c.strip()) for c in cells)


_CN_DIGITS = "零一二三四五六七八九"


def _cn_num(n: int) -> str:
    """整数转中文数字（1→一、11→十一、21→二十一、105→一百零五；≤999）。"""
    if n <= 0:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        t, o = divmod(n, 10)
        return _CN_DIGITS[t] + "十" + (_CN_DIGITS[o] if o else "")
    h, rest = divmod(n, 100)
    if rest == 0:
        return _CN_DIGITS[h] + "百"
    if rest < 10:
        return _CN_DIGITS[h] + "百零" + _CN_DIGITS[rest]
    return _CN_DIGITS[h] + "百" + _cn_num(rest)


def _kv_one_line(header: list[str], row: list[str]) -> str:
    """把一行数据拼成单行 key:value（key: value 用 ; 连接）。"""
    kv = [f"{k}: {v}" for k, v in zip(header, row)]
    kv += [f"字段{i + 1}: {v}" for i, v in enumerate(row[len(header):])]  # 行比表头多列
    kv += [f"{k}: " for k in header[len(row):]]  # 列数不足补空值
    return "; ".join(kv)


def _convert_table(block: list[str]) -> str | None:
    """把单个 GFM 表格块转为「每行单行 key:value（行首第N行标注）」；缺分隔行则不是表格，返回 None。"""
    if len(block) < 2:
        return None
    header = _split_cells(block[0])
    if not _is_separator(_split_cells(block[1])):
        return None
    lines = [
        f"第{_cn_num(idx)}行：{_kv_one_line(header, row)}"
        for idx, row in enumerate((_split_cells(l) for l in block[2:]), start=1)
    ]
    return "; ".join(lines) if lines else None  # 整表连成一行（行间无换行）


def tables_to_key_value(md: str) -> str:
    """把 md 中的表格转换为 key:value 形式（表头作 key、每行数据一组）。

    处理两种来源：
    - **HTML 表格**（MinerU 主输出，`<table>...</table>`）：含 rowspan/colspan
      合并单元格时，合并值填充到其覆盖的行/列；解析失败原样保留。
    - **GFM 管道表格**：仅识别「表头 + 分隔行」的管道表格；无分隔行的 `| xxx |`
      视为普通文本保留；代码块（``` 围栏）内的表格不转换，避免误伤代码。
    """
    # 1) HTML 表格 → kv（逐块替换；解析失败保留原样）
    md = _HTML_TABLE_RE.sub(
        lambda m: _html_table_to_kv(m.group(0)) or m.group(0), md
    )

    # 2) GFM 管道表格 → kv
    lines = md.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if not in_fence and _TABLE_LINE_RE.match(line):
            j = i
            while j < len(lines) and _TABLE_LINE_RE.match(lines[j]):
                j += 1
            block = lines[i:j]
            converted = _convert_table(block)
            if converted is not None:
                out.append(converted)
            else:
                out.extend(block)
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def enhance_markdown(
    md: str,
    images: dict[str, bytes],
    llm: Any,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> str:
    """阶段 7.2 md 增强：先图片→VL 描述，再表格→key:value。"""
    md = describe_images(md, images, llm, context_chars)
    return tables_to_key_value(md)
