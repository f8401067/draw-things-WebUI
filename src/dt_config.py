"""
FlatBuffers GenerationConfiguration 编码器

Draw Things gRPC 的生成参数不是 protobuf，而是 FlatBuffers 二进制。
本模块基于 flatc 生成的代码（src/fb_gen/，由 proto/config.fbs 生成）做封装。

Schema 定义见 proto/config.fbs

⚠️ 关键约束
----------
- `start_width` / `start_height` 类型是 ushort，序列化时**除以 64** 存储
  （512 -> 8）。这是最容易踩的坑，不转换服务端尺寸全错。
- `seed` 是 uint32，传 -1 表示随机（0xFFFFFFFF）。
- 枚举字段（sampler / seed_mode）传整数常量。
- 若 flatc 生成的代码缺失，用 scripts/gen_proto.sh 重新生成。
"""

try:
    from src.fb_gen.GenerationConfiguration import GenerationConfiguration, GenerationConfigurationT
    from src.fb_gen.LoRA import LoRA, LoRAT
    from src.fb_gen.Control import Control, ControlT
    from src.fb_gen.SamplerType import SamplerType
    from src.fb_gen.SeedMode import SeedMode
except ModuleNotFoundError:
    from fb_gen.GenerationConfiguration import GenerationConfiguration, GenerationConfigurationT
    from fb_gen.LoRA import LoRA, LoRAT
    from fb_gen.Control import Control, ControlT
    from fb_gen.SamplerType import SamplerType
    from fb_gen.SeedMode import SeedMode


# =============================================================================
# 枚举常量（与 proto/config.fbs 严格对应）
# =============================================================================

SAMPLER_DPMPP2MKARRAS = 0
SAMPLER_EULER_A = 1
SAMPLER_DDIM = 2
SAMPLER_PLMS = 3
SAMPLER_DPMPPSDEKARRAS = 4
SAMPLER_UNIPC = 5
SAMPLER_LCM = 6
SAMPLER_EULER_A_SUBSTEP = 7
SAMPLER_DPMPPSDESUBSTEP = 8
SAMPLER_TCD = 9
SAMPLER_EULER_A_TRAILING = 10
SAMPLER_DPMPPSDETRAILING = 11
SAMPLER_DPMPP2M_AYS = 12
SAMPLER_EULER_A_AYS = 13
SAMPLER_DPMPPSDE_AYS = 14
SAMPLER_DPMPP2MTRAILING = 15
SAMPLER_DDIM_TRAILING = 16
SAMPLER_UNIPCTRAILING = 17
SAMPLER_UNIPC_AYS = 18
SAMPLER_TCD_TRAILING = 19

# 展示名 -> 枚举值（前端下拉框）
SAMPLER_NAMES = {
    "DPM++ 2M Karras": SAMPLER_DPMPP2MKARRAS,
    "Euler a": SAMPLER_EULER_A,
    "DDIM": SAMPLER_DDIM,
    "PLMS": SAMPLER_PLMS,
    "DPM++ SDE Karras": SAMPLER_DPMPPSDEKARRAS,
    "UniPC": SAMPLER_UNIPC,
    "LCM": SAMPLER_LCM,
    "Euler a Substep": SAMPLER_EULER_A_SUBSTEP,
    "DPM++ SDE Substep": SAMPLER_DPMPPSDESUBSTEP,
    "TCD": SAMPLER_TCD,
    "Euler a Trailing": SAMPLER_EULER_A_TRAILING,
    "DPM++ SDE Trailing": SAMPLER_DPMPPSDETRAILING,
    "DPM++ 2M AYS": SAMPLER_DPMPP2M_AYS,
    "Euler a AYS": SAMPLER_EULER_A_AYS,
    "DPM++ SDE AYS": SAMPLER_DPMPPSDE_AYS,
    "DPM++ 2M Trailing": SAMPLER_DPMPP2MTRAILING,
    "DDIM Trailing": SAMPLER_DDIM_TRAILING,
    "UniPC Trailing": SAMPLER_UNIPCTRAILING,
    "UniPC AYS": SAMPLER_UNIPC_AYS,
    "TCD Trailing": SAMPLER_TCD_TRAILING,
}

