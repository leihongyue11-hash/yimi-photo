"""
壹米云相册 - 认证模块 (无密码版)
"""
import os
import logging
from functools import wraps
from flask import request, jsonify, Blueprint

logger = logging.getLogger(__name__)
bp = Blueprint("auth", __name__)


def requires_auth(f):
    """No-auth mode: always pass through"""
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated


@bp.route("/api/auth/status")
def auth_status():
    return jsonify({"authenticated": True})


@bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    return jsonify({"ok": True, "token": "no-auth"})


@bp.route("/api/auth/setup", methods=["POST"])
def auth_setup():
    return jsonify({"ok": True, "token": "no-auth"})


@bp.route("/api/version")
def version():
    from config import __version__
    return jsonify({"version": __version__})
