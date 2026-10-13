"""
Draw Things 后端通道抽象

统一 HTTP 与 gRPC 两种调用方式，对上层暴露一致的接口，并提供自动降级。

选路策略
--------
1. 优先 gRPC（支持实时进度、图生图、LoRA、ControlNet）
2. gRPC 不可用（未开启 / 端口不通 / TLS 失败）时自动降级到 HTTP
3. 可通过配置强制指定通道：config.json 里 `"drawthings_channel": "grpc" | "http" | "auto"`

两条通道都返回统一结构：
    {
        "image_data": bytes,       # PNG 字节（已解码）
        "seed": int,               # 实际使用的 seed
        "channel": "grpc"|"http",  # 实际走的通道
        "progress": list,          # 进度记录（仅 gRPC 有真实数据）
    }
"""

import logging
import re
import threading
import time

import requests

try:
    from src.grpc_client import DrawThingsGrpcClient, GrpcUnavailableError, decode_result_to_png
    from src import dt_config
except ModuleNotFoundError:
    from grpc_client import DrawThingsGrpcClient, GrpcUnavailableError, decode_result_to_png
    import dt_config

backend_logger = logging.getLogger('backend')
backend_logger.setLevel(logging.INFO)

# 全局 gRPC 客户端（复用 channel）
_grpc_client = None
_grpc_client_lock = threading.Lock()
_grpc_available_cache = {"value": None, "checked_at": 0}

# 探测结果缓存有效期（秒），避免每次生图都做一次 Echo 往返
_GRPC_PROBE_TTL = 30


def get_grpc_client():
    """获取全局 gRPC 客户端（懒加载）

    Returns:
        DrawThingsGrpcClient: 客户端实例
    """
    global _grpc_client
    if _grpc_client is None:
        with _grpc_client_lock:
            if _grpc_client is None:
                _grpc_client = DrawThingsGrpcClient(
                    host="127.0.0.1",
                    port=DEFAULT_GRPC_PORT,
                    use_tls=GRPC_USE_TLS,
                    shared_secret=GRPC_SHARED_SECRET,
                )
                backend_logger.info(
                    f"gRPC 客户端已创建: {_grpc_client.target} (TLS={GRPC_USE_TLS})"
                )
    return _grpc_client


def reset_grpc_cache():
    """清除 gRPC 可用性缓存（改配置后调用）"""
    _grpc_available_cache["value"] = None
    _grpc_available_cache["checked_at"] = 0


def is_grpc_available(force_check=False):
    """检测 gRPC 是否可用（带缓存）

    Args:
        force_check (bool): 忽略缓存强制探测

    Returns:
        bool: 可用返回 True
    """
    now = time.time()
    if not force_check:
        cached = _grpc_available_cache["value"]
        checked_at = _grpc_available_cache["checked_at"]
        if cached is not None and (now - checked_at) < _GRPC_PROBE_TTL:
            return cached

    try:
        # 超时给足，避免冷启动首连握手较慢导致误判为不可用（进而错误降级 HTTP）
        available = get_grpc_client().is_available(timeout=8)
    except Exception:
        available = False

    _grpc_available_cache["value"] = available
    _grpc_available_cache["checked_at"] = now

    if available:
        backend_logger.info("gRPC 服务可用")
    else:
        backend_logger.info("gRPC 服务不可用（将使用 HTTP 通道）")

    return available


def _normalize_sampler(sampler):
    """把前端传入的采样器规范化为枚举整数

    Args:
        sampler: int / str / None

    Returns:
        int | None: 枚举值，None 表示用默认值
    """
    if sampler is None or sampler == "":
        return None
    if isinstance(sampler, int):
        return sampler
    name = str(sampler).strip()
    # ⚠️ 不能写 SAMPLER_NAMES.get(name, int(name))：Python 会**先求值** int(name)，
    # 对非数字名字（如 "Euler a Trailing"）直接抛 ValueError 被吞 → 恒返回 None。
    if name in dt_config.SAMPLER_NAMES:
        return dt_config.SAMPLER_NAMES[name]
    try:
        return int(name)
    except (ValueError, TypeError):
        return None