SAMPLER_VALUE_TO_NAME = {v: k for k, v in SAMPLER_NAMES.items()}

SEED_MODE_LEGACY = 0
SEED_MODE_TORCH_CPU = 1
SEED_MODE_SCALE_ALIKE = 2
SEED_MODE_NVIDIA_GPU = 3

# ControlInputType 常用值
CONTROL_INPUT_UNSPECIFIED = 0
CONTROL_INPUT_DEPTH = 2
CONTROL_INPUT_CANNY = 3
CONTROL_INPUT_POSE = 5
CONTROL_INPUT_INPAINT = 11
CONTROL_INPUT_IP2P = 12
CONTROL_INPUT_SHUFFLE = 13

# LoRAMode
LORA_MODE_ALL = 0
LORA_MODE_BASE = 1
LORA_MODE_REFINER = 2


def _align_to_64(pixels, minimum=64):
    """像素尺寸对齐到 64 的倍数

    Args:
        pixels (int): 原始像素
        minimum (int): 最小值

    Returns:
        int: 对齐后的像素
    """
    if not pixels or pixels <= 0:
        return minimum
    return max(minimum, ((int(pixels) + 63) // 64) * 64)


def _to_tiles(pixels):
    """像素 -> FlatBuffers 存储单位（除以 64）

    Args:
        pixels (int): 像素数

    Returns:
        int: tile 数，0 表示不设置
    """
    if not pixels or pixels <= 0:
        return 0
    return max(1, int(pixels) // 64)


def build_generation_config(
    width=512,
    height=512,
    steps=20,
    seed=-1,
    guidance_scale=3.5,
    sampler=SAMPLER_DPMPP2MKARRAS,
    model=None,
    strength=1.0,
    batch_size=1,
    batch_count=1,
    seed_mode=SEED_MODE_SCALE_ALIKE,
    clip_skip=1,
    shift=1.0,
    hires_fix=False,
    hires_fix_width=None,
    hires_fix_height=None,
    hires_fix_strength=0.7,
    upscaler=None,
    refiner_model=None,
    refiner_start=0.7,
    aesthetic_score=6.0,
    negative_aesthetic_score=2.5,
    sharpness=0.0,
    image_guidance_scale=1.5,
    image_prior_steps=5,
    mask_blur=1.5,
    mask_blur_outset=0,
    tiled_decoding=False,
    decoding_tile_width=640,
    decoding_tile_height=640,
    decoding_tile_overlap=128,
    tiled_diffusion=False,
    diffusion_tile_width=1024,
    diffusion_tile_height=1024,
    diffusion_tile_overlap=128,
    tea_cache=False,
    tea_cache_start=5,
    tea_cache_end=-1,
    tea_cache_threshold=0.06,
    tea_cache_max_skip_steps=3,
    separate_clip_l=False,
    clip_l_text=None,
    separate_t5=False,
    t5_text=None,
    t5_text_encoder=True,
    guidance_embed=3.5,
    speed_up_with_guidance_embed=True,
    resolution_dependent_shift=False,
    stage_2_steps=10,
    stage_2_cfg=1.0,
    stage_2_shift=1.0,
    stochastic_sampling_gamma=0.3,
    preserve_original_after_inpaint=True,
    negative_prompt_for_image_prior=True,
    zero_negative_prompt=False,
    clip_weight=1.0,
    cfg_zero_star=False,
    cfg_zero_init_steps=0,
    causal_inference_enabled=False,
    causal_inference=0,
    causal_inference_pad=0,
    crop_top=0,
    crop_left=0,
    original_width=None,
    original_height=None,
    loras=None,
    controls=None,
    face_restoration=None,
    name="",
):
    """构建 FlatBuffers GenerationConfiguration

    Args:
        width (int): 输出图宽（像素，自动对齐 64）
        height (int): 输出图高（像素，自动对齐 64）
        steps (int): 扩散步数
        seed (int): 随机种子，-1 表示随机
        guidance_scale (float): CFG 引导强度
        sampler (int): 采样器枚举值，见 SAMPLER_* 常量
        model (str): 模型文件名，None 表示沿用服务端当前模型
        strength (float): img2img 强度，1.0 为纯文生图
        original_width (int): 原图宽（图生图时用），默认取width
        original_height (int): 原图高（图生图时用），默认取 height
        loras (list): [{"file": str, "weight": float, "mode": int}]
        controls (list): [{"file": str, "weight": float, "input_override": int}]

    Returns:
        bytes: FlatBuffers 二进制数据
    """
    w_aligned = _align_to_64(width)
    h_aligned = _align_to_64(height)
    orig_w = _align_to_64(original_width) if original_width else w_aligned
    orig_h = _align_to_64(original_height) if original_height else h_aligned

    cfg = GenerationConfigurationT()
    cfg.startWidth = _to_tiles(w_aligned)
    cfg.startHeight = _to_tiles(h_aligned)
    cfg.targetImageWidth = w_aligned
    cfg.targetImageHeight = h_aligned
    cfg.originalImageWidth = orig_w
    cfg.originalImageHeight = orig_h

    cfg.seed = int(seed) & 0xFFFFFFFF
    cfg.steps = int(steps)
    cfg.guidanceScale = float(guidance_scale)
    cfg.strength = float(strength)
    cfg.model = model
    cfg.sampler = int(sampler)
    cfg.batchSize = int(batch_size)
    cfg.batchCount = int(batch_count)

    cfg.hiresFix = bool(hires_fix)
    if hires_fix_width:
        cfg.hiresFixStartWidth = _to_tiles(_align_to_64(hires_fix_width))
    if hires_fix_height:
        cfg.hiresFixStartHeight = _to_tiles(_align_to_64(hires_fix_height))
    cfg.hiresFixStrength = float(hires_fix_strength)
    cfg.upscaler = upscaler

    cfg.imageGuidanceScale = float(image_guidance_scale)
    cfg.seedMode = int(seed_mode)
    cfg.clipSkip = int(clip_skip)

    cfg.maskBlur = float(mask_blur)
    cfg.maskBlurOutset = int(mask_blur_outset)
    cfg.faceRestoration = face_restoration

    cfg.clipWeight = float(clip_weight)
    cfg.negativePromptForImagePrior = bool(negative_prompt_for_image_prior)
    cfg.imagePriorSteps = int(image_prior_steps)
    cfg.refinerModel = refiner_model
    cfg.refinerStart = float(refiner_start)

    cfg.cropTop = int(crop_top)
    cfg.cropLeft = int(crop_left)

    cfg.aestheticScore = float(aesthetic_score)
    cfg.negativeAestheticScore = float(negative_aesthetic_score)
    cfg.zeroNegativePrompt = bool(zero_negative_prompt)

    cfg.name = name
    cfg.sharpness = float(sharpness)
    cfg.shift = float(shift)
    cfg.stage2Steps = int(stage_2_steps)
    cfg.stage2Cfg = float(stage_2_cfg)
    cfg.stage2Shift = float(stage_2_shift)

    cfg.tiledDecoding = bool(tiled_decoding)
    cfg.decodingTileWidth = _to_tiles(decoding_tile_width) or 10
    cfg.decodingTileHeight = _to_tiles(decoding_tile_height) or 10
    cfg.decodingTileOverlap = _to_tiles(decoding_tile_overlap) or 2

    cfg.stochasticSamplingGamma = float(stochastic_sampling_gamma)
    cfg.preserveOriginalAfterInpaint = bool(preserve_original_after_inpaint)

    cfg.tiledDiffusion = bool(tiled_diffusion)
    cfg.diffusionTileWidth = _to_tiles(diffusion_tile_width) or 16
    cfg.diffusionTileHeight = _to_tiles(diffusion_tile_height) or 16
    cfg.diffusionTileOverlap = _to_tiles(diffusion_tile_overlap) or 2

    cfg.t5TextEncoder = bool(t5_text_encoder)
    cfg.separateClipL = bool(separate_clip_l)
    cfg.clipLText = clip_l_text
    cfg.separateT5 = bool(separate_t5)
    cfg.t5Text = t5_text

    cfg.speedUpWithGuidanceEmbed = bool(speed_up_with_guidance_embed)
    cfg.guidanceEmbed = float(guidance_embed)
    cfg.resolutionDependentShift = bool(resolution_dependent_shift)

    cfg.teaCacheStart = int(tea_cache_start)
    cfg.teaCacheEnd = int(tea_cache_end)
    cfg.teaCacheThreshold = float(tea_cache_threshold)
    cfg.teaCache = bool(tea_cache)
    cfg.teaCacheMaxSkipSteps = int(tea_cache_max_skip_steps)

    cfg.causalInferenceEnabled = bool(causal_inference_enabled)
    cfg.causalInference = int(causal_inference)
    cfg.causalInferencePad = int(causal_inference_pad)
    cfg.cfgZeroStar = bool(cfg_zero_star)
    cfg.cfgZeroInitSteps = int(cfg_zero_init_steps)

    # ---- LoRA ----
    if loras:
        cfg.loras = []
        for item in loras:
            lora = LoRAT()
            lora.file = item.get("file")
            lora.weight = float(item.get("weight", 0.6))
            lora.mode = int(item.get("mode", LORA_MODE_ALL))
            cfg.loras.append(lora)

    # ---- ControlNet ----
    if controls:
        cfg.controls = []
        for item in controls:
            ctl = ControlT()
            ctl.file = item.get("file")
            ctl.weight = float(item.get("weight", 1.0))
            ctl.guidance_start = float(item.get("guidance_start", 0.0))
            ctl.guidance_end = float(item.get("guidance_end", 1.0))
            ctl.no_prompt = bool(item.get("no_prompt", False))
            ctl.control_mode = int(item.get("control_mode", 0))
            ctl.input_override = int(item.get("input_override", CONTROL_INPUT_UNSPECIFIED))
            cfg.controls.append(ctl)

    # ---- 序列化 ----
    import flatbuffers

    builder = flatbuffers.Builder(4096)
    builder.Finish(cfg.Pack(builder), None)
    return bytes(builder.Output())


def parse_generation_config(data):
    """解析 FlatBuffers 配置（调试用）

    Args:
        data (bytes): FlatBuffers 二进制

    Returns:
        dict: 关键字段的字典视图
    """
    cfg = GenerationConfiguration.GetRootAs(data, 0)
    result = {
        "start_width": cfg.StartWidth() * 64,
        "start_height": cfg.StartHeight() * 64,
        "steps": cfg.Steps(),
        "seed": cfg.Seed(),
        "guidance_scale": cfg.GuidanceScale(),
        "sampler": cfg.Sampler(),
        "sampler_name": SAMPLER_VALUE_TO_NAME.get(cfg.Sampler(), "unknown"),
        "model": cfg.Model().decode("utf-8") if cfg.Model() else None,
        "strength": cfg.Strength(),
        "batch_size": cfg.BatchSize(),
        "shift": cfg.Shift(),
    }
    if cfg.LorasLength() > 0:
        result["loras"] = []
        for i in range(cfg.LorasLength()):
            lora = cfg.Loras(i)
            result["loras"].append({
                "file": lora.File().decode("utf-8") if lora.File() else None,
                "weight": round(lora.Weight(), 4),
                "mode": lora.Mode(),
            })
    return result