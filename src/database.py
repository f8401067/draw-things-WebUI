"""
数据库管理模块 - 使用 SQLite 存储生成历史
"""

import sqlite3
import os
import sys
from datetime import datetime
from contextlib import contextmanager

# 数据库文件路径
def get_db_file_path():
    """获取数据库文件路径
    
    优先使用 APP_ROOT_DIR 环境变量（打包后的应用），
    否则使用相对路径（开发环境）。
    """
    from pathlib import Path
    
    # 尝试从环境变量获取应用根目录（打包后的应用）
    app_root = os.environ.get('APP_ROOT_DIR')
    if app_root:
        data_dir = Path(app_root) / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / 'history.db')
    
    # 检查是否在 PyInstaller 打包环境中
    if getattr(sys, 'frozen', False):
        # 打包后的应用：使用可执行文件所在目录
        application_path = Path(sys.executable).parent
        # macOS .app 包中，可执行文件在 Contents/MacOS/
        # 需要回到应用根目录
        if application_path.name == 'MacOS':
            app_root_dir = application_path.parent.parent
        else:
            app_root_dir = application_path
        data_dir = app_root_dir / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / 'history.db')
    
    # 开发环境：使用相对路径
    try:
        db_path = Path(__file__).resolve().parent.parent / 'data' / 'history.db'
    except:
        db_path = Path(__file__).resolve().parent / '..' / 'data' / 'history.db'
    
    # 确保目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)

DB_FILE = get_db_file_path()