def generate_via_grpc(params, progress_callback=None):
    """通过 gRPC 生成图片

    Args:
        params (dict): 生成参数，至少包含 prompt/width/height/steps/seed
        progress_callback (callable): 进度回调 (stage, step, total)

    Returns:
        dict: {"image_data": bytes, "seed": int, "channel": "grpc", "progress": list}

    Raises:
        GrpcUnavailableError: 服务不可达
    """
    # 套用模型推荐采样参数（仅补缺失字段，不覆盖用户显式值）
    apply_model_recommendations(params)

    client = get_grpc_client()

    # ---- 图生图：读取源图并转 DTTensor ----
    image_blob = None
    original_width = None
    original_height = None
    source_image = params.get("source_image")
    if source_image:
        import os
        from PIL import Image

        src_path = source_image
        if not os.path.isabs(src_path):
            src_path = os.path.join(IMAGES_DIR, os.path.basename(src_path))
        if os.path.exists(src_path):
            with Image.open(src_path) as img:
                rgb = img.convert("RGB")
                original_width, original_height = rgb.size
                import numpy as np
                from src import dt_tensor
                image_blob = dt_tensor.rgb_array_to_dt_tensor(np.asarray(rgb))

    result = client.generate_image(
        prompt=params.get("prompt", ""),
        negative_prompt=params.get("negative_prompt", ""),
        width=params.get("width", 512),
        height=params.get("height", 512),
        steps=params.get("steps", 8),
        seed=params.get("seed", -1),
        guidance_scale=params.get("guidance_scale", 3.5),
        sampler=_normalize_sampler(params.get("sampler")),
        # ⚠️ gRPC 必须**显式指定模型**：实测当前服务端（echo files=[]）在请求不带模型时
        # 会直接 INTERNAL "unknown error processing request"。前端不传 model 时用
        # config 的 default_model 兜底（该值须是服务端真实存在的模型文件名）。
        model=params.get("model") or DEFAULT_MODEL,
        strength=params.get("strength", 1.0),
        batch_size=params.get("batch_size", 1),
        original_width=original_width,
        original_height=original_height,
        loras=params.get("loras"),
        controls=params.get("controls"),
        resolution_dependent_shift=params.get("resolution_dependent_shift"),
        shift=params.get("shift"),
        progress_callback=progress_callback,
    )

    if not result["images"]:
        raise RuntimeError("gRPC 未返回图片数据")

    # ⚠️ gRPC 响应含多块「逐步预览」，前面是早期低质量/近噪声态，
    # 最后一块才是收敛后的成品。取 [-1]（取 [0] 会得到橙色渐变之类的中间态）。
    png_bytes = decode_result_to_png(result["images"][-1])

    return {
        "image_data": png_bytes,
        "seed": result.get("seed", -1),
        "channel": "grpc",
        "progress": result.get("progress", []),
    }


