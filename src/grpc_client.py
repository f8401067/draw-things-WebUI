"""
Draw Things gRPC 客户端

封装 ImageGenerationService 的调用，对外提供与 HTTP 版一致的接口，
额外支持进度流式回调（HTTP 版做不到）。

与 HTTP 通道的关键差异
----------------------
- 图片用 DTTensor 私有格式，不是 base64 PNG（见 dt_tensor.py）
- 生成参数用 FlatBuffers，不是 JSON（见 dt_config.py）
- 走服务端流，能实时拿到采样进度和中间预览

降级策略
--------
`generate_image` 会先探测 gRPC 可用性；不可用时由调用方回退到 HTTP 通道
（见 app.py 的_generate_via_http）。
"""

import logging
import socket
import ssl
import threading
import time

import grpc

try:
    from src.grpc_gen import imageService_pb2 as pb2
    from src.grpc_gen import imageService_pb2_grpc as pb2_grpc
    from src import dt_config, dt_tensor
    from src.drawthings_ca import _cert as DT_ROOT_CA, SSL_TARGET_NAME
except ModuleNotFoundError:
    from grpc_gen import imageService_pb2 as pb2
    from grpc_gen import imageService_pb2_grpc as pb2_grpc
    import dt_config
    import dt_tensor
    from drawthings_ca import _cert as DT_ROOT_CA, SSL_TARGET_NAME

grpc_logger = logging.getLogger('grpc_client')
grpc_logger.setLevel(logging.INFO)

# 默认 gRPC 端口（Draw Things 设置里可改）
DEFAULT_GRPC_PORT = 7888

# 单次生成超时（秒）
#
# ⚠️ 不要设太大。客户端超时后连接仍在服务端排队，会持续占用内存。
# Draw Things 是单任务串行，一个卡住的请求会让后续全部堆在队列里。
# 实测 256x256 / 4 步约 90秒，留 2 倍余量即可。
GENERATE_TIMEOUT = 300

# 单请求最大接收消息数（MB）。
# 256MB/条在高分辨率下会撑爆内存，128MB 足够 4K 图的 DTTensor。
MAX_MESSAGE_MB = 128

# 生成前的安全上限，防止误传超大参数把服务端/本机拖垮
MAX_WIDTH = 4096
MAX_HEIGHT = 4096
MAX_STEPS = 150

# 空闲判据：TLS 握手在该时间内完成即视为空闲（实测空闲时<100ms）
IDLE_HANDSHAKE_SEC = 1.5


def _decode_asset_list(raw):
    """解析 Echo / MetadataOverride 的资产清单

    官方 draw-things-comfyui 用 `json.loads(base64.b64decode(override[k]))`
    解析，即字段是 base64(UTF-8 JSON) 字节。但本机实测某些版本直接是裸
    UTF-8 JSON。两种都试：优先 base64，能解析成 JSON 才采用，否则回退裸文本。

    Args:
        raw (bytes): 原始字节

    Returns:
        list: 资产条目列表（可能是字符串，也可能是 dict——官方 ComfyUI
              返回的 models 项就是 dict，含路径/元数据）
    """
    if not raw:
        return []

    import base64
    import json

    # 尝试 1：官方方式 base64(UTF-8 JSON)
    try:
        decoded = base64.b64decode(raw)
        text = decoded.decode("utf-8", errors="ignore").strip()
        if text and text[0] in "[{":
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        pass

    # 尝试 2：裸 UTF-8 JSON（本机实测路径）
    try:
        text = raw.decode("utf-8", errors="ignore").strip()
        if text and text[0] in "[{":
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        pass

    # 兜底：换行 / 逗号分隔纯文本
    text = raw.decode("utf-8", errors="ignore").strip()
    items = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(items) == 1:
        for sep in (",", ";", "\x00"):
            if sep in items[0]:
                items = [x.strip() for x in items[0].split(sep) if x.strip()]
                break
    return items


