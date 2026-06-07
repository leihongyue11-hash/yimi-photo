"""
壹米云相册 - 设置/向导路由
"""
import logging
from flask import Blueprint, request, jsonify
from config import get_all, __version__
from auth import requires_auth

logger = logging.getLogger(__name__)
bp = Blueprint("setup", __name__)


@bp.route("/api/settings")
@requires_auth
def get_settings():
    return jsonify(get_all())
