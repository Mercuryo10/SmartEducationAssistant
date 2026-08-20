"""MinerU API 客户端单测（阶段 7.2，docs/08 §10）。

用 httpx.MockTransport 模拟 MinerU 官方云端 API v4 流程，覆盖：
申请上传链接→PUT 上传→轮询 running→done→下载 zip 提取 md；failed 报错、
超时、鉴权失败（{success:false}）、业务错误（{code:!=0}）、上传失败、
zip 解压（含嵌套目录/多个 md 取最长/缺 md/坏 zip）、未配置（URL 或 Token 空）、
文件校验。全部离线运行。
"""
import io
import tempfile
import zipfile
from pathlib import Path

import httpx
import pytest

from app.core.exceptions import ToolExecutionError, ValidationError
from app.services.mineru_service import MineruService

UPLOAD_URL = "http://upload/b1"
ZIP_URL = "http://zip/b1.zip"


def _zip_bytes(md_text: str, md_name: str = "full.md") -> bytes:
    """构造含 md 与 images/ 的结果 zip（官方云端 zip 主文档为 full.md）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(md_name, md_text)
        zf.writestr("images/hash.jpg", b"img")
    return buf.getvalue()


def _make_service(handler, base_url="http://mineru", token="tk", timeout=5.0) -> MineruService:
    """用 MockTransport 构造 MinerU 客户端（轮询不等待）。"""
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)
    return MineruService(base_url=base_url, token=token, client=client, poll_interval=0.001, timeout=timeout)


def _pdf(tmp_dir: str = "data") -> Path:
    """构造一个假 pdf 文件（客户端不校验内容，仅上传）。"""
    p = Path(tempfile.mkdtemp()) / "book.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


def _submit_ok(request: httpx.Request) -> httpx.Response | None:
    """申请上传链接的响应（成功）。"""
    if request.method == "POST" and request.url.path == "/file-urls/batch":
        return httpx.Response(200, json={"code": 0, "data": {"batch_id": "b1", "file_urls": [UPLOAD_URL]}})
    return None


def _happy_handler(md_text: str):
    """成功路径：提交→上传→running→done→zip。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = _submit_ok(request)
        if resp is not None:
            return resp
        if request.method == "PUT" and request.url.path == "/b1":
            return httpx.Response(200, content=b"")
        if request.url.path == "/extract-results/batch/b1":
            calls["n"] += 1
            state = "running" if calls["n"] < 2 else "done"
            item = {"file_name": "book.pdf", "state": state}
            if state == "done":
                item["full_zip_url"] = ZIP_URL
            return httpx.Response(200, json={"code": 0, "data": {"batch_id": "b1", "extract_result": [item]}})
        if request.url.path == "/b1.zip":
            return httpx.Response(200, content=_zip_bytes(md_text))
        return httpx.Response(404)

    return handler


def test_convert_pdf_to_md_success() -> None:
    md = "# 标题\n\n正文内容。"
    svc = _make_service(_happy_handler(md))
    assert svc.convert_pdf_to_md(_pdf()) == md


def test_convert_pdf_to_md_with_images() -> None:
    """with_images 版本同时返回图片字典（key 为 zip 内路径，与 md 引用一致）。"""
    md = "# 标题\n\n![](images/hash.jpg)"
    svc = _make_service(_happy_handler(md))
    text, images = svc.convert_pdf_to_md_with_images(_pdf())
    assert text == md
    assert images.get("images/hash.jpg") == b"img"


def test_failed_state_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = _submit_ok(request)
        if resp is not None:
            return resp
        if request.method == "PUT":
            return httpx.Response(200)
        if request.url.path == "/extract-results/batch/b1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"batch_id": "b1", "extract_result": [
                    {"file_name": "book.pdf", "state": "failed", "err_msg": "文件格式不支持，请上传符合要求的文件类型"}
                ]}},
            )
        return httpx.Response(404)

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="解析失败"):
        svc.convert_pdf_to_md(_pdf())


def test_poll_timeout_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = _submit_ok(request)
        if resp is not None:
            return resp
        if request.method == "PUT":
            return httpx.Response(200)
        if request.url.path == "/extract-results/batch/b1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"batch_id": "b1", "extract_result": [
                    {"file_name": "book.pdf", "state": "running"}
                ]}},
            )
        return httpx.Response(404)

    svc = _make_service(handler, timeout=0.05)
    with pytest.raises(ToolExecutionError, match="超时"):
        svc.convert_pdf_to_md(_pdf())


