"""学习推送工具（docs/06 §4.6）：渠道分发（mock 默认，渠道可扩展）。

设计要点（docs/01 US-PU-4）：
- `Channel` 为渠道接口；新增渠道只需实现 `send(content) -> bool` 并在 `CHANNELS`
  注册，业务代码零改动（渠道层可插拔）。
- 演示默认 `mock`：触达内容写日志 + 控制台打印（docs/06 §4.6）。
- wechat/email/sms 为预留渠道名；注册表缺失时回退 mock 并告警。

`schedule_push` 由 push_agent 的 persist 节点与 scheduler 调度器共用；
分发不依赖请求上下文，可在后台任务中直接调用。
"""
from langchain_core.tools import tool

from app.core.logging import get_logger

logger = get_logger("push_tool")


class Channel:
    """推送渠道接口：实现 send(content) -> bool 即可接入新渠道。"""

    name = "base"

    def send(self, content: str) -> bool:
        """触达一条内容，返回是否成功。"""
        raise NotImplementedError


class MockChannel(Channel):
    """演示渠道：写日志 + 控制台打印，恒成功（docs/06 §4.6）。"""

    name = "mock"

    def send(self, content: str) -> bool:
        """把触达内容写入日志与控制台（模拟真实推送）。"""
        logger.info("[push mock 触达] %s", content)
        print(f"[push mock 触达] {content}", flush=True)
        return True


# 渠道注册表：新增渠道在此登记（如 WeChatChannel / EmailChannel / SMSChannel）
CHANNELS: dict[str, type[Channel]] = {"mock": MockChannel}


def dispatch_push(task: dict) -> bool:
    """按任务渠道分发触达内容（未知渠道回退 mock 并告警）。

    Args:
        task: 推送任务字典，需含 content 与 channel。

    Returns:
        是否分发成功（供 push_logs 记录 success/failed）。
    """
    content = str(task.get("content", ""))
    channel_name = str(task.get("channel") or "mock")
    cls = CHANNELS.get(channel_name, MockChannel)
    if channel_name not in CHANNELS:
        logger.warning("推送渠道 %s 未注册，回退 mock", channel_name)
    try:
        return cls().send(content)
    except Exception as exc:
        logger.exception("推送渠道 %s 触达失败: %s", channel_name, exc)
        return False


@tool
def schedule_push(task: dict, channel: str = "mock") -> bool:
    """推送触达：把任务内容经指定渠道分发（演示默认 mock，写日志/控制台）。
    task 需含 content 字段；channel 取值 mock/wechat/email/sms（未注册渠道回退 mock）。
    返回是否分发成功。
    """
    return dispatch_push({**task, "channel": channel})


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [schedule_push]
