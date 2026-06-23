# DrawThings WebUI Code Wiki

> **项目版本**: v1.0.3 (2026-04-12)
> **文档版本**: 1.0.0
> **最后更新**: 2026-05-19

---

## 目录

1. [项目概述](#1-项目概述)
2. [项目架构](#2-项目架构)
3. [核心模块详解](#3-核心模块详解)
4. [API接口参考](#4-api接口参考)
5. [数据库设计](#5-数据库设计)
6. [配置管理](#6-配置管理)
7. [依赖关系](#7-依赖关系)
8. [项目运行](#8-项目运行)
9. [前端架构](#9-前端架构)
10. [扩展指南](#10-扩展指南)

---

## 1. 项目概述

### 1.1 项目简介

DrawThings WebUI 是一个基于 Python Flask 和静态 HTML 的 Web 界面应用，用于远程控制 Mac 上的 DrawThings 进行 AI 图片生成和图片浏览。该应用提供了友好美观的界面，支持移动端操作。

### 1.2 核心功能

| 功能模块 | 说明 |
|---------|------|
| 图片生成 | 支持自定义提示词、尺寸、种子值、步数等参数 |
| AI提示词润色 | 调用LLM API智能优化提示词（需配置LLM服务） |
| 服务器状态检查 | 实时显示DrawThings服务状态和当前模型 |
| 本地存储 | 自动保存输入内容，下次访问自动填充 |
| 图片查看器 | 支持放大、缩小、重置和保存图片 |
| 时间统计 | 记录每次生成耗时并计算平均值 |
| 浏览器缓存 | Service Worker智能缓存，第二次访问秒开，支持离线浏览 |
| NSFW检测 | 基于LLM的内容安全检测，自动识别不当内容 |
| 星级评分 | 支持1-5星和Bad标记功能 |
| 智能筛选 | 支持按日期、评分、NSFW状态等多维度筛选 |
| 批量清理 | 一键删除所有标记为Bad的图片 |
| 日志记录 | 自动记录图片生成和LLM调用记录 |

### 1.3 技术栈

- **后端框架**: Flask 3.0.0
- **编程语言**: Python 3.8+
- **前端技术**: 原生 HTML/CSS/JavaScript, Service Worker
- **数据库**: SQLite
- **HTTP客户端**: requests 2.31.0
- **跨域支持**: flask-cors 4.0.0
- **图像处理**: Pillow >= 10.0.0
- **打包工具**: PyInstaller

---

## 2. 项目架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        DrawThings WebUI                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐         ┌──────────────────────────────┐  │
│  │   前端界面层      │         │         API 网关              │  │
│  │  (static/*.html) │◄───────►│        (Flask Routes)        │  │
│  │                  │  HTTP   │                              │  │
│  │  - index.html    │  JSON   │  /api/generate               │  │
│  │  - history.html  │         │  /api/history                │  │
│  │  - sw.js         │         │  /api/status                 │  │
│  └──────────────────┘         │  /api/refine_prompt          │  │
│                                └──────────────────────────────┘  │
│                                         │                         │
│  ┌──────────────────┐                    │                         │
│  │   Service Worker │                    │                         │
│  │   (sw.js)        │◄──────────────────┘                         │
│  │                  │         缓存管理 & 离线支持                   │
│  └──────────────────┘                                             │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                         业务逻辑层                                 │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐  │
│  │  app.py     │ │ ai_refine   │ │ llm_client │ │  database  │  │
│  │             │ │             │ │            │ │            │  │
│  │ 核心路由     │ │ 提示词润色   │ │ NSFW检测   │ │ 数据持久化  │  │
│  │ 任务调度     │ │             │ │            │ │            │  │
│  └─────────────┘ └─────────────┘ └────────────┘ └────────────┘  │
│                                                                  │
│  ┌─────────────┐ ┌─────────────┐                                 │
│  │history_     │ │ config_     │                                  │
│  │routes.py    │ │ manager.py  │                                  │
│  │             │ │             │                                  │
│  │ 历史记录API │ │ 配置管理     │                                  │
│  └─────────────┘ └─────────────┘                                  │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                         数据层                                    │
│  ┌─────────────────────┐      ┌─────────────────────────────┐  │
│  │      SQLite          │      │       文件系统               │  │
│  │                      │      │                             │  │
│  │  - history.db        │      │  - data/generated_images/   │  │
│  │  - generation_history│      │  - data/thumbnails/         │  │
│  │  - users             │      │  - data/logs/               │  │
│  │                      │      │  - config.json              │  │
│  └─────────────────────┘      └─────────────────────────────┘  │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                         外部服务层                                 │
│  ┌──────────────────┐         ┌──────────────────────────────┐    │
│  │  DrawThings App  │◄───────►│       LLM API 服务          │    │
│  │  (Mac本地服务)    │ HTTP   │  (OpenAI/兼容API)           │    │
│  │  :7888           │         │  : 配置提供                  │    │
│  └──────────────────┘         └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
drawThingsWebUI/
├── src/                          # Python 源代码目录
│   ├── __init__.py              # 包初始化文件
│   ├── app.py                   # Flask 主应用入口
│   ├── launcher.py              # 统一启动器
│   ├── config_manager.py       # 配置管理模块
│   ├── database.py              # 数据库操作模块
│   ├── history_routes.py        # 历史记录路由模块
│   ├── ai_refine.py             # AI提示词润色模块
│   └── llm_client.py            # LLM客户端模块
│
├── static/                       # 前端静态文件目录
│   ├── index.html               # 主页HTML
│   ├── history.html             # 历史记录页HTML
│   ├── sw.js                    # Service Worker脚本
│   └── favicon.svg             # 网站图标
│
├── data/                        # 运行时数据目录（自动创建）
│   ├── generated_images/        # 生成的图片存储目录
│   ├── thumbnails/              # 缩略图存储目录
│   ├── logs/                    # 日志文件目录
│   │   ├── image_generation.log # 图片生成日志
│   │   └── llm_calls.log        # LLM调用日志
│   ├── history.db               # SQLite数据库文件
│   └── timing_stats.json        # 耗时统计数据文件
│
├── scripts/                      # 工具脚本目录
│   ├── migrate_add_rating.py    # 添加评分字段迁移脚本
│   ├── migrate_add_nsfw.py      # 添加NSFW字段迁移脚本
│   ├── migrate_add_thumbnails.py # 添加缩略图迁移脚本
│   └── cleanup.py               # 清理脚本
│
├── tests/                        # 测试文件目录
│   ├── test_api.py              # API测试
│   ├── test_database.py         # 数据库测试
│   ├── test_rating.py           # 评分功能测试
│   ├── test_nsfw.py             # NSFW功能测试
│   └── ...
│
├── docs/                         # 文档目录
│   └── *.md                     # 功能文档
│
├── build/                        # 构建资源目录
│   ├── Info.plist              # macOS应用配置
│   ├── app_icon.icns           # 应用图标
│   └── launch_wrapper.sh        # 启动包装脚本
│
├── dist/                         # 打包输出目录
│   └── DrawThings WebUI.app/   # macOS应用包
│
├── launcher.py                   # 开发环境启动器入口
├── app.py                        # Flask应用入口（src/app.py的别名）
├── build_standalone.py           # PyInstaller打包脚本
├── create_package.sh            # 分发包创建脚本
├── config.example.json          # 配置示例文件
├── requirements.txt              # Python依赖列表
├── DEVELOPER.md                 # 开发者指南
├── README.md                    # 用户使用说明
└── LICENSE                      # MIT许可证
```

### 2.3 数据流向图

```
┌────────────────────────────────────────────────────────────────────┐
│                          用户操作流程                                │
└────────────────────────────────────────────────────────────────────┘

  用户输入                      Flask后端                      外部服务
     │                            │                              │
     │  POST /api/generate        │                              │
     ├───────────────────────────►│                              │
     │                            │                              │
     │                            │  1. 验证参数                  │
     │                            │  2. 创建初始记录              │
     │                            │  3. 启动NSFW检测（异步）      │
     │                            │                              │
     │                            ├─────────────────────────────►│
     │                            │      POST txt2img            │
     │                            │◄─────────────────────────────┤
     │                            │                              │
     │                            │  4. 保存原图                  │
     │                            │  5. 生成缩略图                │
     │                            │  6. 更新数据库                │
     │                            │  7. 记录日志                  │
     │                            │                              │
     │  JSON Response             │                              │
     │◄───────────────────────────┤                              │
     │  {                         │                              │
     │    "image_url": "...",     │                              │
     │    "elapsed_time": 12.5,   │                              │
     │    "seed": 12345           │                              │
     │  }                         │                              │
     │                            │                              │
     ▼                            ▼                              ▼
```

---

## 3. 核心模块详解

### 3.1 src/app.py - Flask主应用

**文件路径**: `src/app.py`

**功能描述**: 项目的核心入口模块，负责Flask应用的初始化、路由注册和主要业务逻辑处理。

**主要职责**:
- 初始化Flask应用和CORS配置
- 定义所有API端点
- 管理图片生成流程
- 配置日志系统
- 启动定期清理任务

**关键函数**:

#### 3.1.1 路径管理函数

| 函数名 | 说明 | 返回值 |
|--------|------|--------|
| `get_app_root_dir()` | 获取应用根目录（从环境变量APP_ROOT_DIR） | `Path` |
| `get_data_dir()` | 获取数据目录路径 | `Path` |
| `get_config_file_path()` | 获取配置文件路径 | `Path` |

#### 3.1.2 配置函数

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `load_config()` | 加载DrawThings服务配置 | 无 | `str` - DrawThings服务URL |
| `save_config()` | 保存DrawThings服务配置 | `drawthings_url: str` | `bool` |
| `load_thumbnail_config()` | 加载缩略图配置 | 无 | `dict` |

#### 3.1.3 工具函数

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `generate_thumbnail()` | 生成图片缩略图 | `image_path`, `thumbnail_path`, `size` | `bool` |
| `load_timing_stats()` | 加载耗时统计数据 | 无 | `dict` |
| `save_timing_stats()` | 保存耗时统计数据 | `stats: dict` | 无 |
| `calculate_average_time()` | 计算平均耗时 | `times: list` | `float` |
| `estimate_generation_time()` | 预估图片生成时间 | `width`, `height`, `steps`, `user_id` | `dict` |
| `get_user_id()` | 从请求头获取用户ID | 无 | `int` |

#### 3.1.4 API路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 提供主页HTML |
| `/favicon.ico` | GET | 提供网站图标 |
| `/sw.js` | GET | 提供Service Worker |
| `/api/status` | GET | 检查DrawThings服务器状态 |
| `/api/estimate_time` | POST | 预估生成时间 |
| `/api/generate` | POST | 生成图片 |
| `/generated_images/<filename>` | GET | 提供生成的图片 |
| `/thumbnails/<filename>` | GET | 提供缩略图 |
| `/api/config` | GET/POST | 获取/更新DrawThings配置 |
| `/api/status/generating` | GET | 获取当前生成任务数量 |
| `/api/refine_prompt` | POST | AI润色提示词 |
| `/api/refine_config` | GET/POST | 获取/更新AI润色配置 |
| `/api/app_config` | GET/POST | 获取/更新应用配置 |

#### 3.1.5 全局变量

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `app` | `Flask` | Flask应用实例 |
| `generating_count` | `int` | 当前正在生成的请求数量 |
| `count_lock` | `threading.Lock` | 并发计数器锁 |
| `IMAGES_DIR` | `str` | 生成的图片目录路径 |
| `THUMBNAILS_DIR` | `str` | 缩略图目录路径 |
| `LOG_DIR` | `str` | 日志目录路径 |
| `CONFIG_FILE` | `str` | 配置文件路径 |
| `image_logger` | `logging.Logger` | 图片生成日志记录器 |
| `llm_logger` | `logging.Logger` | LLM调用日志记录器 |

#### 3.1.6 代码片段示例

```python
# Flask应用初始化
app = Flask(__name__, static_folder=_static_folder, static_url_path='')
CORS(app)

# 并发控制
generating_count = 0
count_lock = threading.Lock()

# 启动定期清理任务
def start_cleanup_scheduler(interval_hours=24):
    """启动定期清理不完整记录的后台任务"""
    def cleanup_task():
        while True:
            time.sleep(interval_hours * 3600)
            cleanup_incomplete_records(IMAGES_DIR)
    thread = threading.Thread(target=cleanup_task, daemon=True)
    thread.start()
```

---

### 3.2 src/database.py - 数据库管理模块

**文件路径**: `src/database.py`

**功能描述**: 负责SQLite数据库的初始化、CRUD操作和数据库迁移。

**数据库表结构**:

#### generation_history 表
| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | INTEGER | 主键，自增 |
| `user_id` | INTEGER | 用户ID，外键关联users表 |
| `image_id` | TEXT | 图片ID（时间戳格式） |
| `image_url` | TEXT | 图片URL路径 |
| `image_filename` | TEXT | 图片文件名 |
| `thumbnail_url` | TEXT | 缩略图URL路径 |
| `thumbnail_filename` | TEXT | 缩略图文件名 |
| `prompt` | TEXT | 正向提示词 |
| `negative_prompt` | TEXT | 负向提示词 |
| `width` | INTEGER | 图片宽度，默认512 |
| `height` | INTEGER | 图片高度，默认512 |
| `steps` | INTEGER | 生成步数，默认8 |
| `seed` | INTEGER | 随机种子，默认-1 |
| `elapsed_time` | REAL | 生成耗时（秒） |
| `rating` | INTEGER | 评分（-1=Bad，0=未评分，1-5=星级） |
| `is_nsfw` | INTEGER | NSFW标记（0=安全，1=NSFW） |
| `created_at` | TIMESTAMP | 创建时间 |

#### users 表
| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | INTEGER | 主键，自增 |
| `first_seen` | TIMESTAMP | 首次访问时间 |
| `last_seen` | TIMESTAMP | 最后访问时间 |

**关键函数**:

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `get_db_connection()` | 获取数据库连接上下文管理器 | 无 | `sqlite3.Connection` |
| `init_database()` | 初始化数据库和表结构 | 无 | 无 |
| `get_or_create_user()` | 获取或创建用户记录 | `is_new: bool` | `int` - 用户ID |
| `add_history_record()` | 添加生成历史记录 | `record: dict` | `int` - 新记录ID |
| `get_user_history()` | 获取指定用户的历史记录 | 多参数 | `list` |
| `get_all_history()` | 获取所有用户的历史记录 | 多参数 | `list` |
| `get_available_dates()` | 获取有记录的日期列表 | `user_id` | `list` |
| `get_history_count()` | 获取历史记录数量 | 多参数 | `int` |
| `update_rating()` | 更新图片评分 | `image_id`, `rating` | `bool` |
| `update_history_record()` | 更新历史记录的指定字段 | `image_id`, `updates` | `bool` |
| `delete_history_record()` | 删除历史记录 | `image_id` | `bool` |
| `toggle_nsfw()` | 切换图片的NSFW标记 | `image_id` | `tuple` |
| `update_nsfw_status()` | 直接设置图片的NSFW状态 | `image_id`, `is_nsfw` | `bool` |
| `get_bad_images()` | 获取所有标记为Bad的图片 | `all_users`, `user_id` | `list` |
| `delete_bad_images()` | 删除所有标记为Bad的图片 | `all_users`, `user_id` | `tuple` |
| `cleanup_incomplete_records()` | 清理不完整记录 | `images_dir` | `dict` |

**索引结构**:
```sql
CREATE INDEX idx_history_user_id ON generation_history(user_id);
CREATE INDEX idx_history_created_at ON generation_history(created_at);
CREATE INDEX idx_history_user_id_created ON generation_history(user_id, created_at DESC);
CREATE INDEX idx_history_rating ON generation_history(rating);
CREATE INDEX idx_history_nsfw ON generation_history(is_nsfw);
```

---

### 3.3 src/history_routes.py - 历史记录路由模块

**文件路径**: `src/history_routes.py`

**功能描述**: 处理所有与历史记录相关的API端点，包括用户管理、历史查询、评分、NSFW标记等。

**注册的路由**:

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/user/create` | POST | 创建新用户并返回用户ID |
| `/api/history` | GET | 获取生成历史记录 |
| `/api/history` | DELETE | 清空当前用户的生成历史记录 |
| `/api/rating` | POST | 为图片评分 |
| `/api/nsfw` | POST | 切换图片的NSFW标记 |
| `/api/history/bad` | DELETE | 删除所有标记为Bad的图片 |

**关键函数**:

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `get_user_id()` | 从请求头获取用户ID | 无 | `int` or `None` |
| `register_history_routes()` | 注册所有历史记录相关路由 | `app` | 无 |

---

### 3.4 src/ai_refine.py - AI提示词润色模块

**文件路径**: `src/ai_refine.py`

**功能描述**: 提供调用大模型API进行提示词优化的功能。

**配置项**:
- `llm_api_url`: LLM API地址（默认: `https://api.openai.com/v1/chat/completions`）
- `llm_model`: 模型名称（默认: `gpt-3.5-turbo`）
- `llm_api_key`: API密钥（可通过环境变量 `LLM_API_KEY` 设置）

**关键函数**:

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `load_config()` | 加载项目配置 | 无 | `dict` |
| `save_config()` | 保存项目配置 | `config: dict` | `bool` |
| `refine_prompt_with_llm()` | 使用大模型润色提示词 | `prompt`, `language` | `str` |

**使用示例**:
```python
from ai_refine import refine_prompt_with_llm

# 润色中文提示词
refined = refine_prompt_with_llm("一只可爱的猫", language="zh")
print(refined)  # 输出润色后的英文提示词
```

---

### 3.5 src/llm_client.py - LLM客户端模块

**文件路径**: `src/llm_client.py`

**功能描述**: 提供调用大模型API进行NSFW检测的功能，支持同步和异步调用。

**关键函数**:

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `load_llm_config()` | 加载LLM配置 | 无 | `dict` or `None` |
| `detect_nsfw_content()` | 同步检测NSFW内容 | `prompt`, `negative_prompt`, `image_id` | `bool` |
| `async_detect_nsfw()` | 异步检测NSFW内容（不阻塞主线程） | `prompt`, `negative_prompt`, `image_id` | `threading.Thread` |

**使用示例**:
```python
from llm_client import async_detect_nsfw

# 异步启动NSFW检测，不阻塞当前请求
thread = async_detect_nsfw(prompt, negative_prompt, image_id)
```

---

### 3.6 src/config_manager.py - 配置管理模块

**文件路径**: `src/config_manager.py`

**功能描述**: 管理应用的运行时配置（端口、主机等）。

**关键函数**:

| 函数名 | 说明 | 参数 | 返回值 |
|--------|------|------|--------|
| `get_config_file_path()` | 获取配置文件路径 | 无 | `Path` |
| `load_app_config()` | 加载应用配置 | 无 | `dict` |
| `save_app_config()` | 保存应用配置 | `config: dict` | `bool` |
| `update_port()` | 更新端口配置 | `port: int` | `bool` |
| `update_host()` | 更新主机地址配置 | `host: str` | `bool` |
| `update_auto_open_browser()` | 更新自动打开浏览器配置 | `auto_open: bool` | `bool` |

---

### 3.7 launcher.py - 统一启动器

**文件路径**: `launcher.py`

**功能描述**: 统一的应用启动入口，支持开发和打包环境。

**主要功能**:
- 设置工作目录
- 创建数据目录结构
- 加载应用配置
- 自动打开浏览器（macOS）
- 启动Flask服务器

**启动参数**:
- `--port`: 服务器端口（默认: 9898）
- `--host`: 监听地址（默认: 0.0.0.0）
- `--debug`: 启用调试模式

---

## 4. API接口参考

### 4.1 图片生成相关

#### POST /api/generate
生成AI图片

**请求体**:
```json
{
  "prompt": "string",           // 正向提示词（必需）
  "negative_prompt": "string",  // 负向提示词
  "width": 512,                 // 图片宽度（默认: 512）
  "height": 512,                // 图片高度（默认: 512）
  "steps": 8,                   // 生成步数（默认: 8）
  "seed": -1                    // 随机种子（-1表示随机）
}
```

**响应**:
```json
{
  "success": true,
  "image_url": "/generated_images/generated_20240519_123456.png",
  "image_filename": "generated_20240519_123456.png",
  "elapsed_time": 12.5,
  "average_time": 15.3,
  "seed": 12345,
  "estimated_time": 13.2
}
```

#### POST /api/estimate_time
预估生成时间

**请求体**:
```json
{
  "width": 512,
  "height": 512,
  "steps": 8
}
```

**响应**:
```json
{
  "success": true,
  "estimated_time": 13.2,
  "base_time": 30.0,
  "pixel_ratio": 1.0,
  "step_ratio": 1.0
}
```

#### GET /api/status
检查DrawThings服务器状态

**响应**:
```json
{
  "success": true,
  "prompt": "当前提示词",
  "model": "当前模型名称",
  "raw_data": {}
}
```

---

### 4.2 历史记录相关

#### GET /api/history
获取生成历史记录

**查询参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `all_users` | boolean | 是否获取所有用户的历史（默认: false） |
| `date` | string | 日期筛选，格式 YYYY-MM-DD |
| `rating` | string | 评分筛选，支持多选（逗号分隔），-1=Bad，1-5=星级 |
| `min_rating` | int | 最低星级筛选（0=未评分，1-3） |
| `exclude_bad` | boolean | 是否排除Bad图片（默认: false） |
| `show_nsfw` | boolean | 是否显示NSFW内容（默认: false） |
| `query_dates` | boolean | 是否返回有记录的日期列表（默认: false） |

**响应**:
```json
{
  "success": true,
  "history": [
    {
      "id": 1,
      "user_id": 1,
      "image_id": "20240519_123456",
      "image_url": "/generated_images/generated_20240519_123456.png",
      "prompt": "...",
      "rating": 5,
      "is_nsfw": 0,
      "created_at": "2024-05-19T12:34:56"
    }
  ],
  "count": 50,
  "user_id": 1,
  "all_users": false
}
```

#### DELETE /api/history
清空当前用户的生成历史记录

**响应**:
```json
{
  "success": true,
  "message": "历史记录已清空，共删除 10 条记录",
  "user_id": 1,
  "deleted_count": 10
}
```

#### DELETE /api/history/bad
删除所有标记为Bad的图片

**前置条件**: 必须先选择 Bad 筛选条件（`rating=-1`）

**响应**:
```json
{
  "success": true,
  "message": "成功删除 5 张 Bad 图片",
  "deleted_count": 5,
  "files_deleted": 5,
  "files_failed": 0
}
```

---

### 4.3 评分相关

#### POST /api/rating
为图片评分

**请求体**:
```json
{
  "image_id": "20240519_123456",
  "rating": 5
}
```

**评分说明**:
| 值 | 说明 |
|----|------|
| -1 | Bad（不喜欢） |
| 0 | 清除评分 |
| 1-5 | 星级评分 |

**响应**:
```json
{
  "success": true,
  "message": "评分已更新",
  "image_id": "20240519_123456",
  "rating": 5,
  "user_id": 1
}
```

---

### 4.4 NSFW相关

#### POST /api/nsfw
切换图片的NSFW标记

**请求体**:
```json
{
  "image_id": "20240519_123456"
}
```

**响应**:
```json
{
  "success": true,
  "message": "NSFW标记已更新",
  "image_id": "20240519_123456",
  "is_nsfw": 1,
  "user_id": 1
}
```

---

### 4.5 AI润色相关

#### POST /api/refine_prompt
AI润色提示词

**请求体**:
```json
{
  "prompt": "一只可爱的猫",
  "language": "zh"
}
```

**响应**:
```json
{
  "success": true,
  "refined_prompt": "A cute cat sitting on a windowsill, soft natural lighting..."
}
```

#### GET /api/refine_config
获取AI润色配置

**响应**:
```json
{
  "success": true,
  "config": {
    "llm_api_url": "https://api.openai.com/v1/chat/completions",
    "llm_model": "gpt-3.5-turbo",
    "has_key": true
  }
}
```

#### POST /api/refine_config
更新AI润色配置

**请求体**:
```json
{
  "llm_api_url": "https://api.openai.com/v1/chat/completions",
  "llm_model": "gpt-3.5-turbo",
  "llm_api_key": "sk-..."
}
```

---

### 4.6 应用配置相关

#### GET /api/app_config
获取应用配置

**响应**:
```json
{
  "success": true,
  "config": {
    "port": 9898,
    "host": "0.0.0.0",
    "auto_open_browser": true
  }
}
```

#### POST /api/app_config
更新应用配置

**请求体**:
```json
{
  "port": 9898,
  "host": "0.0.0.0",
  "auto_open_browser": true
}
```

#### GET /api/config
获取DrawThings服务配置

**响应**:
```json
{
  "success": true,
  "drawthings_url": "http://127.0.0.1:7888"
}
```

#### POST /api/config
更新DrawThings服务配置

**请求体**:
```json
{
  "drawthings_url": "http://127.0.0.1:7888"
}
```

---

### 4.7 用户相关

#### POST /api/user/create
创建新用户

**响应**:
```json
{
  "success": true,
  "user_id": 1,
  "message": "用户创建成功"
}
```

---

### 4.8 生成状态相关

#### GET /api/status/generating
获取当前正在生成的请求数量

**响应**:
```json
{
  "success": true,
  "generating_count": 2,
  "estimated_wait_time": 30.5
}
```

---

## 5. 数据库设计

### 5.1 数据库文件位置

- 开发环境: `{项目根目录}/data/history.db`
- 打包环境: `{应用目录}/data/history.db`

### 5.2 ER图

```
┌─────────────────┐       ┌─────────────────────────────┐
│     users       │       │    generation_history        │
├─────────────────┤       ├─────────────────────────────┤
│ id (PK)         │◄──────┤ user_id (FK)                 │
│ first_seen      │       │ id (PK)                      │
│ last_seen       │       │ image_id                     │
└─────────────────┘       │ image_url                    │
                          │ image_filename               │
                          │ thumbnail_url                │
                          │ thumbnail_filename           │
                          │ prompt                       │
                          │ negative_prompt              │
                          │ width                        │
                          │ height                       │
                          │ steps                        │
                          │ seed                         │
                          │ elapsed_time                 │
                          │ rating                       │
                          │ is_nsfw                      │
                          │ created_at                   │
                          └─────────────────────────────┘
```

### 5.3 数据迁移

项目支持数据库字段的自动迁移和手动迁移脚本：

| 脚本 | 功能 |
|------|------|
| `scripts/migrate_add_rating.py` | 添加评分字段 |
| `scripts/migrate_add_nsfw.py` | 添加NSFW字段 |
| `scripts/migrate_add_thumbnails.py` | 添加缩略图并生成缩略图 |

---

## 6. 配置管理

### 6.1 配置文件位置

| 环境 | 配置文件位置 |
|------|-------------|
| 开发环境 | `{项目根目录}/config.json` |
| 打包环境 | `{应用目录}/config.json` |

### 6.2 配置项详解

```json
{
  "port": 9898,
  "host": "0.0.0.0",
  "debug": false,
  "auto_open_browser": true,
  "drawthings_url": "http://127.0.0.1:7888",
  "llm_api_url": "",
  "llm_model": "",
  "llm_api_key": "",
  "thumbnail": {
    "max_size": [300, 300],
    "quality": 85,
    "format": "JPEG"
  }
}
```

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `port` | int | 服务器端口号 | 9898 |
| `host` | string | 监听地址（0.0.0.0=允许外部访问） | 0.0.0.0 |
| `debug` | bool | 调试模式 | false |
| `auto_open_browser` | bool | 启动时自动打开浏览器 | true |
| `drawthings_url` | string | DrawThings服务地址 | http://127.0.0.1:7888 |
| `llm_api_url` | string | LLM API地址 | - |
| `llm_model` | string | LLM模型名称 | - |
| `llm_api_key` | string | LLM API密钥 | - |
| `thumbnail.max_size` | array | 缩略图最大尺寸 [宽, 高] | [300, 300] |
| `thumbnail.quality` | int | 缩略图压缩质量 (1-100) | 85 |
| `thumbnail.format` | string | 缩略图格式 (JPEG/PNG/WEBP) | JPEG |

### 6.3 环境变量

| 变量名 | 说明 |
|--------|------|
| `APP_ROOT_DIR` | 应用根目录（打包后由启动脚本设置） |
| `LLM_API_KEY` | LLM API密钥（可替代配置文件中的配置） |

---

## 7. 依赖关系

### 7.1 Python依赖

```
flask==3.0.0
requests==2.31.0
flask-cors==4.0.0
Pillow>=10.0.0
```

### 7.2 系统依赖

- Python 3.8+
- DrawThings 应用（Mac端）
- HTTP Server功能需在DrawThings中启用

### 7.3 依赖关系图

```
┌─────────────────────────────────────────────────────────────┐
│                        requirements.txt                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  flask==3.0.0                                                │
│     ├── werkzeug                                             │
│     ├── jinja2                                               │
│     └── markupsafe                                          │
│                                                              │
│  requests==2.31.0                                            │
│     ├── urllib3                                             │
│     ├── certifi                                             │
│     └── charset-normalizer                                  │
│                                                              │
│  flask-cors==4.0.0                                          │
│     └── flask                                               │
│                                                              │
│  Pillow>=10.0.0                                              │
│     └── (系统级图像处理库)                                    │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                      系统级依赖                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Python 3.8+                                                 │
│     ├── sqlite3                                              │
│     ├── threading                                            │
│     ├── logging                                              │
│     └── json                                                 │
│                                                              │
│  macOS (可选，用于自动打开浏览器)                             │
│     └── subprocess                                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. 项目运行

### 8.1 开发环境运行

#### 方式一：使用开发者脚本（推荐）

```bash
# 克隆项目
cd drawThingsWebUI

# 激活虚拟环境
source venv/bin/activate

# 使用开发者脚本启动
./dev_start.sh
```

#### 方式二：手动启动

```bash
# 激活虚拟环境
source venv/bin/activate

# 设置环境变量
export APP_ROOT_DIR=$(pwd)

# 启动应用
python launcher.py
```

#### 方式三：直接运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行Flask应用
python src/app.py --port 9898 --host 0.0.0.0
```

### 8.2 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--port` | 服务器端口 | 9898 |
| `--host` | 监听地址 | 0.0.0.0 |
| `--debug` | 启用调试模式 | false |

### 8.3 访问应用

启动后，浏览器自动打开，或手动访问：
- 主页: http://localhost:9898
- 历史记录: http://localhost:9898/history.html

### 8.4 打包macOS应用

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行打包脚本
python build_standalone.py

# 创建分发包
./create_package.sh
```

---

## 9. 前端架构

### 9.1 前端文件结构

```
static/
├── index.html     # 主页
├── history.html   # 历史记录页
├── sw.js          # Service Worker
└── favicon.svg    # 图标
```

### 9.2 页面说明

#### index.html - 主页
- 图片生成表单
- DrawThings状态显示
- AI提示词润色功能
- 图片预览区域
- 生成时间统计

#### history.html - 历史记录页
- 图片网格展示
- 评分功能（1-5星 + Bad标记）
- NSFW筛选和标记
- 日期筛选
- 批量删除功能
- 浏览器缓存管理

#### sw.js - Service Worker
- 图片缓存策略
- 离线访问支持
- 后台更新机制

### 9.3 前端与后端交互

```javascript
// 示例：调用生成API
async function generateImage(params) {
  const response = await fetch('/api/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': userId  // 用户ID
    },
    body: JSON.stringify(params)
  });
  return await response.json();
}
```

---

## 10. 扩展指南

### 10.1 添加新的API端点

在 `src/app.py` 或 `src/history_routes.py` 中添加新的路由：

```python
@app.route('/api/new_feature', methods=['POST'])
def new_feature():
    """新功能说明"""
    try:
        data = request.json
        # 处理逻辑
        return jsonify({
            "success": True,
            "result": result
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
```

### 10.2 添加新的数据库字段

1. 修改 `src/database.py` 中的 `init_database()` 函数
2. 或创建迁移脚本 `scripts/migrate_add_xxx.py`

```python
def migrate_add_xxx():
    """迁移脚本示例"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('ALTER TABLE generation_history ADD COLUMN new_field TEXT')
        print("新字段添加成功")
```

### 10.3 添加新的前端页面

1. 在 `static/` 目录创建新的HTML文件
2. 在 `src/app.py` 中添加路由

```python
@app.route('/new_page')
def new_page():
    return send_from_directory(app.static_folder, 'new_page.html')
```

### 10.4 配置Service Worker缓存

在 `static/sw.js` 中配置缓存策略：

```javascript
// 缓存图片资源
const imageCache = caches.open('images-v1');
imageCache.then(cache => {
  cache.addAll([
    '/generated_images/',
    '/thumbnails/'
  ]);
});
```

---

## 附录

### A. 日志文件说明

| 文件 | 说明 |
|------|------|
| `data/logs/image_generation.log` | 图片生成日志 |
| `data/logs/llm_calls.log` | LLM调用日志 |

### B. 错误代码

| 错误代码 | 说明 |
|---------|------|
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 429 | 请求过于频繁（超过5个并发） |
| 500 | 服务器内部错误 |

### C. 并发限制

- 最大并发生成任务数: 5
- 单个任务超时时间: 10分钟
- LLM API超时时间: 30秒

### D. 安全建议

1. 不要将敏感配置（如API Key）提交到版本控制
2. 生产环境建议设置 `debug: false`
3. 外部访问时注意网络安全性
4. 定期备份数据库文件

---

**文档结束**

*本文档由代码分析自动生成，如有问题请联系开发者。*
