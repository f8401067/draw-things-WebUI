"""
AI 提示词润色模块
提供调用大模型 API 进行提示词优化的功能
"""

import os
import sys
import json
import requests
import logging
from pathlib import Path

# 默认的大模型 API 配置（可以根据实际情况修改）
DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-3.5-turbo"
API_KEY_ENV_VAR = "LLM_API_KEY"


def get_config_file_path():
    """获取配置文件路径
    
    从环境变量 APP_ROOT_DIR 读取，由启动脚本传入
    """
    app_root = os.environ.get('APP_ROOT_DIR')
    if not app_root:
        raise EnvironmentError(
            "未设置 APP_ROOT_DIR 环境变量。\n"
            "请通过启动脚本启动应用，或手动设置：export APP_ROOT_DIR=/path/to/app/dir"
        )
    return Path(app_root) / "config.json"


# 初始化配置文件路径
CONFIG_FILE = str(get_config_file_path())

# 配置LLM调用日志
llm_logger = logging.getLogger('llm_calls')
llm_logger.setLevel(logging.INFO)


def load_config():
    """加载项目配置（从 config.json）
    
    Returns:
        dict: 包含 drawthings_url, llm_api_url, llm_model, llm_api_key 的配置字典
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    # 返回默认配置
    return {
        "drawthings_url": "http://127.0.0.1:7888",
        "llm_api_url": DEFAULT_API_URL,
        "llm_model": DEFAULT_MODEL,
        "llm_api_key": os.getenv(API_KEY_ENV_VAR, "")
    }


def save_config(config):
    """保存项目配置到 config.json
    
    Args:
        config (dict): 完整的配置字典
        
    Returns:
        bool: 保存成功返回 True
    """
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        print(f"保存配置出错: {e}")
        return False


def refine_prompt_with_llm(prompt, language="zh", user_id=None):
    """使用大模型润色提示词
    
    Args:
        prompt (str): 用户输入的原始提示词
        language (str): 目标语言，'zh' 为中文，'en' 为英文
        user_id (int): 用户 ID，用于从数据库读取该用户的 LLM 配置
        
    Returns:
        str: 润色后的提示词，如果失败则返回原始提示词
    """
    import time
    start_time = time.time()
    
    if not prompt or not prompt.strip():
        return prompt

    # 优先从数据库读取用户配置，否则回退到 config.json
    config = _resolve_llm_config(user_id)
    api_key = config.get("llm_api_key") or os.getenv(API_KEY_ENV_VAR)
    
    if not api_key:
        error_msg = "未配置 LLM API Key。请在 AI 设置中配置 API Key。"
        llm_logger.error(error_msg)
        raise ValueError(error_msg)
    
    # 记录提示词润色开始
    llm_logger.info(f"开始润色提示词 - 原始长度: {len(prompt)}, 语言: {language}")

    # 构建系统提示词
    system_instruction = (
        "You are a professional AI art prompt engineer. "
        "Your task is to refine and enhance the user's prompt for image generation. "
        "Make it more descriptive, vivid, and detailed while keeping the original intent. "
        "Add artistic styles, lighting details, and composition suggestions if appropriate. "
        "IMPORTANT: Output ONLY the refined prompt text. Do NOT include any explanations, summaries, or conversational filler. "
    )
    
    if language == "zh":
        system_instruction += "Respond in Chinese."
    else:
        system_instruction += "Respond in English."

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": config.get("llm_model", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"Refine this prompt: {prompt}"}
        ],
        "temperature": 0.7,
        "max_tokens": 500,
        "enable_thinking": False  # 关闭思考模式，加快响应速度
    }

    try:
        response = requests.post(
            config.get("llm_api_url", DEFAULT_API_URL),
            headers=headers,
            json=payload,
            timeout=30
        )
        
        # 记录API响应
        llm_logger.info(f"提示词润色API响应 - 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            refined_text = result["choices"][0]["message"]["content"].strip()
            
            # 计算并记录耗时
            elapsed_time = time.time() - start_time
            llm_logger.info(f"提示词润色成功 - 原始长度: {len(prompt)}, 润色后长度: {len(refined_text)}, 耗时: {elapsed_time:.2f}秒")
            return refined_text
        else:
            elapsed_time = time.time() - start_time
            error_msg = response.json().get("error", {}).get("message", "Unknown error")
            full_error = f"API 请求失败: {response.status_code} - {error_msg} - 耗时: {elapsed_time:.2f}秒"
            llm_logger.error(full_error)
            raise Exception(full_error)
            
    except requests.exceptions.RequestException as e:
        elapsed_time = time.time() - start_time
        error_msg = f"网络请求错误: {str(e)} - 耗时: {elapsed_time:.2f}秒"
        llm_logger.error(error_msg)
        raise Exception(error_msg)


def _resolve_llm_config(user_id=None):
    """解析 LLM 配置：优先从数据库读取用户配置，否则回退到 config.json。
    
    Args:
        user_id (int): 用户 ID
        
    Returns:
        dict: {llm_api_url, llm_model, llm_api_key}
    """
    # 先尝试从数据库获取用户配置
    if user_id:
        try:
            try:
                from src.database import get_user_llm_config
            except ModuleNotFoundError:
                from database import get_user_llm_config
            db_config = get_user_llm_config(user_id)
            if db_config and (db_config.get("llm_api_url") or db_config.get("llm_api_key")):
                return db_config
        except Exception:
            pass  # 数据库不可用时回退到 config.json
    
    # 回退到 config.json
    config = load_config()
    return {
        "llm_api_url": config.get("llm_api_url", DEFAULT_API_URL),
        "llm_model": config.get("llm_model", DEFAULT_MODEL),
        "llm_api_key": config.get("llm_api_key", ""),
    }


def get_llm_config_for_user(user_id):
    """获取指定用户的 LLM 配置（给 API 用）。
    优先返回数据库中的用户配置，若无则返回 config.json 的默认值。
    
    Returns:
        dict: {llm_api_url, llm_model, has_key}
    """
    if user_id:
        try:
            try:
                from src.database import get_user_llm_config
            except ModuleNotFoundError:
                from database import get_user_llm_config
            db_config = get_user_llm_config(user_id)
            if db_config and (db_config.get("llm_api_url") or db_config.get("llm_api_key")):
                return {
                    "llm_api_url": db_config.get("llm_api_url", ""),
                    "llm_model": db_config.get("llm_model", ""),
                    "has_key": bool(db_config.get("llm_api_key")),
                }
        except Exception:
            pass
    
    # 回退
    config = load_config()
    return {
        "llm_api_url": config.get("llm_api_url", DEFAULT_API_URL),
        "llm_model": config.get("llm_model", DEFAULT_MODEL),
        "has_key": bool(config.get("llm_api_key") or os.getenv(API_KEY_ENV_VAR)),
    }


def save_llm_config_for_user(user_id, llm_api_url="", llm_model="", llm_api_key=""):
    """保存用户的 LLM 配置到数据库。"""
    try:
        try:
            from src.database import save_user_llm_config
        except ModuleNotFoundError:
            from database import save_user_llm_config
        save_user_llm_config(user_id, llm_api_url, llm_model, llm_api_key)
        return True
    except Exception as e:
        print(f"保存用户 LLM 配置失败: {e}")
        return False