def _normalize_secret(secret):
    """归一化共享密钥

    Draw Things 界面把密钥显示成带空格的分组形式（如 "MGT6 9RNR BSQW"），
    但服务端校验时需要的是去掉分隔符的原始字符串（"MGT69RNRBSQW"）。
    实测传带空格的版本会返回 sharedSecretMissing=True。

    Args:
        secret (str | None): 原始密钥

    Returns:
        str | None: 去掉空格/连字符/下划线的密钥；无值时返回 None
    """
    if not secret:
        return None
    return "".join(ch for ch in str(secret) if ch not in " \t-_")


class GrpcUnavailableError(Exception):
    """gRPC 服务不可用（未开启、端口不通、TLS 失败等）"""


class DrawThingsGrpcClient:
    """Draw Things gRPC 客户端

    线程安全：每个线程各自持有 channel。
    """

    def __init__(self, host="127.0.0.1", port=DEFAULT_GRPC_PORT, shared_secret=None,
                 use_tls=True, timeout=30):
        """初始化客户端

        Args:
            host (str): 服务地址
            port (int): 服务端口
            shared_secret (str): 共享密钥，服务端启用鉴权时需要
            use_tls (bool): 是否使用 TLS（Draw Things 默认启用自签证书）
            timeout (int): 普通 RPC 超时（秒）
        """
        self.host = host
        self.port = port
        # 密钥格式：Draw Things 界面显示为 "MGT6 9RNR BSQW"（含空格分组），
        # 但实际校验时不带分隔符 —— 实测传带空格版本会认证失败。
        # 这里统一归一化，兼容用户从界面直接复制。
        self.shared_secret = _normalize_secret(shared_secret)
        self.use_tls = use_tls
        self.timeout = timeout
        self._local = threading.local()
        self._root_cert = None
        # Draw Things 自签证书的 subject 是 CN=localhost，SAN 里也含 localhost 与 127.0.0.1。
        # grpc 会用 target 里的主机名做校验，这里显式覆盖成证书里的名字。
        self._ssl_target_name = SSL_TARGET_NAME

    @property
    def target(self):
        """str: gRPC 连接目标"""
        return f"{self.host}:{self.port}"

    def _get_channel(self):
        """获取或创建当前线程的 channel

        Returns:
            grpc.Channel: 可用的 channel
        """
        channel = getattr(self._local, "channel", None)
        if channel is None:
            options = [
                ('grpc.max_receive_message_length', MAX_MESSAGE_MB * 1024 * 1024),
                ('grpc.max_send_message_length', MAX_MESSAGE_MB * 1024 * 1024),
                # 关键：环境里通常有 HTTP_PROXY，gRPC 会自动走代理导致连不上本地服务，
                # 必须显式关闭，否则报 "ipv4:127.0.0.1:xxxx: HTTP proxy connect failed"
                ('grpc.enable_http_proxy', 0),
                # Draw Things 生图耗时较长（可能几分钟），必须保活，
                # 否则中途 GOAWAY 会导致 "FD shutdown"
                ('grpc.keepalive_time_ms', 120000),
                ('grpc.keepalive_timeout_ms', 30000),
                ('grpc.keepalive_permit_without_calls', 0),
            ]
            if self.use_tls:
                # 用内置的 Draw Things Root CA（官方同款）。
                # 不能用抓来的服务端证书代替——那样证书链不完整，握手会静默挂起。
                creds = grpc.ssl_channel_credentials(root_certificates=DT_ROOT_CA)
                options.append(('grpc.ssl_target_name_override', SSL_TARGET_NAME))
                channel = grpc.secure_channel(self.target, creds, options=options)
            else:
                channel = grpc.insecure_channel(self.target, options=options)
            self._local.channel = channel
        return channel

    def close(self):
        """关闭当前线程的 channel"""
        channel = getattr(self._local, "channel", None)
        if channel is not None:
            channel.close()
            self._local.channel = None

    def echo(self, timeout=None):
        """健康检查 + 获取服务端可用模型列表

        Args:
            timeout (int): 超时（秒）

        Returns:
            dict: {"message": str, "files": list, "server_identifier": int}

        Raises:
            GrpcUnavailableError: 服务不可达
        """
        request = pb2.EchoRequest(name="DrawThingsWebUI")
        if self.shared_secret:
            request.sharedSecret = self.shared_secret

        # TLS 自动协商：桥接/远程模式会强制 TLS，且设置来回切会导致
        # 固定 use_tls 失配（UNAVAILABLE）。失败时翻转重试一次。
        response = None
        for attempt in range(2):
            channel = self._get_channel()
            stub = pb2_grpc.ImageGenerationServiceStub(channel)
            try:
                response = stub.Echo(request, timeout=timeout or self.timeout)
                break
            except grpc.RpcError as e:
                # ⚠️ 服务端对「协议不匹配」的请求可能是**挂起到超时**（DEADLINE_EXCEEDED），
                # 而不一定是 UNAVAILABLE。若只认 UNAVAILABLE，use_tls 设错时会一直失败。
                # 故首次失败（UNAVAILABLE / DEADLINE_EXCEEDED）即翻转 use_tls 重试一次。
                if e.code() in (grpc.StatusCode.UNAVAILABLE,
                                grpc.StatusCode.DEADLINE_EXCEEDED) and attempt == 0:
                    self.use_tls = not self.use_tls
                    self.close()
                    grpc_logger.info(
                        f"Echo 连接失败({e.code().name})，自动切换 use_tls={self.use_tls} 重试")
                    continue
                raise

        return {
            "message": response.message,
            "files": list(response.files),
            "override": self._parse_override(response.override),
            "shared_secret_missing": response.sharedSecretMissing,
            "server_identifier": response.serverIdentifier,
        }

    def _parse_override(self, override):
        """解析 MetadataOverride 里的资产清单

        各字段是 FlatBuffers 编码的字符串列表（裸的 UTF-8 文本，不是标准 FlatBuffer）。
        这里做尽力解析：能取出文件名就返回，取不出就返回空列表。

        Args:
            override: pb2.MetadataOverride 消息

        Returns:
            dict: {"models": [], "loras": [], "control_nets": [],
                   "textual_inversions": [], "upscalers": []}
        """
        result = {
            "models": [],
            "loras": [],
            "control_nets": [],
            "textual_inversions": [],
            "upscalers": [],
        }
        if not override:
            return result

        mapping = [
            ("models", "models"),
            ("loras", "loras"),
            ("controlNets", "control_nets"),
            ("textualInversions", "textual_inversions"),
            ("upscalers", "upscalers"),
        ]
        for proto_field, key in mapping:
            raw = getattr(override, proto_field, b"")
            if raw:
                result[key] = _decode_asset_list(raw)
        return result

    def list_models(self, timeout=None):
        """获取服务端全部模型列表

        HTTP 通道没有任何等价能力（实测 sdapi/v1/models 等端点均404），
        所以这是 gRPC 独有能力。

        Args:
            timeout (int): 超时（秒）

        Returns:
            dict: {
                "models": [str], "loras": [str], "control_nets": [str],
                "textual_inversions": [str], "upscalers": [str],
                "all_files": [str],
            }

        Raises:
            grpc.RpcError: 服务不可达
        """
        info = self.echo(timeout=timeout)
        return {
            **info["override"],
            "all_files": info["files"],
        }

    def is_available(self, timeout=5):
        """探测 gRPC 服务是否可用

        Args:
            timeout (int): 探测超时（秒）

        Returns:
            bool: 可用返回 True
        """
        try:
            self.echo(timeout=timeout)
            return True
        except Exception as e:
            # 注意：这里不能退化成"裸 TLS 能握手就算可用"。
            # 裸 TLS 只证明端口在监听，不证明 gRPC 服务能正常应答——
            # 服务端忙/协议不符时两者表现完全不同，误判会导致错误降级。
            grpc_logger.info(f"gRPC 探测失败: {str(e)[:80]}")
            return False

    def is_idle(self, timeout=1.5):
        """检测服务端是否空闲（轻量，不发 RPC）

        判据原理（实测验证）：
        - TCP `create_connection` 永远秒通 —— 内核 accept backlog 有缓冲，
          **不能**用它判断空闲。
        - TLS 握手需要应用主线程参与：空闲时 <100ms 完成，忙时挂起直到超时。

        所以「TLS 握手能否在短超时内完成」才是可靠判据。
        该探测只做握手，不发任何 RPC，不会给正在生成的任务加负担。

        Args:
            timeout (float): TLS 握手超时（秒）

        Returns:
            tuple: (is_idle, status_text)
        """
        try:
            probe = socket.create_connection((self.host, self.port), timeout=1.0)
            probe.close()
        except Exception as e:
            return False, f"TCP 不通 ({type(e).__name__})"

        t0 = time.time()
        raw = socket.create_connection((self.host, self.port), timeout=timeout)

        # 服务端可能启用或关闭 TLS，先按配置试；不匹配再试另一种。
        # （协议层协商不出错，只有在应用层才会暴露，所以两种都要试。）
        if self.use_tls:
            attempts = [True, False]
        else:
            attempts = [False, True]

        last_error = None
        for use_ssl in attempts:
            try:
                if use_ssl:
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    conn = ctx.wrap_socket(raw, server_hostname=self._ssl_target_name)
                    elapsed = time.time() - t0
                    label = f"TLS握手 {elapsed*1000:.0f}ms"
                else:
                    conn = raw
                    label = "明文"
                conn.close()
                raw = None
                return True, f"空闲 ({label})"
            except Exception as e:
                last_error = e
                try:
                    raw.close()
                except Exception:
                    pass
                raw = None
                # 换另一种协议重试
                raw = socket.create_connection((self.host, self.port), timeout=timeout)

        return False, f"忙 ({type(last_error).__name__})"

    def wait_until_idle(self, max_wait=180, interval=4):
        """轮询等待服务端空闲

        Args:
            max_wait (int): 最长等待秒数
            interval (int): 探测间隔秒数

        Returns:
            bool: 空闲返回 True，超时返回 False
        """
        waited = 0
        while waited < max_wait:
            is_idle, status = self.is_idle(timeout=IDLE_HANDSHAKE_SEC)
            if is_idle:
                grpc_logger.info(f"Draw Things 已空闲 ({status})")
                return True
            grpc_logger.info(
                f"Draw Things {status}，等待空闲... ({waited}/{max_wait}s)"
            )
            time.sleep(interval)
            waited += interval
        return False

    def _can_tls_handshake(self, timeout=3):
        """裸 TLS 握手探测（不涉及 gRPC 协议）

        Args:
            timeout (int): 超时（秒）

        Returns:
            bool: 握手成功返回 True
        """
        import socket
        import ssl

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            raw = socket.create_connection((self.host, self.port), timeout=timeout)
            try:
                tls = ctx.wrap_socket(raw, server_hostname=self._ssl_target_name)
                tls.close()
            except Exception:
                raw.close()
            return True
        except Exception:
            return False

    def files_exist(self, files, timeout=None):
        """检查文件是否存在

        Args:
            files (list): 文件名列表
            timeout (int): 超时（秒）

        Returns:
            set: 存在的文件名集合

        Raises:
            GrpcUnavailableError: 服务不可达
        """
        channel = self._get_channel()
        stub = pb2_grpc.ImageGenerationServiceStub(channel)

        request = pb2.FileListRequest(files=list(files))
        if self.shared_secret:
            request.sharedSecret = self.shared_secret

        try:
            response = stub.FilesExist(request, timeout=timeout or self.timeout)
            return set(response.files)
        except grpc.RpcError as e:
            raise GrpcUnavailableError(
                f"FilesExist 失败 ({e.code().name}): {e.details()}"
            ) from e

    def _build_override(self, model=None, loras=None, controls=None):
        """构建 MetadataOverride（模型/LoRA/ControlNet 清单）

        官方实现见 draw-things-comfyui/src/draw_things.py:build_override()。
        每个字段是 **JSON 数组字符串的 UTF-8 字节**。

        Args:
            model (str): 主模型文件名；None 表示沿用服务端当前模型
            loras (list): LoRA 配置列表
            controls (list): ControlNet 配置列表

        Returns:
            pb2.MetadataOverride: 至少含 models 字段
        """
        import json

        models = []
        if model:
            models.append(model)

        override = pb2.MetadataOverride()

        if models:
            override.models = json.dumps(models).encode("utf-8")

        if loras:
            lora_names = [
                item.get("file") for item in loras if item.get("file")
            ]
            if lora_names:
                override.loras = json.dumps(lora_names).encode("utf-8")

        if controls:
            control_names = [
                item.get("file") for item in controls if item.get("file")
            ]
            if control_names:
                override.controlNets = json.dumps(control_names).encode("utf-8")

        return override

    def generate_image(self, prompt, negative_prompt="", width=512, height=512,
                       steps=20, seed=-1, guidance_scale=3.5, sampler=None,
                       model=None, strength=1.0, batch_size=1,
                       original_width=None, original_height=None,
                       loras=None, controls=None, resolution_dependent_shift=None,
                       shift=None,
                       hints=None, mask_blob=None, scale_factor=1,
                       progress_callback=None, timeout=None):
        """生成图片

        Args:
            prompt (str): 正向提示词
            negative_prompt (str): 负向提示词
            width (int): 输出宽
            height (int): 输出高
            steps (int): 步数
            seed (int): 随机种子，-1 为随机
            guidance_scale (float): CFG 强度
            sampler (int): 采样器枚举，None 表示用默认
            model (str): 模型文件名，None 表示沿用服务端当前模型
            strength (float): img2img 强度
            original_width (int): 原图宽（图生图用）
            original_height (int): 原图高（图生图用）
            loras (list): LoRA 配置
            controls (list): ControlNet 配置
            hints (list): [{"hint_type": str, "tensors": [(bytes, float)]}]
            mask_blob (bytes): 遮罩的 DTTensor 数据
            scale_factor (int): 输入图像缩放系数
            progress_callback (callable): 进度回调，签名 (stage, step, total)
            timeout (int): 超时（秒）

        Returns:
            dict: {
                "images": [bytes],      # DTTensor 格式
                "seed": int,            # 实际使用的 seed
                "progress": list,       # 进度记录
            }

        Raises:
            GrpcUnavailableError: 服务不可达
            RuntimeError: 未返回图片数据
        """
        # ---- 参数安全校验：超大参数会拖垮服务端（单任务串行 + 大内存）----
        width = int(width)
        height = int(height)
        steps = int(steps)
        if not (1 <= width <= MAX_WIDTH) or not (1 <= height <= MAX_HEIGHT):
            raise ValueError(
                f"尺寸超限: {width}x{height}，允许范围 1-{MAX_WIDTH}"
            )
        # steps=0 / guidance_scale=0 表示「沿用 Draw Things 模型内置推荐值」，
        # 让服务端自行套用（等价于 UI 的「尝试推荐设置」）。仅拦截明显越界。
        if not (0 <= steps <= MAX_STEPS):
            raise ValueError(f"步数超限: {steps}，允许范围 0-{MAX_STEPS}")

        channel = self._get_channel()
        stub = pb2_grpc.ImageGenerationServiceStub(channel)

        cfg_kwargs = dict(
            width=width,
            height=height,
            steps=steps,
            seed=seed,
            guidance_scale=guidance_scale,
            sampler=sampler if sampler is not None else dt_config.SAMPLER_DPMPP2MKARRAS,
            model=model,
            strength=strength,
            batch_size=batch_size,
            original_width=original_width,
            original_height=original_height,
            loras=loras,
            controls=controls,
        )
        # Flow Matching 模型的噪声调度（qwen 基础版需 resolution_dependent_shift=True，
        # 否则会整片偏色）。None 表示沿用 build 默认。
        if resolution_dependent_shift is not None:
            cfg_kwargs["resolution_dependent_shift"] = bool(resolution_dependent_shift)
        if shift is not None:
            cfg_kwargs["shift"] = float(shift)
        config_blob = dt_config.build_generation_config(**cfg_kwargs)

        request = pb2.ImageGenerationRequest(
            prompt=prompt,
            negativePrompt=negative_prompt,
            configuration=config_blob,
            scaleFactor=scale_factor,
            user="DrawThingsWebUI",
            # device 必须给，否则服务端不知道按哪种设备特性调度
            device=pb2.DeviceType.Value("LAPTOP"),
        )
        if self.shared_secret:
            request.sharedSecret = self.shared_secret

        # ---- override：告诉服务端用哪些模型/LoRA/ControlNet ----
        # 官方 ComfyUI 扩展必传此字段（src/draw_things.py build_override）。
        # 缺了它服务端拿不到模型清单，请求会被挂起直到超时。
        override = self._build_override(model, loras, controls)
        if override is not None:
            request.override.CopyFrom(override)

        # ---- 内容寻址存储（CAS）：图片按 sha256 放入 contents，主字段存 hash ----
        import hashlib

        if hints:
            request.hints.extend(hints)
            for hint in hints:
                for tensor in hint.tensors:
                    digest = hashlib.sha256(tensor.tensor).digest()
                    request.contents.append(tensor.tensor)
                    tensor.tensor = digest

        if mask_blob:
            digest = hashlib.sha256(mask_blob).digest()
            request.contents.append(mask_blob)
            request.mask = digest

        # ---- 消费服务端流 ----
        # 对齐官方参考实现（draw-things-comfyui/src/draw_things.py）：
        # 每个 response.generatedImages 已是完整图像（或整批），直接 extend，
        # 不要做 downloadSize 分块重组——否则多图会拼成一个损坏 blob。
        images = []
        progress_log = []
        actual_seed = -1
        partial = False

        # TLS 自动协商：桥接/远程模式会强制 TLS，服务端设置来回切会导致
        # 固定 use_tls 失配。UNAVAILABLE 且尚无结果时翻转重试一次。
        for attempt in range(2):
            try:
                stub = pb2_grpc.ImageGenerationServiceStub(self._get_channel())
                responses = stub.GenerateImage(
                    request, timeout=timeout or GENERATE_TIMEOUT)
                for response in responses:
                    if response.generatedImages:
                        images.extend(response.generatedImages)

                    # 进度
                    signpost = response.currentSignpost
                    if signpost.HasField("sampling"):
                        step = signpost.sampling.step
                        progress_log.append(("sampling", step))
                        if progress_callback:
                            progress_callback("sampling", step, steps)
                    elif signpost.HasField("textEncoded"):
                        progress_log.append(("text_encoded", 0))
                        if progress_callback:
                            progress_callback("text_encoded", 0, steps)
                    elif signpost.HasField("imageDecoded"):
                        progress_log.append(("image_decoded", 0))
                        if progress_callback:
                            progress_callback("image_decoded", 0, steps)
                break
            except grpc.RpcError as e:
                code = e.code().name
                # UNAVAILABLE/UNIMPLEMENTED 是"连不上"；
                # DEADLINE_EXCEEDED 在**尚未拿到任何结果**时也可能是协议(use_tls)不匹配
                # （服务端对错误协议的请求会挂起到超时），故同样翻转重试一次。
                if code in ('UNAVAILABLE', 'UNIMPLEMENTED', 'DEADLINE_EXCEEDED'):
                    if images:
                        # 流中途断但已有部分结果 → 返回部分（与官方一致）
                        partial = True
                        break
                    if attempt == 0:
                        # 可能是 TLS 失配（桥接模式/明文模式切换导致），翻转重试
                        self.use_tls = not self.use_tls
                        self.close()
                        grpc_logger.info(
                            f"GenerateImage 连接失败({code})，"
                            f"自动切换 use_tls={self.use_tls} 重试")
                        continue
                    raise GrpcUnavailableError(
                        f"GenerateImage 不可达 ({code}): {e.details()}"
                    ) from e
                raise

        if not images:
            raise RuntimeError("gRPC 未返回图片数据")

        return {
            "images": images,
            "seed": actual_seed,
            "progress": progress_log,
            "completed": not partial,
        }


def decode_result_to_png(tensor_blob):
    """把 DTTensor 转成 PNG 字节

    Args:
        tensor_blob (bytes): DTTensor 数据

    Returns:
        bytes: PNG 编码的字节
    """
    import io

    image = dt_tensor.dt_tensor_to_pil(tensor_blob)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def decode_result_to_array(tensor_blob):
    """DTTensor -> numpy RGB 数组

    Args:
        tensor_blob (bytes): DTTensor 数据

    Returns:
        numpy.ndarray: shape (h, w, 3)，dtype uint8
    """
    return dt_tensor.dt_tensor_to_rgb_array(tensor_blob)