@contextmanager
def get_db_connection():
    """获取数据库连接的上下文管理器
    
    自动处理连接的打开和关闭，确保资源正确释放。
    
    Yields:
        sqlite3.Connection: 数据库连接对象
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def _upgrade_schema(cursor):
    """在已存在的数据库上补充用户系统相关字段/表。

    安全可重入：检查列是否存在再添加。
    """
    # 1. users 表补字段
    cursor.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in cursor.fetchall()}
    if 'username' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if 'password' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN password TEXT")
    if 'is_guest' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN is_guest INTEGER DEFAULT 0")
    if 'created_at_ip' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at_ip TEXT")

    # 2. 老 users 行（没 username 的）全部视为游客
    cursor.execute(
        "UPDATE users SET is_guest = 1 WHERE username IS NULL OR username = ''"
    )

    # 3. username 唯一索引（仅对非 NULL 生效，允许多个 NULL/空）
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username "
        "ON users(username) WHERE username IS NOT NULL"
    )

    # 4. prompt_presets 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompt_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_presets_user_id "
        "ON prompt_presets(user_id)"
    )

    # 5. user_llm_config 表 —— 每个用户独立的 AI 大模型配置
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_llm_config (
            user_id INTEGER PRIMARY KEY,
            llm_api_url TEXT DEFAULT '',
            llm_model TEXT DEFAULT '',
            llm_api_key TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # 6. user_notify_config 表 —— 每个用户独立的通知（ntfy）配置
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_notify_config (
            user_id INTEGER PRIMARY KEY,
            ntfy_topic TEXT DEFAULT '',
            ntfy_server TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')


def init_database():
    """初始化数据库

    创建历史记录表、用户表、提示词预设表。
    已有数据库通过 _upgrade_schema 补齐缺失字段。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 检查是否需要重建表（从旧版本升级）
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='generation_history'")
        table_exists = cursor.fetchone()

        if table_exists:
            # 检查表结构是否包含必要的字段
            cursor.execute("PRAGMA table_info(generation_history)")
            columns = [row[1] for row in cursor.fetchall()]

            needs_rebuild = False

            if 'user_id' not in columns and 'uid' in columns:
                # 旧表结构，需要重建
                print("检测到旧表结构，正在重建...")
                needs_rebuild = True
            elif 'is_nsfw' not in columns:
                # 缺少 is_nsfw 字段，需要添加
                print("检测到缺少 is_nsfw 字段，正在添加...")
                try:
                    cursor.execute('ALTER TABLE generation_history ADD COLUMN is_nsfw INTEGER DEFAULT 0')
                    print("is_nsfw 字段添加成功")
                except Exception as e:
                    print(f"添加 is_nsfw 字段失败: {e}")

            # 检查是否缺少缩略图字段
            if 'thumbnail_url' not in columns:
                print("检测到缺少 thumbnail_url 字段，正在添加...")
                try:
                    cursor.execute('ALTER TABLE generation_history ADD COLUMN thumbnail_url TEXT')
                    cursor.execute('ALTER TABLE generation_history ADD COLUMN thumbnail_filename TEXT')
                    print("缩略图字段添加成功")
                except Exception as e:
                    print(f"添加缩略图字段失败: {e}")

            if needs_rebuild:
                cursor.execute('DROP TABLE IF EXISTS generation_history')
                cursor.execute('DROP TABLE IF EXISTS users')
                table_exists = None

        if not table_exists:
            # 创建历史记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS generation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    image_id TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    image_filename TEXT NOT NULL,
                    thumbnail_url TEXT,
                    thumbnail_filename TEXT,
                    prompt TEXT,
                    negative_prompt TEXT,
                    width INTEGER DEFAULT 512,
                    height INTEGER DEFAULT 512,
                    steps INTEGER DEFAULT 8,
                    seed INTEGER DEFAULT -1,
                    elapsed_time REAL,
                    rating INTEGER DEFAULT 0,
                    is_nsfw INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')

            # 创建用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    password TEXT,
                    is_guest INTEGER DEFAULT 0,
                    created_at_ip TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            print("数据库表创建完成")

        # 增量升级（users 新字段 / prompt_presets 表）
        _upgrade_schema(cursor)

        # 创建索引以优化查询
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_history_user_id
            ON generation_history(user_id)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_history_created_at
            ON generation_history(created_at)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_history_user_id_created
            ON generation_history(user_id, created_at DESC)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_history_rating
            ON generation_history(rating)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_history_nsfw
            ON generation_history(is_nsfw)
        ''')

        print("数据库初始化完成")


def get_or_create_user(is_new=False):
    """获取或创建用户记录
    
    Args:
        is_new (bool): 如果为 True，则总是创建新用户；如果为 False，则返回最后一个用户
    
    Returns:
        int: 用户 ID
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if is_new:
            # 强制创建新用户
            cursor.execute('INSERT INTO users (first_seen, last_seen) VALUES (CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)')
            new_id = cursor.lastrowid
            print(f"创建新用户 ID: {new_id}")
            return new_id
        else:
            # 获取最后一个用户（用于向后兼容）
            cursor.execute('SELECT id FROM users ORDER BY id DESC LIMIT 1')
            row = cursor.fetchone()
            
            if row:
                # 更新最后访问时间
                user_id = row['id']
                cursor.execute('UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?', (user_id,))
                return user_id
            else:
                # 没有用户，创建第一个
                cursor.execute('INSERT INTO users (first_seen, last_seen) VALUES (CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)')
                new_id = cursor.lastrowid
                print(f"创建第一个用户 ID: {new_id}")
                return new_id


def add_history_record(record):
    """添加一条生成历史记录
    
    Args:
        record (dict): 包含图片信息的记录字典
            - user_id: 用户 ID（整数）
            - image_id: 图片 ID（时间戳）
            - image_url: 图片 URL
            - image_filename: 图片文件名
            - prompt: 提示词
            - negative_prompt: 负面提示词
            - width: 图片宽度
            - height: 图片高度
            - steps: 生成步数
            - seed: 随机种子
            - elapsed_time: 耗时（秒）
            - rating: 评分（-1为bad，0为未评分，1-5为星级）
    
    Returns:
        int: 新记录的 ID
    """
    user_id = record.get('user_id')
    if not user_id:
        raise ValueError("Record must contain 'user_id'")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO generation_history (
                user_id, image_id, image_url, image_filename,
                prompt, negative_prompt, width, height, steps, seed,
                elapsed_time, rating, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            record.get('id'),
            record.get('image_url'),
            record.get('image_filename'),
            record.get('prompt', ''),
            record.get('negative_prompt', ''),
            record.get('width', 512),
            record.get('height', 512),
            record.get('steps', 8),
            record.get('seed', -1),
            record.get('elapsed_time', 0),
            record.get('rating', 0),
            record.get('created_at', datetime.now().isoformat())
        ))
        
        return cursor.lastrowid


def get_user_history(user_id, limit=50, offset=0, date_filter=None, rating_filter=None, min_rating=None, exclude_bad=False, show_nsfw=False):
    """获取指定用户的历史记录
    
    Args:
        user_id (int): 用户 ID
        limit (int): 返回记录数量限制
        offset (int): 偏移量（用于分页）
        date_filter (str, optional): 日期筛选，格式 YYYY-MM-DD
        rating_filter (int or list, optional): 评分筛选（-1为bad，1-5为星级），支持单个值或列表
        min_rating (int, optional): 最低星级筛选（1-3），例如1表示一星及以上
        exclude_bad (bool): 是否排除Bad图片（rating=-1），默认为False
        show_nsfw (bool): 是否显示NSFW内容，默认为False
    
    Returns:
        list: 历史记录列表（字典形式）
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 构建查询条件
        conditions = ['user_id = ?']
        params = [user_id]
        
        if date_filter:
            conditions.append('DATE(created_at) = ?')
            params.append(date_filter)
        
        if rating_filter is not None:
            # 支持多个评级筛选
            if isinstance(rating_filter, list):
                if len(rating_filter) > 0:
                    placeholders = ','.join(['?' for _ in rating_filter])
                    conditions.append(f'rating IN ({placeholders})')
                    params.extend(rating_filter)
            else:
                conditions.append('rating = ?')
                params.append(rating_filter)
        
        if min_rating is not None:
            # 最低星级筛选
            if min_rating == 0:
                # 未评分（rating = 0）
                conditions.append('rating = 0')
            else:
                # 星级筛选（>= min_rating）
                conditions.append('rating >= ?')
                params.append(min_rating)
        
        if exclude_bad:
            # 排除Bad图片（rating != -1）
            conditions.append('rating != -1')
        
        # 默认隐藏NSFW内容
        if not show_nsfw:
            conditions.append('is_nsfw = 0')
        
        where_clause = ' AND '.join(conditions)
        
        query = f'''
            SELECT * FROM generation_history 
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        '''
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_all_history(limit=100, offset=0, date_filter=None, rating_filter=None, min_rating=None, exclude_bad=False, show_nsfw=False):
    """获取所有用户的历史记录
    
    Args:
        limit (int): 返回记录数量限制
        offset (int): 偏移量（用于分页）
        date_filter (str, optional): 日期筛选，格式 YYYY-MM-DD
        rating_filter (int or list, optional): 评分筛选（-1为bad，1-5为星级），支持单个值或列表
        min_rating (int, optional): 最低星级筛选（1-3），例如1表示一星及以上
        exclude_bad (bool): 是否排除Bad图片（rating=-1），默认为False
        show_nsfw (bool): 是否显示NSFW内容，默认为False
    
    Returns:
        list: 历史记录列表（字典形式）
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 构建查询条件
        conditions = []
        params = []
        
        if date_filter:
            conditions.append('DATE(created_at) = ?')
            params.append(date_filter)
        
        if rating_filter is not None:
            # 支持多个评级筛选
            if isinstance(rating_filter, list):
                if len(rating_filter) > 0:
                    placeholders = ','.join(['?' for _ in rating_filter])
                    conditions.append(f'rating IN ({placeholders})')
                    params.extend(rating_filter)
            else:
                conditions.append('rating = ?')
                params.append(rating_filter)
        
        if min_rating is not None:
            # 最低星级筛选
            if min_rating == 0:
                # 未评分（rating = 0）
                conditions.append('rating = 0')
            else:
                # 星级筛选（>= min_rating）
                conditions.append('rating >= ?')
                params.append(min_rating)
        
        if exclude_bad:
            # 排除Bad图片（rating != -1）
            conditions.append('rating != -1')
        
        # 默认隐藏NSFW内容
        if not show_nsfw:
            conditions.append('is_nsfw = 0')
        
        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        
        query = f'''
            SELECT * FROM generation_history 
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        '''
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_available_dates(user_id=None):
    """获取有记录的日期列表
    
    Args:
        user_id (int, optional): 用户 ID，如果为 None 则返回所有用户的日期
    
    Returns:
        list: 日期列表（格式 YYYY-MM-DD），按降序排列
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if user_id:
            query = '''
                SELECT DISTINCT DATE(created_at) as date 
                FROM generation_history 
                WHERE user_id = ?
                ORDER BY date DESC
            '''
            cursor.execute(query, (user_id,))
        else:
            query = '''
                SELECT DISTINCT DATE(created_at) as date 
                FROM generation_history 
                ORDER BY date DESC
            '''
            cursor.execute(query)
        
        rows = cursor.fetchall()
        return [row['date'] for row in rows]


def clear_user_history(user_id):
    """清空指定用户的历史记录
    
    Args:
        user_id (int): 用户 ID
    
    Returns:
        int: 删除的记录数量
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM generation_history WHERE user_id = ?', (user_id,))
        return cursor.rowcount


def get_history_count(user_id=None, date_filter=None, rating_filter=None, min_rating=None, exclude_bad=False, show_nsfw=False):
    """获取历史记录数量
    
    Args:
        user_id (int, optional): 用户 ID，如果为 None 则统计所有用户
        date_filter (str, optional): 日期筛选，格式 YYYY-MM-DD
        rating_filter (int or list, optional): 评分筛选（-1为bad，1-5为星级），支持单个值或列表
        min_rating (int, optional): 最低星级筛选（1-3），例如1表示一星及以上
        exclude_bad (bool): 是否排除Bad图片（rating=-1），默认为False
        show_nsfw (bool): 是否显示NSFW内容，默认为False
    
    Returns:
        int: 记录数量
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 构建查询条件
        conditions = []
        params = []
        
        if user_id:
            conditions.append('user_id = ?')
            params.append(user_id)
        
        if date_filter:
            conditions.append('DATE(created_at) = ?')
            params.append(date_filter)
        
        if rating_filter is not None:
            # 支持多个评级筛选
            if isinstance(rating_filter, list):
                if len(rating_filter) > 0:
                    placeholders = ','.join(['?' for _ in rating_filter])
                    conditions.append(f'rating IN ({placeholders})')
                    params.extend(rating_filter)
            else:
                conditions.append('rating = ?')
                params.append(rating_filter)
        
        if min_rating is not None:
            # 最低星级筛选
            if min_rating == 0:
                # 未评分（rating = 0）
                conditions.append('rating = 0')
            else:
                # 星级筛选（>= min_rating）
                conditions.append('rating >= ?')
                params.append(min_rating)
        
        if exclude_bad:
            # 排除Bad图片（rating != -1）
            conditions.append('rating != -1')
        
        # 默认隐藏NSFW内容
        if not show_nsfw:
            conditions.append('is_nsfw = 0')
        
        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        
        query = f'SELECT COUNT(*) as count FROM generation_history WHERE {where_clause}'
        cursor.execute(query, params)
        
        result = cursor.fetchone()
        return result['count'] if result else 0


def update_rating(image_id, rating):
    """更新图片评分
    
    Args:
        image_id (str): 图片 ID
        rating (int): 评分值（-1为bad，0为清除评分，1-5为星级）
    
    Returns:
        bool: 更新是否成功
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE generation_history 
            SET rating = ? 
            WHERE image_id = ?
        ''', (rating, image_id))
        return cursor.rowcount > 0