def generate_via_http(drawthings_url, params):
    """通过 HTTP 生成图片（原实现）

    Args:
        drawthings_url (str): DrawThings HTTP 服务地址
        params (dict): 生成参数

    Returns:
        dict: {"image_data": bytes, "seed": int, "channel": "http", "progress": []}

    Raises:
        Exception: 请求失败或无图片数据
    """
    # ⚠️ HTTP 通道【不要】注入模型推荐参数：
    # Draw Things 的 HTTP API 使用「画布当前设置」，且 sampler 必须是**字符串名**
    # （如 "Euler a"）——传 gRPC 用的整数枚举会直接
    # `DecodingError.typeMismatch: Expected ... String ... found number`。
    # 因此这里和旧实现保持一致：原样透传前端参数，采样参数由 Draw Things 画布决定。

    # 禁用代理以确保 DrawThings（127.0.0.1）能直连
    no_proxy = {"http": None, "https": None}
    response = requests.post(
        f"{drawthings_url}/sdapi/v1/txt2img",
        json=params,
        timeout=600,
        proxies=no_proxy,
    )

    if response.status_code != 200:
        # 尽量解析 DrawThings 的错误体，给出可操作的提示
        detail = ""
        try:
            body = response.json()
            detail = body.get("detail") or body.get("error") or ""
        except Exception:
            detail = (response.text or "").strip()[:300]
        if "Missing files for model" in detail:
            raise Exception(
                "DrawThings 缺少模型配套文件（Missing files for model）。"
                "请在 Draw Things 设置中开启 Model Browser，并补齐当前模型的 "
                "text encoder / VAE 等依赖文件后重试；或改用 gRPC / 桥接云端通道。"
            )
        raise Exception(
            f"DrawThings API 返回状态码: {response.status_code}"
            + (f"：{detail}" if detail else "")
        )

    result = response.json()

    if "images" in result and len(result["images"]) > 0:
        import base64
        image_base64 = result["images"][0]
    elif "data" in result:
        import base64
        image_base64 = result["data"]
    else:
        raise Exception("响应中没有图片数据")

    image_data = base64.b64decode(image_base64)

    # 通过根路径读取实际 seed（HTTP 响应里没有）
    seed = -1
    try:
        status_response = requests.get(drawthings_url, timeout=10, proxies=no_proxy)
        if status_response.status_code == 200:
            status_data = status_response.json()
            if "seed" in status_data:
                seed = status_data["seed"]
    except Exception as e:
        backend_logger.warning(f"读取 seed 失败: {e}")

    return {
        "image_data": image_data,
        "seed": seed,
        "channel": "http",
        "progress": [],
    }


def generate_image_auto(drawthings_url, params, channel="auto", progress_callback=None):
    """自动选择通道生成图片

    Args:
        drawthings_url (str): HTTP 服务地址（降级时用）
        params (dict): 生成参数
        channel (str): "auto" | "grpc" | "http"
        progress_callback (callable): 进度回调（仅 gRPC 生效）

    Returns:
        dict: {"image_data": bytes, "seed": int, "channel": str, "progress": list}

    Raises:
        Exception: 两条通道都失败
    """
    # 强制 HTTP：直接用 HTTP，不碰 gRPC
    if channel == "http":
        return generate_via_http(drawthings_url, params)

    # grpc / auto：**直接尝试 gRPC**（不预判，避免 is_grpc_available 冷启动误判）。
    #
    # 失败分两类，处理方式不同：
    #  - GrpcUnavailableError（UNAVAILABLE/UNIMPLEMENTED/DEADLINE）：真的"连不上"，
    #    auto 模式降级到 HTTP。
    #  - 其它（如 INTERNAL "unknown error processing request"）：服务端**已收到请求
    #    但处理出错**，多为单任务串行下的瞬时错误。降级 HTTP 没有意义（对纯 gRPC
    #    端口只会得到 415），故改为**重试 gRPC 一次**，仍失败则抛出原始错误信息。
    last_err = None
    for i in range(2):
        try:
            result = generate_via_grpc(params, progress_callback=progress_callback)
            result["fallback_reason"] = None
            return result
        except GrpcUnavailableError as e:
            last_err = e
            break
        except Exception as e:
            last_err = e
            if i == 0:
                backend_logger.warning(
                    f"gRPC 服务端错误，2 秒后重试一次: {str(e)[:120]}")
                time.sleep(2)

    if isinstance(last_err, GrpcUnavailableError):
        if channel == "grpc":
            raise last_err
        backend_logger.warning(f"gRPC 不可达，降级到 HTTP: {last_err}")
        reset_grpc_cache()
        return generate_via_http(drawthings_url, params)

    raise last_err


