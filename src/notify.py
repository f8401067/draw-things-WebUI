"""
ntfy 通知模块

在图片生成完成后，向 ntfy 推送完成通知。
使用 ntfy 官方默认服务器 https://ntfy.sh ，用户可在配置中覆盖。
"""

import os
import sys
import threading
import logging

import requests

# 默认使用 ntfy 官方服务器
DEFAULT_NTFY_SERVER = "https://ntfy.sh"

# 推送超时时间（秒）
NTFY_TIMEOUT = 10

# 通知日志
notify_logger = logging.getLogger('notify')
notify_logger.setLevel(logging.INFO)


def get_ntfy_server(user_id=None):
    """获取 ntfy 服务器地址

    优先级：用户配置 > config.json > ntfy 默认服务器

    Args:
        user_id (int): 用户 ID

    Returns:
        str: ntfy 服务器地址（不含尾部斜杠）
    """
    server = None

    if user_id:
        try:
            try:
                from src.database import get_user_notify_config
            except ModuleNotFoundError:
                from database import get_user_notify_config
            cfg = get_user_notify_config(user_id)
            server = (cfg or {}).get("ntfy_server")
        except Exception:
            server = None

    if not server:
        try:
            server = _load_config_json().get("ntfy_server")
        except Exception:
            server = None

    return (server or DEFAULT_NTFY_SERVER).rstrip("/")


def _load_config_json():
    """从 config.json 读取配置（依赖 APP_ROOT_DIR 环境变量）"""
    import json
    from pathlib import Path

    app_root = os.environ.get('APP_ROOT_DIR')
    if not app_root:
        return {}
    config_path = Path(app_root) / "config.json"
    if not config_path.exists():
        return {}
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_user_notify_config(user_id):
    """读取用户完整的 ntfy 配置

    Args:
        user_id (int): 用户 ID

    Returns:
        dict: {"ntfy_topic": str, "ntfy_server": str}
    """
    if not user_id:
        return {}
    try:
        try:
            from src.database import get_user_notify_config as _get
        except ModuleNotFoundError:
            from database import get_user_notify_config as _get
        return _get(user_id) or {}
    except Exception as e:
        notify_logger.warning(f"读取用户 ntfy 配置失败: {e}")
        return {}


def get_user_topic(user_id):
    """读取用户配置的 ntfy 推送主题

    Args:
        user_id (int): 用户 ID

    Returns:
        str: 主题名，未配置返回空字符串
    """
    if not user_id:
        return ""
    try:
        try:
            from src.database import get_user_notify_config
        except ModuleNotFoundError:
            from database import get_user_notify_config
        cfg = get_user_notify_config(user_id) or {}
        return (cfg.get("ntfy_topic") or "").strip()
    except Exception as e:
        notify_logger.warning(f"读取用户 ntfy 配置失败: {e}")
        return ""


def push_ntfy(topic, title, message, server=None, tags=None, click=None):
    """向 ntfy 推送一条消息

    实现要点：
    - 标题/图标/点击链接通过 HTTP header（Title / Tags / Click）传递，这是 ntfy 的标准用法。
      注意 header 只能承载 latin-1，必须传bytes 而非 str，否则中文和 emoji 会抛
      UnicodeEncodeError。requests 接受 bytes 形式的 header，会原样发送 UTF-8 字节。
    - ntfy.sh 不解析 application/json 请求体（会把整个 JSON 当成消息文本），
      所以不能用 json= 方式提交。

    Args:
        topic (str): 推送主题
        title (str): 消息标题
        message (str): 消息正文
        server (str): ntfy 服务器地址，默认使用 ntfy 官方服务器
        tags (str): ntfy emoji tags，如 "white_check_mark"
        click (str): 点击消息时跳转的 URL

    Returns:
        bool: 推送成功返回 True
    """
    topic = (topic or "").strip().lstrip("/")
    if not topic:
        notify_logger.info("未配置 ntfy 主题，跳过推送")
        return False

    server = (server or DEFAULT_NTFY_SERVER).rstrip("/")
    url = f"{server}/{topic}"

    # header 值统一用 UTF-8 bytes，规避 latin-1 编码限制
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if title:
        headers["Title"] = str(title).encode("utf-8")
    if tags:
        headers["Tags"] = str(tags).encode("utf-8")
    if click:
        headers["Click"] = str(click).encode("utf-8")

    try:
        response = requests.post(
            url,
            data=(message or "").encode("utf-8"),
            headers=headers,
            timeout=NTFY_TIMEOUT,
        )
        if response.status_code == 200:
            notify_logger.info(f"ntfy 推送成功 - 主题: {topic}")
            return True
        notify_logger.error(
            f"ntfy 推送失败 - 主题: {topic}, 状态码: {response.status_code}, 响应: {response.text[:200]}"
        )
        return False
    except Exception as e:
        notify_logger.error(f"ntfy 推送异常 - 主题: {topic}, 错误: {e}")
        return False


def notify_generation_done(user_id, prompt="", image_filename="",
                           width=0, height=0, steps=0, seed=-1,
                           elapsed_time=0.0, base_url=""):
    """生成成功后推送 ntfy 通知

    Args:
        user_id (int): 用户 ID（未配置主题时直接返回）
        prompt (str): 提示词
        image_filename (str): 生成的文件名
        width (int): 宽度
        height (int): 高度
        steps (int): 步数
        seed (int): Seed
        elapsed_time (float): 耗时（秒）
        base_url (str): WebUI 访问地址，用于点击跳转

    Returns:
        None
    """
    topic = get_user_topic(user_id)
    if not topic:
        return

    server = get_ntfy_server(user_id)

    prompt = (prompt or "").strip().replace("\n", " ")
    if len(prompt) > 120:
        prompt = prompt[:120] + "..."

    lines = []
    if prompt:
        lines.append(f"提示词: {prompt}")
    lines.append(f"尺寸: {width}x{height} | 步数: {steps} | Seed: {seed}")
    lines.append(f"耗时: {elapsed_time:.2f} 秒")

    click = None
    if base_url and image_filename:
        click = f"{base_url.rstrip('/')}/generated_images/{image_filename}"

    push_ntfy(
        topic=topic,
        title="✅ 图片生成完成",
        message="\n".join(lines),
        server=server,
        tags="white_check_mark",
        click=click,
    )


def async_notify_generation_done(**kwargs):
    """后台线程推送通知，不阻塞生成请求

    Args:
        **kwargs: 透传给 notify_generation_done 的参数

    Returns:
        threading.Thread: 已启动的线程
    """
    def task():
        try:
            notify_generation_done(**kwargs)
        except Exception as e:
            notify_logger.error(f"异步通知推送失败: {e}")

    thread = threading.Thread(target=task, daemon=True)
    thread.start()
    return thread


def test_notify(user_id, topic):
    """发送一条测试通知

    Args:
        user_id (int): 用户 ID
        topic (str): 主题名

    Returns:
        dict: {success, error}
    """
    server = get_ntfy_server(user_id)
    ok = push_ntfy(
        topic=topic,
        title="🔔 DrawThings WebUI",
        message="通知配置成功，图片生成完成后会在此收到推送。",
        server=server,
        tags="bell",
    )
    if ok:
        return {"success": True, "message": "测试通知已发送"}
    return {"success": False, "error": "推送失败，请检查主题名是否正确"}