def update_history_record(image_id, updates):
    """更新历史记录的指定字段
    
    Args:
        image_id (str): 图片 ID
        updates (dict): 要更新的字段字典，如 {'elapsed_time': 10.5, 'seed': 12345}
    
    Returns:
        bool: 更新是否成功
    """
    if not updates:
        return False
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 构建动态UPDATE语句
        set_clauses = []
        params = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            params.append(value)
        
        params.append(image_id)
        set_clause = ", ".join(set_clauses)
        
        query = f"UPDATE generation_history SET {set_clause} WHERE image_id = ?"
        cursor.execute(query, params)
        return cursor.rowcount > 0


def delete_history_record(image_id):
    """删除历史记录
    
    Args:
        image_id (str): 图片 ID
    
    Returns:
        bool: 删除是否成功
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM generation_history WHERE image_id = ?', (image_id,))
        return cursor.rowcount > 0


def cleanup_incomplete_records(images_dir=None):
    """清理不完整的记录（图片文件不存在但数据库中有记录）
    
    通常在程序启动时调用，用于清理因程序崩溃而留下的孤儿记录。
    
    Args:
        images_dir (str, optional): 图片目录路径，默认为项目根目录下的 generated_images
    
    Returns:
        dict: 包含 cleaned_count（清理数量）和 orphaned_ids（孤儿记录ID列表）
    """
    import os
    
    if images_dir is None:
        images_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'generated_images')
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 获取所有记录
        cursor.execute('SELECT id, image_id, image_filename FROM generation_history')
        rows = cursor.fetchall()
        
        orphaned_ids = []
        cleaned_count = 0
        
        for row in rows:
            image_filename = row['image_filename']
            image_path = os.path.join(images_dir, image_filename)
            
            # 检查图片文件是否存在
            if not os.path.exists(image_path):
                # 图片文件不存在，这是孤儿记录
                orphaned_ids.append(row['image_id'])
                cursor.execute('DELETE FROM generation_history WHERE id = ?', (row['id'],))
                cleaned_count += 1
        
        if cleaned_count > 0:
            print(f"清理了 {cleaned_count} 条不完整的历史记录")
        
        return {
            'cleaned_count': cleaned_count,
            'orphaned_ids': orphaned_ids
        }


def toggle_nsfw(image_id):
    """切换图片的NSFW标记
    
    Args:
        image_id (str): 图片 ID
    
    Returns:
        tuple: (success: bool, new_nsfw_value: int)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 先获取当前值
        cursor.execute('SELECT is_nsfw FROM generation_history WHERE image_id = ?', (image_id,))
        row = cursor.fetchone()
        if not row:
            return False, 0
        
        current_nsfw = row['is_nsfw']
        new_nsfw = 1 if current_nsfw == 0 else 0
        
        cursor.execute('''
            UPDATE generation_history 
            SET is_nsfw = ? 
            WHERE image_id = ?
        ''', (new_nsfw, image_id))
        return cursor.rowcount > 0, new_nsfw