def generate_image_with_retry(drawthings_url, params, channel="auto",
                              progress_callback=None, retries=0, retry_delay=10):
    """生成图片，gRPC 通道失败时带重试

    ⚠️ 默认 retries=0，即不重试。

    Draw Things 是单任务串行的：上一个请求没跑完时新请求会排队。
    客户端超时后连接仍占着服务端队列，此时重试只会让队列越长、内存压力越大
    （实测多次重试会把整台机器拖到卡死）。
    所以宁可让本次失败，让用户显式重试，也不要自动堆积请求。

    Args:
        drawthings_url (str): HTTP 服务地址
        params (dict): 生成参数
        channel (str): "auto" | "grpc" | "http"
        progress_callback (callable): 进度回调
        retries (int): 额外重试次数，默认 0（不重试）
        retry_delay (int): 重试前等待秒数

    Returns:
        dict: 统一结果结构

    Raises:
        Exception: 所有重试都失败
    """
    import time as _time

    last_error = None
    for attempt in range(retries + 1):
        try:
            return generate_image_auto(drawthings_url, params, channel,
                                       progress_callback)
        except Exception as e:
            last_error = e
            if attempt < retries:
                backend_logger.warning(
                    f"第 {attempt + 1} 次尝试失败（{str(e)[:60]}），"
                    f"{retry_delay} 秒后重试"
                )
                reset_grpc_cache()
                _time.sleep(retry_delay)

    raise last_error


# 全局配置（由 app.py 启动时注入）
DEFAULT_GRPC_PORT = 7888
GRPC_USE_TLS = True
# Draw Things 设置里「共享密钥」启用时需要
GRPC_SHARED_SECRET = None
# 默认生图模型：仅作为「推荐采样参数」的匹配基准，不强制指定给服务端
DEFAULT_MODEL = None

# 模型推荐采样配置（Flow Matching / 蒸馏模型普遍适用 Euler a Trailing + 低 guidance）
# key 为模型名特征子串（lower + 去掉空格/连字符/下划线后做「包含」匹配）
# 可选字段 min_size：当前尺寸小于该值时自动提升（低于此分辨率模型不收敛）
MODEL_RECOMMENDED = {
    # Z Image Turbo：Euler a Trailing + 8 步 + guidance 2.5（实测出锐利图，
    # 用 DPM++ 2M Karras + 3.5 会出糊图）；512 起即可
    "zimagetturbo": {"sampler": 10, "steps": 8, "guidance_scale": 2.5},
    "zimageturbo": {"sampler": 10, "steps": 8, "guidance_scale": 2.5},
    # Qwen Image 2.1 Turbo：官方 **8 DDIM Trailing 步 + Text Guidance 1 + Shift 6.5**；
    # 分辨率必须 ≥1024（官方原生 2048+）。guidance>1 会过曝成色块。
    # ⚠️ sampler 必须用官方推荐的 **DDIM Trailing(16)**：基础版对采样器极敏感，
    # 用 Euler a Trailing 会整片偏色（实测 40 步出图全偏品红）。
    "qwenimage2.1turbo": {"sampler": 16, "steps": 8, "guidance_scale": 1.0, "min_size": 1024},
    "qwenimageturbo": {"sampler": 16, "steps": 8, "guidance_scale": 1.0, "min_size": 1024},
    # Qwen Image 2.1 基础版（非 turbo）：官方 **40 DDIM Trailing 步 + Text Guidance 1 + Shift 1**。
    # 放在 turbo 之后，保证子串匹配时 turbo 优先命中。
    "qwenimage2.1": {"sampler": 16, "steps": 40, "guidance_scale": 1.0, "min_size": 1024,
                     "resolution_dependent_shift": True},
    "qwenimage": {"sampler": 16, "steps": 40, "guidance_scale": 1.0, "min_size": 1024,
                  "resolution_dependent_shift": True},
}


def _normalize_model_name(name):
    """把模型名规范化为匹配键：小写 + 去掉空白/连字符/下划线"""
    return re.sub(r"[\s_\-]+", "", str(name).strip().lower())


