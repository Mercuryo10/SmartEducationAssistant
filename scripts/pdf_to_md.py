"""阶段 7.2：调用 MinerU API 把 PDF 教材批量转换为 .md（可选增强）。

转换出的 .md 可直接放入 scripts/demo_data/，经阶段 7.1 标题感知分块进入知识库
（或交给 build_kb.py --strategy heading 扫描）。

用法：python scripts/pdf_to_md.py [--input data/pdfs] [--output data/md] [--force] [--enhance]
- 对 input 目录下每个 .pdf：调 MinerU API 解析 → 写 <stem>.md 到 output。
- 默认跳过已转换的 .md（幂等）；--force 强制重新转换。
- --enhance：图片喂 qwen-vl-plus（上文/下文各 100 字）生成文本描述替换、表格转 key:value
  （见 docs/09 阶段 7.2 增强；需 QWEN_API_KEY，会消耗千问 VL 额度）。
- 需要 .env 配置 MINERU_API_URL 与 MINERU_TOKEN（官方云端 API v4）。
"""
import argparse
import sys
from pathlib import Path

# 使 `app` 包可导入（以项目根为运行目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.services.md_enhancer import enhance_markdown  # noqa: E402
from app.services.mineru_service import get_mineru_service  # noqa: E402

logger = get_logger("pdf_to_md")


def main() -> None:
    """批量转换 PDF → MD（幂等，--force 重转；--enhance 图片描述+表格转 kv）。"""
    parser = argparse.ArgumentParser(description="调用 MinerU API 把 PDF 教材转换为 Markdown")
    parser.add_argument("--input", default="data/pdfs", help="PDF 目录（默认 data/pdfs）")
    parser.add_argument("--output", default="data/md", help="输出 .md 目录（默认 data/md）")
    parser.add_argument("--force", action="store_true", help="强制重新转换已存在的 .md")
    parser.add_argument("--enhance", action="store_true", help="增强：图片喂 qwen-vl-plus 生成文本描述替换 + 表格转 key:value")
    args = parser.parse_args()

    setup_logging()
    src_dir = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(src_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("未找到 PDF 文件：%s（请把教材 PDF 放入该目录）", src_dir)
        return

    svc = get_mineru_service()
    if not svc.is_configured():
        logger.error("MinerU 未配置：请在 .env 设置 MINERU_API_URL 与 MINERU_TOKEN（官方云端 API v4，Token 在 https://mineru.net/apiManage/token 申请）")
        return

    vision = None
    if args.enhance:
        if not settings.qwen_api_key:
            logger.error("--enhance 需要 QWEN_API_KEY（图片描述调 qwen-vl-plus），请在 .env 配置后重试")
            return
        from app.services.llm import get_vision_llm  # noqa: PLC0415  惰性导入，仅增强时构造

        vision = get_vision_llm()

    ok, failed = 0, 0
    for pdf in pdfs:
        target = out_dir / f"{pdf.stem}.md"
        if target.exists() and not args.force:
            logger.info("跳过已转换：%s（--force 可强制重转）", target.name)
            continue
        try:
            if vision is not None:
                md, images = svc.convert_pdf_to_md_with_images(pdf)
                md = enhance_markdown(md, images, vision)
                tag = "已转换（增强）"
            else:
                md = svc.convert_pdf_to_md(pdf)
                tag = "已转换"
            target.write_text(md, encoding="utf-8")
            logger.info("%s：%s → %s（%d 字符）", tag, pdf.name, target.name, len(md))
            ok += 1
        except Exception as exc:  # noqa: BLE001 批量脚本：单文件失败不中断（含 LLM 异常）
            logger.error("转换失败 %s：%s", pdf.name, exc)
            failed += 1

    logger.info("完成：成功 %d，失败 %d（输出目录 %s）", ok, failed, out_dir)


if __name__ == "__main__":
    main()
