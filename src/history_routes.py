"""
历史记录路由模块 - 处理所有与历史记录相关的 API 端点
"""

from flask import request, jsonify
try:
    from src.database import (
        get_user_history,
        get_all_history,
        get_available_dates,
        clear_user_history,
        get_history_count,
        update_rating,
        delete_bad_images,
        get_or_create_user,
        toggle_nsfw
    )
except ModuleNotFoundError:
    from database import (
        get_user_history,
        get_all_history,
        get_available_dates,
        clear_user_history,
        get_history_count,
        update_rating,
        delete_bad_images,
        get_or_create_user,
        toggle_nsfw
    )
import os


def get_user_id():
    """从 Session 或请求头中获取用户 ID

    优先级：
    1. Flask session（登录/游客后由 server 设置，最可靠）
    2. X-User-ID 请求头（向前兼容老前端）
    3. 均未提供则返回 None

    Returns:
        int or None: 用户 ID，如果未提供则返回 None
    """
    from flask import session
    # 优先从 session 获取（登录后设置）
    uid = session.get('user_id')
    if uid:
        try:
            return int(uid)
        except (ValueError, TypeError):
            pass

    # 其次从 X-User-ID 请求头获取（向前兼容）
    user_id_header = request.headers.get("X-User-ID")
    if user_id_header:
        try:
            return int(user_id_header)
        except (ValueError, TypeError):
            pass

    return None