def update_nsfw_status(image_id, is_nsfw):
    """直接设置图片的NSFW状态
    
    Args:
        image_id (str): 图片 ID
        is_nsfw (bool): 是否标记为NSFW
    
    Returns:
        bool: 更新成功返回True，失败返回False
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        nsfw_value = 1 if is_nsfw else 0
        
        cursor.execute('''
            UPDATE generation_history 
            SET is_nsfw = ? 
            WHERE image_id = ?
        ''', (nsfw_value, image_id))
        
        return cursor.rowcount > 0


def get_bad_images(all_users=False, user_id=None):
    """获取所有标记为 Bad 的图片
    
    Args:
        all_users (bool): 是否获取所有用户的 Bad 图片
        user_id (int, optional): 用户 ID
    
    Returns:
        list: Bad 图片记录列表
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if all_users:
            query = '''
                SELECT * FROM generation_history 
                WHERE rating = -1
                ORDER BY created_at DESC
            '''
            cursor.execute(query)
        else:
            query = '''
                SELECT * FROM generation_history 
                WHERE rating = -1 AND user_id = ?
                ORDER BY created_at DESC
            '''
            cursor.execute(query, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def delete_bad_images(all_users=False, user_id=None):
    """删除所有标记为 Bad 的图片记录
    
    Args:
        all_users (bool): 是否删除所有用户的 Bad 图片
        user_id (int, optional): 用户 ID
    
    Returns:
        tuple: (删除的记录数, 删除的图片文件名列表)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 先获取要删除的图片文件名
        if all_users:
            query = 'SELECT image_filename FROM generation_history WHERE rating = -1'
            cursor.execute(query)
        else:
            query = 'SELECT image_filename FROM generation_history WHERE rating = -1 AND user_id = ?'
            cursor.execute(query, (user_id,))
        
        rows = cursor.fetchall()
        filenames = [row['image_filename'] for row in rows]
        
        # 删除记录
        if all_users:
            delete_query = 'DELETE FROM generation_history WHERE rating = -1'
            cursor.execute(delete_query)
        else:
            delete_query = 'DELETE FROM generation_history WHERE rating = -1 AND user_id = ?'
            cursor.execute(delete_query, (user_id,))
        
        deleted_count = cursor.rowcount
        return deleted_count, filenames


def migrate_from_json(json_file=None):
    """从 JSON 文件迁移数据到数据库（已弃用，仅保留接口）
    
    Args:
        json_file (str, optional): JSON 文件路径
    
    Returns:
        dict: 迁移统计信息
    """
    return {"success": False, "error": "Migration from JSON is no longer supported"}


# 初始化数据库（模块导入时自动执行）
init_database()


# =============================================================================
# 用户系统
# =============================================================================

# 用户名约束
USERNAME_MIN_LEN = 1
USERNAME_MAX_LEN = 64
PASSWORD_MIN_LEN = 1
PASSWORD_MAX_LEN = 128


class UserError(Exception):
    """用户系统错误基类"""
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _validate_username(username):
    if not isinstance(username, str):
        raise UserError("账号必须是字符串", 400)
    username = username.strip()
    if len(username) < USERNAME_MIN_LEN or len(username) > USERNAME_MAX_LEN:
        raise UserError(
            f"账号长度需在 {USERNAME_MIN_LEN}-{USERNAME_MAX_LEN} 字符之间", 400
        )
    return username


def _validate_password(password):
    if not isinstance(password, str):
        raise UserError("密码必须是字符串", 400)
    if len(password) < PASSWORD_MIN_LEN or len(password) > PASSWORD_MAX_LEN:
        raise UserError(
            f"密码长度需在 {PASSWORD_MIN_LEN}-{PASSWORD_MAX_LEN} 字符之间", 400
        )
    return password


def _normalize_username(username):
    """用于查询和唯一约束的规范化形式：去首尾空格，小写。"""
    return username.strip().lower()


def find_user_by_username(username):
    """根据账号查找用户。"""
    norm = _normalize_username(username)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 用 LOWER(username) = ? 做不区分大小写的查找
        cursor.execute(
            "SELECT id, username, password, is_guest FROM users "
            "WHERE LOWER(username) = ? AND is_guest = 0",
            (norm,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def find_user_by_id(user_id):
    """根据主键查找用户。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password, is_guest, created_at_ip, first_seen, last_seen "
            "FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def register_user(username, password):
    """注册正式用户。返回新用户 dict。

    Raises:
        UserError: 账号已存在 / 校验失败
    """
    username = _validate_username(username)
    password = _validate_password(password)
    norm = _normalize_username(username)

    if find_user_by_username(username):
        raise UserError("该账号已存在", 409)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 保存原始大小写形式展示
        cursor.execute(
            "INSERT INTO users (username, password, is_guest) VALUES (?, ?, 0)",
            (username, password),
        )
        new_id = cursor.lastrowid
        return {
            "id": new_id,
            "username": username,
            "is_guest": 0,
        }


def login_user(username, password):
    """校验账号密码。返回用户 dict 或 None。"""
    username = _validate_username(username)
    password = _validate_password(password)
    user = find_user_by_username(username)
    if not user or user.get("is_guest"):
        return None
    if user.get("password") != password:
        return None
    # 更新 last_seen
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (user["id"],),
        )
    return {"id": user["id"], "username": user["username"], "is_guest": 0}