def test_auth_failure_raises() -> None:
    """网关/鉴权失败是 {success:false,msgCode,msg} 结构。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "msgCode": "A0202", "msg": "user authenticate failed"})

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="鉴权失败"):
        svc.convert_pdf_to_md(_pdf())


def test_business_error_raises() -> None:
    """业务失败是 {code:!=0,msg} 结构。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 40010, "msg": "invalid file"})

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="业务错误"):
        svc.convert_pdf_to_md(_pdf())


def test_submit_non_200_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="http=500"):
        svc.convert_pdf_to_md(_pdf())


def test_upload_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = _submit_ok(request)
        if resp is not None:
            return resp
        if request.method == "PUT":
            return httpx.Response(403, text="forbidden")
        return httpx.Response(404)

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="上传失败"):
        svc.convert_pdf_to_md(_pdf())


def test_submit_missing_batch_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"file_urls": [UPLOAD_URL]}})  # 缺 batch_id

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="batch_id"):
        svc.convert_pdf_to_md(_pdf())


def test_not_configured_raises() -> None:
    """URL 与 Token 都为空 → 未配置，不应发起任何请求。"""
    svc = MineruService(base_url="", token="")
    with pytest.raises(ToolExecutionError, match="未配置"):
        svc.convert_pdf_to_md(_pdf())


def test_missing_token_raises() -> None:
    """URL 已配但 Token 为空 → 仍视为未配置。"""
    svc = MineruService(base_url="http://mineru", token="")
    with pytest.raises(ToolExecutionError, match="未配置"):
        svc.convert_pdf_to_md(_pdf())


def test_missing_file_raises() -> None:
    svc = _make_service(_happy_handler(""))
    with pytest.raises(ValidationError, match="不存在"):
        svc.convert_pdf_to_md("data/no_such.pdf")


def test_non_pdf_suffix_raises() -> None:
    svc = _make_service(_happy_handler(""))
    p = Path(tempfile.mkdtemp()) / "book.txt"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ValidationError, match="不是 PDF"):
        svc.convert_pdf_to_md(p)


def test_zip_without_md_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = _submit_ok(request)
        if resp is not None:
            return resp
        if request.method == "PUT":
            return httpx.Response(200)
        if request.url.path == "/extract-results/batch/b1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"batch_id": "b1", "extract_result": [
                    {"file_name": "book.pdf", "state": "done", "full_zip_url": ZIP_URL}
                ]}},
            )
        if request.url.path == "/b1.zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("images/x.jpg", b"img")  # 只有图片，无 md
            return httpx.Response(200, content=buf.getvalue())
        return httpx.Response(404)

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="未找到 markdown"):
        svc.convert_pdf_to_md(_pdf())


def test_done_without_zip_url_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = _submit_ok(request)
        if resp is not None:
            return resp
        if request.method == "PUT":
            return httpx.Response(200)
        if request.url.path == "/extract-results/batch/b1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"batch_id": "b1", "extract_result": [
                    {"file_name": "book.pdf", "state": "done"}  # done 但缺 full_zip_url
                ]}},
            )
        return httpx.Response(404)

    svc = _make_service(handler)
    with pytest.raises(ToolExecutionError, match="full_zip_url"):
        svc.convert_pdf_to_md(_pdf())


def test_extract_md_nested_dir() -> None:
    """zip 内 md 嵌套在单一顶层目录（hoist 场景）也能提取。"""
    zipb = _zip_bytes("# 嵌套", md_name="task-1/full.md")
    assert MineruService._extract_md(zipb, "book") == "# 嵌套"


def test_extract_md_picks_largest() -> None:
    """多个根级 .md 时取内容最长者（主文档）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.md", "短")
        zf.writestr("full.md", "# 主文档\n\n" + "正文内容" * 20)
    assert MineruService._extract_md(buf.getvalue(), "book") == "# 主文档\n\n" + "正文内容" * 20


def test_extract_md_bad_zip_raises() -> None:
    with pytest.raises(ToolExecutionError, match="zip"):
        MineruService._extract_md(b"not a zip", "book")
