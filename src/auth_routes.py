"""
用户认证路由：注册、登录、游客、注销、当前用户信息。
基于 Flask session + cookie，默认 30 天免登录。
"""
from functools import wraps
from flask import Blueprint, request, jsonify, session

try:
    from src import database
    from src.database import (
        register_user,
        login_user,
        login_or_register_guest,
        find_user_by_id,
        public_user_dict,
        UserError,
    )
except ModuleNotFoundError:
    import database
    from database import (
        register_user,
        login_user,
        login_or_register_guest,
        find_user_by_id,
        public_user_dict,
        UserError,
    )

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _client_ip():
    """尽量从反向代理头里取真实 IP，本地直连 fallback 到 remote_addr。"""
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr


def login_required(fn):
    """要求登录（正式或游客均可）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"error": "未登录", "code": "AUTH_REQUIRED"}), 401
        user = find_user_by_id(user_id)
        if not user:
            # session 里的用户已被删除
            session.clear()
            return jsonify({"error": "会话已失效，请重新登录", "code": "AUTH_INVALID"}), 401
        # 把当前用户挂到 request 上方便后续使用
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def login_required_real(fn):
    """要求正式用户（排除游客）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"error": "未登录", "code": "AUTH_REQUIRED"}), 401
        user = find_user_by_id(user_id)
        if not user:
            session.clear()
            return jsonify({"error": "会话已失效，请重新登录", "code": "AUTH_INVALID"}), 401
        if user.get("is_guest"):
            return jsonify({"error": "该操作仅对正式用户开放", "code": "GUEST_FORBIDDEN"}), 403
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def _mark_session(user_id, permanent=True):
    session.clear()
    session["user_id"] = user_id
    if permanent:
        session.permanent = True


@bp.post("/register")
def api_register():
    """POST /api/auth/register  body: {username, password, password2}"""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    password2 = data.get("password2", "")

    if not username:
        return jsonify({"error": "请输入账号"}), 400
    if not password:
        return jsonify({"error": "请输入密码"}), 400
    if password != password2:
        return jsonify({"error": "两次输入的密码不一致"}), 400

    try:
        user = register_user(username, password)
    except UserError as e:
        return jsonify({"error": e.message}), e.status_code

    _mark_session(user["id"])
    return jsonify({"user": public_user_dict(user), "ok": True})


@bp.post("/login")
def api_login():
    """POST /api/auth/login  body: {username, password}"""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "请输入账号和密码"}), 400
    try:
        user = login_user(username, password)
    except UserError as e:
        return jsonify({"error": e.message}), e.status_code
    if not user:
        return jsonify({"error": "账号或密码错误"}), 401
    _mark_session(user["id"])
    return jsonify({"user": public_user_dict(user), "ok": True})


@bp.post("/guest")
def api_guest():
    """POST /api/auth/guest  body: {legacy_user_id?}

    legacy_user_id 用来把老 localStorage.user_id 绑定到新游客账号。
    """
    data = request.get_json(silent=True) or {}
    legacy = data.get("legacy_user_id")
    try:
        user = login_or_register_guest(
            legacy_user_id=legacy,
            client_ip=_client_ip(),
        )
    except UserError as e:
        return jsonify({"error": e.message}), e.status_code
    _mark_session(user["id"])
    return jsonify({"user": public_user_dict(user), "ok": True})


@bp.get("/me")
def api_me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"user": None, "authenticated": False})
    user = find_user_by_id(user_id)
    if not user:
        session.clear()
        return jsonify({"user": None, "authenticated": False})
    return jsonify({"user": public_user_dict(user), "authenticated": True})


@bp.post("/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})