def login_or_register_guest(legacy_user_id=None, client_ip=None):
    """游客登录。

    - 若 legacy_user_id 是数据库中已存在的用户（可能没有 username），则复用
      并把 is_guest 置 1。保留该用户的所有历史记录。
    - 否则新建一个游客用户。
    """
    if legacy_user_id is not None:
        try:
            legacy_user_id = int(legacy_user_id)
        except (TypeError, ValueError):
            legacy_user_id = None

        if legacy_user_id is not None:
            existing = find_user_by_id(legacy_user_id)
            if existing:
                # 标记为游客（即使原来已有 username 也不再当作正式用户，简化逻辑）
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET is_guest = 1, last_seen = CURRENT_TIMESTAMP, "
                        "created_at_ip = COALESCE(created_at_ip, ?) WHERE id = ?",
                        (client_ip, legacy_user_id),
                    )
                return {
                    "id": existing["id"],
                    "username": existing.get("username"),
                    "is_guest": 1,
                }

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (is_guest, created_at_ip) VALUES (1, ?)",
            (client_ip,),
        )
        new_id = cursor.lastrowid
        return {"id": new_id, "username": None, "is_guest": 1}


def public_user_dict(user):
    """脱敏的用户信息，用于返回给前端。"""
    if not user:
        return None
    is_guest = bool(user.get("is_guest"))
    return {
        "id": user["id"],
        "username": user.get("username") if not is_guest else None,
        "display_name": (
            user.get("username") if not is_guest
            else f"游客-{user['id']:04d}"
        ),
        "is_guest": is_guest,
    }


