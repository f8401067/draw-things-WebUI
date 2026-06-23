"""
LLM客户端模块 - 用于调用大模型API进行NSFW检测
"""

import os
import sys
import requests
import json
import threading
import logging
from pathlib import Path
try:
    from src.database import update_nsfw_status
except ModuleNotFoundError:
    from database import update_nsfw_status

# 配置LLM调用日志
llm_logger = logging.getLogger('llm_calls')
llm_logger.setLevel(logging.INFO)


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
    return Path(app_root) / 'config.json'


def load_llm_config(user_id=None):
    """加载LLM配置（优先从数据库读取用户配置，回退到 config.json）
    
    Args:
        user_id (int): 用户 ID，用于从数据库读取该用户的配置
        
    Returns:
        dict: LLM配置信息
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
                return {
                    'api_url': db_config.get('llm_api_url'),
                    'model': db_config.get('llm_model'),
                    'api_key': db_config.get('llm_api_key'),
                }
        except Exception:
            pass  # 数据库不可用时回退
    
    # 回退到 config.json
    try:
        config_path = get_config_file_path()
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return {
                'api_url': config.get('llm_api_url'),
                'model': config.get('llm_model'),
                'api_key': config.get('llm_api_key')
            }
    except Exception as e:
        print(f"加载LLM配置失败: {e}")
        return None


def detect_nsfw_content(prompt, negative_prompt="", image_id=None, user_id=None):
    """使用LLM检测提示词是否包含NSFW内容
    
    Args:
        prompt (str): 正向提示词
        negative_prompt (str): 负向提示词
        image_id (str): 图片ID，用于更新数据库
        user_id (int): 用户 ID，用于读取该用户的 LLM 配置
        
    Returns:
        bool: 如果检测到NSFW内容返回True，否则返回False
    """
    import time
    
    # ========== MOCK模式：始终返回YES用于调试 ==========
    MOCK_NSWF = False  # 设置为True启用MOCK，False禁用
    if MOCK_NSWF:
        print(f"⚠️  [MOCK模式] NSFW检测结果: YES (图片ID: {image_id})")
        if image_id:
            update_nsfw_status(image_id, True)
            print(f"⚠️  [MOCK模式] 已标记图片 {image_id} 为NSFW")
        return True
    # ===================================================
    
    start_time = time.time()
    
    config = load_llm_config(user_id=user_id)
    if not config or not config['api_url']:
        llm_logger.warning("LLM配置不完整，跳过NSFW检测")
        print("LLM配置不完整，跳过NSFW检测")
        return False
    
    # 记录NSFW检测开始
    llm_logger.info(f"开始NSFW检测 - 图片ID: {image_id}, 提示词长度: {len(prompt)}")
    
    # 构建检测消息 - 采用更宽松的判断标准
    system_message = """你是一个内容安全检测助手。请分析用户提供的图像生成提示词，判断是否包含明确的、不适合工作场所(NSFW)的内容。
    
请注意以下几点：
- 只有当内容明显包含色情、暴力、裸露等成人内容时才标记为NSFW
- 艺术性的人体描绘、医学相关内容、教育用途等内容不应被标记为NSFW
- 轻微暗示或隐喻内容通常可以接受
- 对于模糊或不确定的情况，倾向于判定为安全(NO)

请只回答"YES"或"NO"，不要添加其他解释。"""
    
    user_message = f"正向提示词: {prompt}\n负向提示词: {negative_prompt}"
    
    try:
        headers = {
            "Content-Type": "application/json"
        }
        
        # 如果有API密钥，添加到headers
        if config['api_key']:
            headers["Authorization"] = f"Bearer {config['api_key']}"
        
        payload = {
            "model": config['model'],
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.3,  # 适度温度以平衡一致性和灵活性
            "max_tokens": 10,
            "top_p": 0.9,  # 使用核采样增加多样性
            "enable_thinking": False  # 关闭思考模式，加快响应速度
        }
        
        response = requests.post(
            config['api_url'],
            headers=headers,
            json=payload,
            timeout=30
        )
        
        # 记录API响应
        llm_logger.info(f"NSFW检测API响应 - 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            # 提取LLM的回复
            if 'choices' in result and len(result['choices']) > 0:
                answer = result['choices'][0]['message']['content'].strip().upper()
                is_nsfw = answer.startswith("YES")
                
                # 计算并记录耗时
                elapsed_time = time.time() - start_time
                llm_logger.info(f"NSFW检测完成 - 图片ID: {image_id}, 耗时: {elapsed_time:.2f}秒")
                
                # 记录检测结果
                llm_logger.info(f"NSFW检测结果 - 图片ID: {image_id}, 结果: {'NSFW' if is_nsfw else '安全'}, 回答: {answer}")
                
                # 如果检测到NSFW且提供了image_id，则更新数据库
                if is_nsfw and image_id:
                    update_nsfw_status(image_id, True)
                    llm_logger.info(f"已标记图片 {image_id} 为NSFW")
                    print(f"检测到NSFW内容，已标记图片 {image_id}")
                
                return is_nsfw
            else:
                elapsed_time = time.time() - start_time
                llm_logger.error(f"LLM响应格式异常 - 耗时: {elapsed_time:.2f}秒")
                print("LLM响应格式异常")
                return False
        else:
            elapsed_time = time.time() - start_time
            llm_logger.error(f"LLM API请求失败，状态码: {response.status_code} - 耗时: {elapsed_time:.2f}秒")
            print(f"LLM API请求失败，状态码: {response.status_code}")
            return False
            
    except Exception as e:
        elapsed_time = time.time() - start_time
        llm_logger.error(f"LLM NSFW检测出错: {str(e)} - 耗时: {elapsed_time:.2f}秒")
        print(f"LLM NSFW检测出错: {e}")
        return False


def async_detect_nsfw(prompt, negative_prompt="", image_id=None, user_id=None):
    """异步执行NSFW检测，不阻塞主线程
    
    Args:
        prompt (str): 正向提示词
        negative_prompt (str): 负向提示词
        image_id (str): 图片ID
        user_id (int): 用户 ID，用于读取该用户的 LLM 配置
    """
    def detect_task():
        try:
            is_nsfw = detect_nsfw_content(prompt, negative_prompt, image_id)
            if is_nsfw:
                print(f"⚠️  检测到NSFW内容: {prompt[:50]}...")
            else:
                print(f"✅ 内容安全检查通过")
        except Exception as e:
            print(f"异步NSFW检测失败: {e}")
    
    # 启动后台线程执行检测
    thread = threading.Thread(target=detect_task, daemon=True)
    thread.start()
    return thread