def register_history_routes(app):
    """注册所有历史记录相关的路由
    
    Args:
        app: Flask 应用实例
    """
    
    @app.route('/api/user/create', methods=['POST'])
    def create_user_handler():
        """创建新用户并返回用户ID
        
        每次调用都会创建一个新的用户记录，返回自增的用户ID。
        
        Returns:
            Response: JSON 响应，包含新创建的用户 ID
        """
        try:
            try:
                from src.database import get_or_create_user
            except ModuleNotFoundError:
                from database import get_or_create_user
            user_id = get_or_create_user(is_new=True)
            
            return jsonify({
                "success": True,
                "user_id": user_id,
                "message": "用户创建成功"
            })
        except Exception as e:
            print(f"Error creating user: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route('/api/history', methods=['GET'])
    def history_get_handler():
        """获取生成历史记录
            
        从请求头 X-User-ID 中获取用户 ID，返回该用户的历史记录。
        如果查询参数 all_users=true，则返回所有用户的历史记录（合并）。
        支持 date 参数进行日期筛选，格式为 YYYY-MM-DD。
        支持 rating 参数进行评分筛选，-1为bad，1-5为星级。
        如果 query_dates=true，则返回所有有记录的日期列表。
            
        Returns:
            Response: JSON 响应，包含历史记录列表和用户 ID
        """
        user_id = get_user_id()
            
        # 检查是否请求所有用户的历史
        all_users = request.args.get('all_users', 'false').lower() == 'true'
            
        # 检查是否请求日期列表
        query_dates = request.args.get('query_dates', 'false').lower() == 'true'
            
        if query_dates:
            # 返回所有有记录的日期列表
            try:
                if all_users:
                    dates_list = get_available_dates()
                else:
                    dates_list = get_available_dates(user_id)
                    
                return jsonify({
                    "success": True,
                    "dates": dates_list,
                    "count": len(dates_list)
                })
            except Exception as e:
                print(f"Error getting available dates: {e}")
                return jsonify({
                    "success": True,
                    "dates": [],
                    "count": 0
                })
            
        # 获取日期筛选参数
        filter_date = request.args.get('date', None)
            
        # 获取评分筛选参数（支持多选，用逗号分隔）
        rating_filter = request.args.get('rating', None)
        if rating_filter is not None:
            try:
                # 检查是否包含逗号（多选）
                if ',' in rating_filter:
                    # 多个评级，转换为列表
                    rating_list = [int(r.strip()) for r in rating_filter.split(',')]
                    # 验证所有值都有效
                    rating_filter = [r for r in rating_list if r in [-1, 1, 2, 3, 4, 5]]
                    if not rating_filter:
                        rating_filter = None
                else:
                    # 单个评级
                    rating_filter = int(rating_filter)
                    if rating_filter not in [-1, 1, 2, 3, 4, 5]:
                        rating_filter = None
            except ValueError:
                rating_filter = None
        
        # 获取最低星级筛选参数（min_rating）
        min_rating = request.args.get('min_rating', None)
        if min_rating is not None:
            try:
                min_rating = int(min_rating)
                if min_rating not in [0, 1, 2, 3]:  # 0表示未评分
                    min_rating = None
            except ValueError:
                min_rating = None
        
        # 获取排除Bad参数
        exclude_bad = request.args.get('exclude_bad', 'false').lower() == 'true'
        
        # 获取NSFW显示参数
        show_nsfw = request.args.get('show_nsfw', 'false').lower() == 'true'
            
        try:
            if all_users:
                # 获取所有用户的历史记录
                history = get_all_history(limit=100, date_filter=filter_date, rating_filter=rating_filter, min_rating=min_rating, exclude_bad=exclude_bad, show_nsfw=show_nsfw)
                count = get_history_count(date_filter=filter_date, rating_filter=rating_filter, min_rating=min_rating, exclude_bad=exclude_bad, show_nsfw=show_nsfw)
            else:
                # 只返回当前用户的历史
                if not user_id:
                    # 没有用户ID，返回空列表
                    history = []
                    count = 0
                else:
                    history = get_user_history(user_id, limit=50, date_filter=filter_date, rating_filter=rating_filter, min_rating=min_rating, exclude_bad=exclude_bad, show_nsfw=show_nsfw)
                    count = get_history_count(user_id=user_id, date_filter=filter_date, rating_filter=rating_filter, min_rating=min_rating, exclude_bad=exclude_bad, show_nsfw=show_nsfw)
                        
            return jsonify({
                "success": True,
                "history": history,
                "count": count,
                "user_id": user_id,
                "all_users": all_users,
                "show_nsfw": show_nsfw
            })
        except Exception as e:
            print(f"Error getting history: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/api/history', methods=['DELETE'])
    def history_delete_handler():
        """清空当前用户的生成历史记录
        
        从请求头 X-User-ID 中获取用户 ID，只清空该用户的历史。
        
        Returns:
            Response: JSON 响应，包含操作结果
        """
        user_id = get_user_id()
        
        if not user_id:
            return jsonify({
                "success": False,
                "error": "缺少用户 ID，请先获取用户 ID"
            }), 400
        
        try:
            deleted_count = clear_user_history(user_id)
            return jsonify({
                "success": True,
                "message": f"历史记录已清空，共删除 {deleted_count} 条记录",
                "user_id": user_id,
                "deleted_count": deleted_count
            })
        except Exception as e:
            print(f"Error clearing history: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/api/rating', methods=['POST'])
    def rating_post_handler():
        """为图片评分
        
        接收图片 ID 和评分值，更新数据库中的评分。
        评分值：-1为bad，0为清除评分，1-5为星级
        不校验用户ID，可以对所有用户的图片进行评分
        
        Returns:
            Response: JSON 响应，包含操作结果
        """
        user_id = get_user_id()  # 可选，用于记录谁评的分
        
        try:
            data = request.json
            image_id = data.get('image_id')
            rating = data.get('rating')
            
            if not image_id:
                return jsonify({
                    "success": False,
                    "error": "缺少图片 ID"
                }), 400
            
            if rating is None or rating not in [-1, 0, 1, 2, 3, 4, 5]:
                return jsonify({
                    "success": False,
                    "error": "无效的评分值"
                }), 400
            
            success = update_rating(image_id, rating)
            
            if success:
                return jsonify({
                    "success": True,
                    "message": "评分已更新",
                    "image_id": image_id,
                    "rating": rating,
                    "user_id": user_id
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "未找到该图片"
                }), 404
        except Exception as e:
            print(f"Error rating image: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/api/nsfw', methods=['POST'])
    def nsfw_toggle_handler():
        """切换图片的NSFW标记
        
        接收图片 ID，切换其NSFW状态。
        不校验用户ID，可以对所有用户的图片进行标记
        
        Returns:
            Response: JSON 响应，包含操作结果
        """
        user_id = get_user_id()  # 可选，用于记录谁标记的
        
        try:
            data = request.json
            image_id = data.get('image_id')
            
            if not image_id:
                return jsonify({
                    "success": False,
                    "error": "缺少图片 ID"
                }), 400
            
            success, new_nsfw_value = toggle_nsfw(image_id)
            
            if success:
                return jsonify({
                    "success": True,
                    "message": "NSFW标记已更新",
                    "image_id": image_id,
                    "is_nsfw": new_nsfw_value,
                    "user_id": user_id
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "未找到该图片"
                }), 404
        except Exception as e:
            print(f"Error toggling NSFW: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/api/history/bad', methods=['DELETE'])
    def bad_images_delete_handler():
        """删除所有标记为 Bad 的图片
        
        只有在当前筛选条件为 Bad (rating=-1) 时才能调用此接口。
        如果 all_users=true，则删除所有用户的 Bad 图片；否则只删除当前用户的。
        同时删除数据库记录和原文件。
        
        Returns:
            Response: JSON 响应，包含删除结果
        """
        user_id = get_user_id()
        
        # 如果不是删除所有用户，需要提供用户ID
        all_users = request.args.get('all_users', 'false').lower() == 'true'
        if not all_users and not user_id:
            return jsonify({
                "success": False,
                "error": "缺少用户 ID，请先获取用户 ID"
            }), 400
        
        try:
            # 检查是否选择了 Bad 筛选条件
            rating_filter = request.args.get('rating', None)
            if rating_filter is None or int(rating_filter) != -1:
                return jsonify({
                    "success": False,
                    "error": "必须先选择 Bad 筛选条件才能删除"
                }), 400
            
            # 获取要删除的图片列表
            deleted_count, filenames = delete_bad_images(all_users=all_users, user_id=user_id if not all_users else None)
            
            # 删除原文件
            IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'generated_images')
            deleted_files = 0
            failed_files = 0
            for filename in filenames:
                try:
                    file_path = os.path.join(IMAGES_DIR, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_files += 1
                    else:
                        print(f"Warning: File not found: {file_path}")
                        failed_files += 1
                except Exception as e:
                    print(f"Error deleting file {filename}: {e}")
                    failed_files += 1
            
            return jsonify({
                "success": True,
                "message": f"成功删除 {deleted_count} 张 Bad 图片",
                "deleted_count": deleted_count,
                "files_deleted": deleted_files,
                "files_failed": failed_files,
                "user_id": user_id
            })
        except Exception as e:
            print(f"Error deleting bad images: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