# =============================================================================
# 提示词预设
# =============================================================================

def get_user_presets(user_id):
    """获取指定用户的所有提示词预设，按 id 升序。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, content, created_at FROM prompt_presets "
            "WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def add_preset(user_id, content):
    """添加提示词预设。content 必填。"""
    if not isinstance(content, str):
        raise UserError("提示词内容必须是字符串", 400)
    content = content.strip()
    if not content:
        raise UserError("提示词不能为空", 400)
    if len(content) > 4000:
        raise UserError("提示词过长（最多 4000 字符）", 400)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO prompt_presets (user_id, content) VALUES (?, ?)",
            (user_id, content),
        )
        new_id = cursor.lastrowid
        return {"id": new_id, "content": content}


def update_preset(user_id, preset_id, content):
    """更新预设。校验所有权。"""
    if not isinstance(content, str):
        raise UserError("提示词内容必须是字符串", 400)
    content = content.strip()
    if not content:
        raise UserError("提示词不能为空", 400)
    if len(content) > 4000:
        raise UserError("提示词过长（最多 4000 字符）", 400)
    try:
        preset_id = int(preset_id)
    except (TypeError, ValueError):
        raise UserError("无效的预设 ID", 400)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE prompt_presets SET content = ? WHERE id = ? AND user_id = ?",
            (content, preset_id, user_id),
        )
        if cursor.rowcount == 0:
            # 区分不存在 vs 无权限，统一返回 404
            raise UserError("预设不存在或无权操作", 404)
        return {"id": preset_id, "content": content}


def delete_preset(user_id, preset_id):
    """删除预设。校验所有权。"""
    try:
        preset_id = int(preset_id)
    except (TypeError, ValueError):
        raise UserError("无效的预设 ID", 400)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM prompt_presets WHERE id = ? AND user_id = ?",
            (preset_id, user_id),
        )
        if cursor.rowcount == 0:
            raise UserError("预设不存在或无权操作", 404)
        return True


# =============================================================================
# AI 大模型配置（按用户存储）
# =============================================================================

def get_user_llm_config(user_id):
    """获取用户的 LLM 配置。如果没有，返回空 dict。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT llm_api_url, llm_model, llm_api_key FROM user_llm_config WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "llm_api_url": row["llm_api_url"] or "",
                "llm_model": row["llm_model"] or "",
                "llm_api_key": row["llm_api_key"] or "",
            }
        return {}


