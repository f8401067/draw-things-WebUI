# DrawThings WebUI - 项目长期记忆

## 项目概述
- 项目名称：DrawThings WebUI
- 当前版本：v1.0.3 (2026-04-12)
- 定位：用于远程控制 Mac 上 DrawThings 进行 AI 图片生成的 Web 界面

## 技术栈
- 后端：Python 3.8+ / Flask 3.0.0 / SQLite / Pillow
- 前端：原生 HTML/CSS/JS / Service Worker（无框架）
- 打包：PyInstaller → macOS .app
- 服务端口：9898（默认）

## 项目结构关键点
- `src/app.py`：Flask 主应用，所有 API 路由，并发控制（最大5并发）
- `src/database.py`：SQLite 操作，generation_history + users 两张表
- `src/history_routes.py`：历史记录相关 API（蓝图方式注册）
- `src/ai_refine.py`：调用 LLM 优化提示词
- `src/llm_client.py`：NSFW 内容检测（异步，不阻塞主线程）
- `src/config_manager.py`：读写 config.json
- `launcher.py`：统一启动入口，环境变量 APP_ROOT_DIR 控制路径
- `static/`：前端 HTML 文件（index.html, history.html, sw.js）
- `data/`：运行时数据（generated_images/, thumbnails/, logs/, history.db）

## 外部依赖
- DrawThings 本地服务：http://127.0.0.1:7888（txt2img API）
- LLM API：OpenAI 兼容格式（可选，用于提示词润色 + NSFW 检测）

## 开发规范
- 遵循 PEP 8，4空格缩进，snake_case 变量名
- 提交格式：feat/fix/docs/refactor: 描述
- 启动命令：`./dev_start.sh` 或 `python launcher.py`
- 环境变量 APP_ROOT_DIR 需要设置为项目根目录

## 数据库字段
- generation_history：id, user_id, image_id, image_url, thumbnail_url, prompt, negative_prompt, width, height, steps, seed, elapsed_time, rating(-1=Bad/0=未评分/1-5=星级), is_nsfw, created_at