def _match_recommended(model_name):
    """按模型名模糊匹配推荐配置（精确优先，其次特征子串包含）

    Args:
        model_name (str | None): 模型名

    Returns:
        dict | None: 推荐采样参数，未命中返回 None
    """
    if not model_name:
        return None
    key = _normalize_model_name(model_name)
    if key in MODEL_RECOMMENDED:
        return MODEL_RECOMMENDED[key]
    # 子串匹配：如 "qwenimage2.1turboq6p.ckpt" 命中 "qwenimage2.1turbo"
    for k, v in MODEL_RECOMMENDED.items():
        nk = _normalize_model_name(k)
        if nk and nk in key:
            return v
    return None


def list_samplers():
    """返回可用采样器名称列表（按枚举值顺序，供前端下拉使用）"""
    try:
        return list(dt_config.SAMPLER_NAMES.keys())
    except Exception:
        return []


def get_model_recommended(model_name):
    """返回某模型的推荐参数（供前端展示/自动填充），未命中返回 None

    Returns:
        dict | None: {"sampler": int, "sampler_name": str, "steps": int,
                      "guidance_scale": float, "min_size": int?}
    """
    rec = _match_recommended(model_name)
    if not rec:
        return None
    out = dict(rec)
    sid = rec.get("sampler")
    if sid is not None:
        try:
            out["sampler_name"] = dt_config.SAMPLER_VALUE_TO_NAME.get(sid, str(sid))
        except Exception:
            pass
    return out


def apply_model_recommendations(params):
    """根据模型名套用推荐采样参数（仅填补缺失/空字段，不覆盖用户显式值）

    规则：
    - steps / guidance_scale：前端未传（None/""/0）时填推荐值
      （0 表示「沿用推荐」，与 grpc_client 的语义一致）
    - sampler：仅在未传（None/""）时填；0 是合法枚举值（DPM++ 2M Karras），保留不覆盖
    - min_size：当前尺寸小于推荐下限时提升（低于该分辨率模型不收敛，如 qwen 需 ≥1024）
    - 不修改 model 字段本身，避免模型名与服务端不一致导致选错模型

    Args:
        params (dict): 生图参数（就地修改）

    Returns:
        dict: 同一个 params
    """
    model = params.get("model") or DEFAULT_MODEL
    rec = _match_recommended(model) if model else None
    if not rec:
        return params

    for field in ("steps", "guidance_scale"):
        if params.get(field) in (None, "", 0) and field in rec:
            params[field] = rec[field]
    if params.get("sampler") in (None, "") and "sampler" in rec:
        params["sampler"] = rec["sampler"]

    # bool / shift 类推荐参数（缺失才写，避免覆盖用户显式值）
    for field in ("resolution_dependent_shift", "shift"):
        if field in rec and params.get(field) is None:
            params[field] = rec[field]

    min_size = rec.get("min_size")
    if min_size:
        for field in ("width", "height"):
            v = params.get(field)
            if isinstance(v, (int, float)) and v < min_size:
                params[field] = int(min_size)
    return params


def configure(grpc_port=None, use_tls=None, shared_secret=None, default_model=None):
    """配置 gRPC 连接参数

    Args:
        grpc_port (int): gRPC 端口
        use_tls (bool): 是否启用 TLS
        shared_secret (str): 共享密钥（服务端启用鉴权时需要）

    Returns:
        None
    """
    global _grpc_client, DEFAULT_GRPC_PORT, GRPC_USE_TLS

    if grpc_port is not None:
        DEFAULT_GRPC_PORT = int(grpc_port)
    if use_tls is not None:
        GRPC_USE_TLS = bool(use_tls)
    if shared_secret is not None:
        global GRPC_SHARED_SECRET
        GRPC_SHARED_SECRET = shared_secret or None
    if default_model is not None:
        global DEFAULT_MODEL
        DEFAULT_MODEL = default_model or None

    # 参数变了就重建客户端
    _grpc_client = None
    reset_grpc_cache()

    backend_logger.info(
        f"gRPC 配置更新: port={DEFAULT_GRPC_PORT}, tls={GRPC_USE_TLS}"
    )