def save_user_llm_config(user_id, llm_api_url="", llm_model="", llm_api_key=""):
    """保存用户的 LLM 配置（UPSERT）。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO user_llm_config (user_id, llm_api_url, llm_model, llm_api_key, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   llm_api_url = excluded.llm_api_url,
                   llm_model = excluded.llm_model,
                   llm_api_key = excluded.llm_api_key,
                   updated_at = CURRENT_TIMESTAMP""",
            (user_id, llm_api_url, llm_model, llm_api_key),
        )
        return True


# =============================================================================
# 通知配置（ntfy，按用户存储）
# =============================================================================

def get_user_notify_config(user_id):
    """获取用户的 ntfy 通知配置。如果没有，返回空 dict。"""
    if not user_id:
        return {}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ntfy_topic, ntfy_server FROM user_notify_config WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "ntfy_topic": row["ntfy_topic"] or "",
                "ntfy_server": row["ntfy_server"] or "",
            }
        return {}


def save_user_notify_config(user_id, ntfy_topic="", ntfy_server=""):
    """保存用户的 ntfy 通知配置（UPSERT）。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO user_notify_config (user_id, ntfy_topic, ntfy_server, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   ntfy_topic = excluded.ntfy_topic,
                   ntfy_server = excluded.ntfy_server,
                   updated_at = CURRENT_TIMESTAMP""",
            (user_id, ntfy_topic, ntfy_server),
        )
        return True
