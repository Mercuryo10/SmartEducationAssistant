"""MinerU API 客户端（阶段 7.2：PDF → Markdown）。

调用 MinerU **官方云端 API v4**（mineru.net）把 PDF 解析为 Markdown，
产物可进入知识库（阶段 7.1 标题感知分块）。契约（见 docs/09 阶段 7.2）：
- `POST /file-urls/batch`             申请文件上传链接，返回 batch_id + file_urls
- `PUT <file_urls[i]>`                直传本地文件到签名 URL（无需鉴权头）
- `GET /extract-results/batch/{id}`   轮询状态 waiting-file/pending/running/converting/done/failed
- `GET <full_zip_url>`                下载结果 zip（内含 full.md + images/ + json）
- 鉴权：请求头 `Authorization: Bearer <MINERU_TOKEN>`

要点：
- 只依赖 `settings.mineru_api_url` / `settings.mineru_token` 与 httpx；
  未配置（URL 或 Token 任一为空）时调用抛结构化错误。
- 同步实现（脚本场景）；若将来在 API 中调用需经线程池避免阻塞事件循环。
- 关键链路（提交/上传/轮询/下载/解压）记录耗时日志（docs/08 §6）。
- 鉴权失败返回 `{"success":false,"msgCode","msg"}`，业务失败返回 `{"code":!=0,"msg"}`，
  与成功 `{"code":0,"data":{...}}` 是两套结构，统一收敛为 ToolExecutionError。
"""
import io
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import ToolExecutionError, ValidationError
from app.core.logging import get_logger

logger = get_logger("mineru_service")

# MinerU 官方云端 API 默认解析模型（文档推荐 vlm；pipeline 为传统管线）
_MODEL_VERSION = "vlm"
# 解析完成 / 失败状态（兼容不同文档版本的写法）
_DONE_STATES = {"done", "completed", "success", "finished"}
_FAIL_STATES = {"failed", "error"}
# 结果 zip 内视为图片的后缀（供 md 增强时提取图片字节）
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".svg", ".tif", ".tiff")


