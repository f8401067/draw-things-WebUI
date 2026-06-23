"""
提示词预设 CRUD API
"""
from flask import Blueprint, request, jsonify

try:
    from src.database import (
        get_user_presets,
        add_preset,
        update_preset,
        delete_preset,
        UserError,
    )
except ModuleNotFoundError:
    from database import (
        get_user_presets,
        add_preset,
        update_preset,
        delete_preset,
        UserError,
    )
try:
    from src.auth_routes import login_required
except ModuleNotFoundError:
    from auth_routes import login_required

bp = Blueprint("presets", __name__, url_prefix="/api/presets")


def _current_user_id():
    """从 request.current_user 取出 user_id。由 @login_required 保证存在。"""
    return request.current_user["id"]


@bp.get("")
@login_required
def api_list_presets():
    presets = get_user_presets(_current_user_id())
    return jsonify({"presets": presets})


@bp.post("")
@login_required
def api_add_preset():
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    try:
        preset = add_preset(_current_user_id(), content)
    except UserError as e:
        return jsonify({"error": e.message}), e.status_code
    return jsonify({"preset": preset, "ok": True})


@bp.put("/<preset_id>")
@login_required
def api_update_preset(preset_id):
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    try:
        preset = update_preset(_current_user_id(), preset_id, content)
    except UserError as e:
        return jsonify({"error": e.message}), e.status_code
    return jsonify({"preset": preset, "ok": True})


@bp.delete("/<preset_id>")
@login_required
def api_delete_preset(preset_id):
    try:
        delete_preset(_current_user_id(), preset_id)
    except UserError as e:
        return jsonify({"error": e.message}), e.status_code
    return jsonify({"ok": True})
