"""
壹米云相册 - 应用工厂
"""
import os
import logging
from flask import Flask, send_from_directory, request
from flask_cors import CORS

from config import init_config, photos_dir, get, __version__
from database import init_pool, migrate_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    cfg = init_config()
    logger.info("壹米云相册 v%s 启动中...", __version__)
    logger.info("数据目录: %s", photos_dir())

    init_pool()
    migrate_db()

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = get("max_upload_mb", 500) * 1024 * 1024
    CORS(app)

    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

    @app.after_request
    def no_cache(response):
        if request.path == "/" or request.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.route("/")
    def index():
        return send_from_directory(frontend_dir, "index.html")

    @app.route("/manifest.json")
    def manifest():
        return send_from_directory(frontend_dir, "manifest.json")

    @app.route("/sw.js")
    def sw():
        return send_from_directory(frontend_dir, "sw.js")

    @app.route("/icon-192.png")
    def i192():
        p = os.path.join(frontend_dir, "icon-192.png")
        return send_from_directory(frontend_dir, "icon-192.png") if os.path.isfile(p) else ("", 404)

    @app.route("/icon-512.png")
    def i512():
        p = os.path.join(frontend_dir, "icon-512.png")
        return send_from_directory(frontend_dir, "icon-512.png") if os.path.isfile(p) else ("", 404)

    @app.route("/assets/<path:filepath>")
    def serve_assets(filepath):
        return send_from_directory(os.path.join(frontend_dir, "assets"), filepath)

    from routes import photos, albums, persons, tags, storage, setup
    from auth import bp as auth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(setup.bp)
    app.register_blueprint(photos.bp)
    app.register_blueprint(albums.bp)
    app.register_blueprint(persons.bp)
    app.register_blueprint(tags.bp)
    app.register_blueprint(storage.bp)

    @app.errorhandler(404)
    def not_found(e):
        return {"error": "not found"}, 404

    @app.errorhandler(413)
    def too_large(e):
        return {"error": "文件太大", "max_mb": get("max_upload_mb", 500)}, 413

    @app.errorhandler(500)
    def server_error(e):
        logger.error("服务器错误: %s", e)
        return {"error": "服务器内部错误"}, 500

    logger.info("应用初始化完成")
    return app