class MineruService:
    """封装 MinerU 官方云端 API v4 的 PDF→MD 转换。"""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        client: httpx.Client | None = None,
        poll_interval: float | None = None,
        timeout: float | None = None,
    ) -> None:
        """初始化。

        Args:
            base_url: MinerU API 基地址，默认 settings.mineru_api_url。
            token: Bearer Token，默认 settings.mineru_token。
            client: 注入的 httpx.Client（测试用 MockTransport；默认自建）。
            poll_interval: 状态轮询间隔（秒），默认取 settings。
            timeout: 单任务最大等待（秒），默认取 settings。
        """
        self.base_url = (base_url if base_url is not None else settings.mineru_api_url).rstrip("/")
        self.token = token if token is not None else settings.mineru_token
        self._client = client or httpx.Client(timeout=60)
        self.poll_interval = settings.mineru_poll_interval if poll_interval is None else poll_interval
        self.timeout = settings.mineru_timeout if timeout is None else timeout

    def is_configured(self) -> bool:
        """是否配置了 MinerU API（URL 与 Token 同时满足）。"""
        return bool(self.base_url and self.token)

    # ---------- 对外接口 ----------

    def convert_pdf_to_md(self, pdf_path: str | Path) -> str:
        """上传 PDF，轮询解析完成，下载并解压提取 Markdown（丢弃图片）。

        Args:
            pdf_path: .pdf 文件路径。

        Returns:
            Markdown 文本（MinerU 解析结果，即 zip 内主 .md）。

        Raises:
            ValidationError: 文件不存在或非 .pdf。
            ToolExecutionError: 未配置 / 上游失败 / 超时 / zip 缺 md。
        """
        md, _ = self._convert_package(pdf_path)
        return md

    def convert_pdf_to_md_with_images(self, pdf_path: str | Path) -> tuple[str, dict[str, bytes]]:
        """上传 PDF，返回 Markdown 与图片字典（供阶段 7.2 md 增强：图片→文本描述）。

        Args:
            pdf_path: .pdf 文件路径。

        Returns:
            (Markdown 文本, 图片字典)。图片 key 为 zip 内路径（如 `images/1.jpg`），
            与 md 中 `![](images/1.jpg)` 引用一致。

        Raises:
            同 convert_pdf_to_md。
        """
        return self._convert_package(pdf_path)

    def _convert_package(self, pdf_path: str | Path) -> tuple[str, dict[str, bytes]]:
        """完整转换流程，返回 (md, images)。"""
        p = Path(pdf_path)
        if not p.is_file():
            raise ValidationError(f"PDF 文件不存在: {pdf_path}")
        if p.suffix.lower() != ".pdf":
            raise ValidationError(f"不是 PDF 文件: {p.name}")
        if not self.is_configured():
            raise ToolExecutionError(
                "MinerU 未配置（settings.mineru_api_url 或 settings.mineru_token 为空），无法转换 PDF"
            )

        t0 = time.perf_counter()
        logger.info("MinerU 提交解析: %s", p.name)
        try:
            batch_id = self._submit(p)
            zip_url = self._wait_result(batch_id, p.name)
            zip_bytes = self._download_result(zip_url)
        except httpx.HTTPError as exc:
            raise ToolExecutionError(f"MinerU 请求失败: {exc}") from exc
        md, images = self._extract_package(zip_bytes)
        logger.info(
            "MinerU 解析完成: %s batch_id=%s md_chars=%d images=%d cost=%.1fs",
            p.name,
            batch_id,
            len(md),
            len(images),
            time.perf_counter() - t0,
        )
        return md, images

    # ---------- 内部步骤 ----------

    def _auth_headers(self) -> dict[str, str]:
        """官方云端 API 的鉴权头。"""
        return {"Authorization": f"Bearer {self.token}"}

    def _raise_on_error(self, resp: httpx.Response) -> dict[str, Any]:
        """校验响应：非 200 / 鉴权失败 / 业务失败统一抛 ToolExecutionError，成功返回 JSON。"""
        if resp.status_code != 200:
            raise ToolExecutionError(f"MinerU 请求失败 http={resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        if body.get("code") == 0:  # 业务成功
            return body
        # 网关/鉴权失败结构：{"success": false, "msgCode": "A0202", "msg": "..."}
        if body.get("success") is False:
            raise ToolExecutionError(
                f"MinerU 鉴权失败 {body.get('msgCode', '')}: {body.get('msg', '') or body}"
            )
        # 业务失败结构：{"code": !=0, "msg": "..."}
        raise ToolExecutionError(f"MinerU 业务错误 code={body.get('code')}: {body.get('msg', '') or body}")

    def _submit(self, pdf_path: Path) -> str:
        """申请上传链接并 PUT 直传文件，返回 batch_id。"""
        body = {
            "files": [{"name": pdf_path.name}],
            "model_version": _MODEL_VERSION,
            "enable_formula": True,
            "enable_table": True,
        }
        resp = self._client.post(
            f"{self.base_url}/file-urls/batch", json=body, headers=self._auth_headers()
        )
        result = self._raise_on_error(resp)
        data = result.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise ToolExecutionError(f"MinerU 响应缺少 batch_id/file_urls: {data}")
        self._upload_file(file_urls[0], pdf_path)
        logger.info("MinerU 文件已上传: %s batch_id=%s", pdf_path.name, batch_id)
        return str(batch_id)

    def _upload_file(self, upload_url: str, pdf_path: Path) -> None:
        """PUT 直传文件到签名 URL（上传成功后系统自动提交解析任务，无需鉴权头）。"""
        with pdf_path.open("rb") as fh:
            resp = self._client.put(upload_url, content=fh.read())
        if resp.status_code != 200:
            raise ToolExecutionError(f"MinerU 文件上传失败 http={resp.status_code}: {resp.text[:200]}")
        logger.info("MinerU 上传成功: %s", pdf_path.name)

    def _wait_result(self, batch_id: str, file_name: str) -> str:
        """轮询批量解析结果直到 done，返回 full_zip_url。"""
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            resp = self._client.get(url, headers=self._auth_headers())
            result = self._raise_on_error(resp)
            results = (result.get("data") or {}).get("extract_result") or []
            target = next((r for r in results if r.get("file_name") == file_name), None) or (
                results[0] if results else None
            )
            if target:
                state = str(target.get("state") or "").lower()
                if state in _DONE_STATES:
                    zip_url = target.get("full_zip_url")
                    if not zip_url:
                        raise ToolExecutionError(f"MinerU 任务完成但缺少 full_zip_url: {target}")
                    return str(zip_url)
                if state in _FAIL_STATES:
                    raise ToolExecutionError(
                        f"MinerU 任务解析失败 batch_id={batch_id}: {target.get('err_msg') or target}"
                    )
            time.sleep(self.poll_interval)
        raise ToolExecutionError(f"MinerU 任务超时 batch_id={batch_id}（>{self.timeout}s）")

    def _download_result(self, zip_url: str) -> bytes:
        """GET full_zip_url 下载结果 zip（签名链接，无需鉴权头）。"""
        resp = self._client.get(zip_url)
        if resp.status_code != 200:
            raise ToolExecutionError(f"MinerU 下载结果失败 http={resp.status_code}: {resp.text[:200]}")
        return resp.content

    @staticmethod
    def _extract_md(zip_bytes: bytes, pdf_stem: str = "") -> str:
        """从结果 zip 中提取主 Markdown 文本（兼容旧接口，丢弃图片）。"""
        return MineruService._extract_package(zip_bytes)[0]

    @staticmethod
    def _extract_package(zip_bytes: bytes) -> tuple[str, dict[str, bytes]]:
        """从结果 zip 中提取 (主 Markdown, 图片字典)。

        - 主 md：取顶层/最大的 .md（官方 zip 主文档为 full.md），跳过 images/ 目录。
        - 图片：收集 images/ 下的图片文件，key 为 zip 内路径，与 md 引用一致。

        Raises:
            ToolExecutionError: 非 zip / 缺 md。
        """
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as exc:
            raise ToolExecutionError("MinerU 结果不是有效的 zip 文件") from exc

        md_names = [n for n in zf.namelist() if n.lower().endswith(".md") and "images/" not in n.lower()]
        if not md_names:
            raise ToolExecutionError("MinerU 结果 zip 中未找到 markdown 文件")

        root_mds = [n for n in md_names if "/" not in n]  # 顶层 .md 优先
        candidates = root_mds or md_names
        best = max(candidates, key=lambda n: len(zf.read(n)))  # 内容最长者为主文档
        md = zf.read(best).decode("utf-8", errors="replace")

        images = {
            n: zf.read(n)
            for n in zf.namelist()
            if n.lower().endswith(_IMAGE_SUFFIXES) and "images/" in n.lower()
        }
        return md, images


def get_mineru_service() -> MineruService:
    """MinerU 服务工厂（惰性单例）：业务层统一从这里取。"""
    global _mineru_service
    if _mineru_service is None:
        _mineru_service = MineruService()
    return _mineru_service


_mineru_service: MineruService | None = None
