"""
DTTensor 编解码器

Draw Things gRPC 协议使用 DTTensor 私有二进制格式交换图片（服务端不接受 PNG/JPEG）。

格式结构
--------
    [68 字节头部] + [float16 像素数据]

头部（68 字节，前 36 字节是 9 个 uint32，小端）：
    [0] reserved = 0
    [1] type     = CCV_TENSOR_CPU_MEMORY (0x1)
    [2] format   = CCV_TENSOR_FORMAT_NHWC (0x02)
    [3] datatype = CCV_16F (0x20000)
    [4] reserved = 0
    [5] N (batch)= 1
    [6] height
    [7] width
    [8] C (channels)
    [9..16] 其余保留字节

⚠️ 这些常量必须与官方一致，否则服务端不认这个张量。

像素数据：
    float16 RGB，取值范围 [-1.0, 1.0]
    解码公式：uint8 = clamp((f16 + 1.0) * 127, 0, 255)
    编码公式：f16   = (uint8 / 127.0) - 1.0

注意：预览图可能是潜空间（latent）而非 RGB，此时 channels 为 4/16/48 等，
调用方需自行判断，参见 LatentModelFamily 的通道数映射。
"""

import struct

import numpy as np

# DTTensor 固定头部大小
DTTENSOR_HEADER_SIZE = 68

# CCV tensor 常量（取自 draw-things-comfyui/src/image_handlers.py:18-33）
CCV_TENSOR_CPU_MEMORY = 0x1
CCV_TENSOR_FORMAT_NHWC = 0x02
CCV_16F = 0x20000

# 头部 [0] 字段 == 此值表示像素数据经 fpzip 压缩
# （官方 draw-things-comfyui/src/image_handlers.py:45 同样是这个魔数）
COMPRESSED_MAGIC = 1012247


def _read_header(data):
    """解析 DTTensor 头部

    Args:
        data (bytes): 完整 DTTensor 数据

    Returns:
        tuple: (width, height, channels, compressed)

    Raises:
        ValueError: 数据长度不足
    """
    if len(data) < DTTENSOR_HEADER_SIZE:
        raise ValueError(
            f"DTTensor 数据过短: {len(data)} 字节，至少需要 {DTTENSOR_HEADER_SIZE}"
        )

    # 头部前 9 个 uint32：[0]=压缩标记，1=type，2=format，3=datatype，
    # 4=保留，5=N，6=height，7=width，8=channels
    values = struct.unpack_from("<9I", data, 0)
    compressed = values[0] == COMPRESSED_MAGIC
    height = values[6]
    width = values[7]
    channels = values[8]
    return width, height, channels, compressed


def _extract_pixels(data, count):
    """取出 float16 像素数据（自动处理 fpzip 压缩）

    Args:
        data (bytes): DTTensor 数据
        count (int): 预期的 float16 元素个数

    Returns:
        numpy.ndarray: float16 数组

    Raises:
        ValueError: 压缩数据无法解码
    """
    values = struct.unpack_from("<9I", data, 0)
    raw = data[DTTENSOR_HEADER_SIZE:]

    if values[0] == COMPRESSED_MAGIC:
        # 服务端用 fpzip 压缩了像素数据
        try:
            import fpzip
        except ImportError as e:
            raise ValueError(
                "收到 fpzip 压缩数据但未安装 fpzip：pip install fpzip"
            ) from e
        try:
            decompressed = fpzip.decompress(raw, order="C")
        except Exception as e:
            raise ValueError(f"fpzip 解压失败: {e}") from e
        buffer = decompressed.astype(np.float16).tobytes()
        return np.frombuffer(buffer, dtype=np.float16, count=count)

    return np.frombuffer(raw, dtype=np.float16, count=count)


def dt_tensor_to_rgb_array(data):
    """DTTensor -> numpy RGB 数组（uint8）

    Args:
        data (bytes): DTTensor 数据

    Returns:
        numpy.ndarray: shape (height, width, 3)，dtype uint8

    Raises:
        ValueError: 数据格式异常
    """
    width, height, channels, _compressed = _read_header(data)

    # float16 -> float32 -> 映射到 uint8（官方用 127.5，这里保持一致）
    arr = _extract_pixels(data, width * height * channels).astype(np.float32)
    arr = np.clip((arr + 1.0) * 127.5, 0, 255).astype(np.uint8)

    arr = arr.reshape(height, width, channels)

    # ⚠️ 通道布局（实测确认）：
    #  - 3 通道 = 标准 RGB，取 [0:3]
    #  - 4 通道 = Draw Things 的 **ARGB（alpha 在前）**，正确 RGB 是**后 3 个通道 [1:4]**！
    #    早期版本对 4 通道也取 [0:3]，会把 alpha 当成 R 通道 → 整片偏色/过曝。
    #    (qwen image 2.1 基础版原生支持透明，返回 4 通道时命中此 bug；turbo 返回 3 通道不受影响。)
    if channels == 3:
        return arr[:, :, 0:3]
    if channels == 4:
        return arr[:, :, 1:4]
    if channels > 4:
        return arr[:, :, 0:3]
    # 单通道（灰度）转三通道
    if channels == 1:
        return np.repeat(arr, 3, axis=2)
    raise ValueError(f"不支持的通道数: {channels}")


def dt_tensor_to_pil(data):
    """DTTensor -> PIL Image

    Args:
        data (bytes): DTTensor 数据

    Returns:
        PIL.Image.Image: RGB 图像
    """
    from PIL import Image

    return Image.fromarray(dt_tensor_to_rgb_array(data), mode="RGB")


def rgb_array_to_dt_tensor(arr):
    """RGB 数组（uint8）-> DTTensor

    Args:
        arr (numpy.ndarray): shape (height, width, 3)，dtype uint8

    Returns:
        bytes: DTTensor 数据

    Raises:
        ValueError: 数组形状或类型不符
    """
    arr = np.asarray(arr)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"期望 (h, w, 3) 形状，实际 {arr.shape}")
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    height, width, _ = arr.shape

    # uint8 -> float16，取值范围 [-1.0, 1.0]
    f16 = (arr.astype(np.float32) / 127.0 - 1.0).astype(np.float16)

    # 头部：<9I = (reserved, type, format, datatype, 0, N, H, W, C)
    # 常量必须与官方一致，否则服务端无法识别张量。
    header = struct.pack(
        "<9I",
        0,                          # reserved
        CCV_TENSOR_CPU_MEMORY,      # type
        CCV_TENSOR_FORMAT_NHWC,     # format
        CCV_16F,                    # datatype (Float16)
        0,                          # reserved
        1,                          # N (batch)
        height,
        width,
        3,                          # C (channels)
    )
    header += b"\x00" * (DTTENSOR_HEADER_SIZE - len(header))

    return header + f16.tobytes()


def pil_to_dt_tensor(image):
    """PIL Image -> DTTensor

    Args:
        image (PIL.Image.Image): 输入图像

    Returns:
        bytes: DTTensor 数据
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    return rgb_array_to_dt_tensor(np.asarray(image))


def is_rgb_tensor(data):
    """判断是否为 RGB 张量（channels == 3）

    Args:
        data (bytes): DTTensor 数据

    Returns:
        bool: channels 为 3 时返回 True
    """
    try:
        _, _, channels, _ = _read_header(data)
        return channels == 3
    except ValueError:
        return False