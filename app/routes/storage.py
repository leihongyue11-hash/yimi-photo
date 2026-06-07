"""
壹米云相册 - 存储管理路由
存储位置管理 + 文件浏览
"""
import os
import json
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from config import photos_dir, get as cfg, set_config
from auth import requires_auth
from security import safe_browse_path, is_safe_path

logger = logging.getLogger(__name__)
bp = Blueprint("storage", __name__)


def _config_path():
    return os.path.join(photos_dir(), ".config", "storage_locations.json")


def _load_locations():
    path = _config_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f).get("locations", [])
        except Exception:
            pass
    return []


def _save_locations(locations):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"locations": locations}, f, indent=2, ensure_ascii=False)


@bp.route("/api/storage/locations")
@requires_auth
def list_storage_locations():
    pd = photos_dir()
    locations = _load_locations()
    if not locations:
        locations = [{"path": pd, "name": "默认存储", "type": "local"}]

    for loc in locations:
        loc["active"] = (os.path.normpath(loc["path"]) == os.path.normpath(pd))
        loc["exists"] = os.path.exists(loc["path"])
        if loc["exists"]:
            try:
                photo_count = video_count = 0
                for root, dirs, files in os.walk(loc["path"]):
                    if "/." in root:
                        continue
                    for f in files:
                        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                        if ext in ("jpg", "jpeg", "png", "gif", "heic", "heif", "bmp", "tiff", "webp"):
                            photo_count += 1
                        elif ext in ("mp4", "mov", "avi", "mkv", "webm", "3gp"):
                            video_count += 1
                loc["photo_count"] = photo_count
                loc["video_count"] = video_count
                loc["total_count"] = photo_count + video_count
            except Exception:
                loc["photo_count"] = loc["video_count"] = loc["total_count"] = 0
        else:
            loc["photo_count"] = loc["video_count"] = loc["total_count"] = 0

    return jsonify({"locations": locations, "current": pd})


@bp.route("/api/storage/locations", methods=["POST"])
@requires_auth
def add_storage_location():
    data = request.get_json()
    path = data.get("path", "").strip()
    name = data.get("name", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 400
    if not is_safe_path(path):
        return jsonify({"error": "不允许访问该路径"}), 403
    if not name:
        name = os.path.basename(path)
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"Cannot create: {e}"}), 400

    locations = _load_locations()
    for loc in locations:
        if loc["path"] == path:
            return jsonify({"error": "Location already exists"}), 400
    locations.append({"path": path, "name": name, "type": "local"})
    _save_locations(locations)
    return jsonify({"ok": True, "path": path, "name": name})


@bp.route("/api/storage/locations/<int:index>", methods=["DELETE"])
@requires_auth
def delete_storage_location(index):
    locations = _load_locations()
    if index < 0 or index >= len(locations):
        return jsonify({"error": "Invalid index"}), 400
    if os.path.normpath(locations[index]["path"]) == os.path.normpath(photos_dir()):
        return jsonify({"error": "Cannot delete active location"}), 400
    locations.pop(index)
    _save_locations(locations)
    return jsonify({"ok": True})


@bp.route("/api/storage/switch", methods=["POST"])
@requires_auth
def switch_storage():
    data = request.get_json()
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 400
    if not os.path.exists(path):
        return jsonify({"error": "Path does not exist"}), 400
    set_config("photos_dir", path)
    return jsonify({"ok": True, "message": "存储位置已切换，重启后生效", "path": path, "restart_required": True})


@bp.route("/api/storage/browse")
@requires_auth
def browse_storage():
    """安全文件浏览（白名单限制）"""
    path = request.args.get("path", "/mnt")
    safe_path, err = safe_browse_path(path)
    if err:
        return jsonify({"error": err}), 403

    photo_exts = ("jpg", "jpeg", "png", "gif", "heic", "heif", "bmp", "tiff", "webp")
    video_exts = ("mp4", "mov", "avi", "mkv", "webm", "3gp")

    try:
        items = []
        for item in os.listdir(safe_path):
            item_path = os.path.join(safe_path, item)
            try:
                stat = os.stat(item_path)
                is_dir = os.path.isdir(item_path)
                item_data = {
                    "name": item, "path": item_path, "is_dir": is_dir,
                    "size": stat.st_size if not is_dir else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "photo_count": 0, "video_count": 0,
                }
                if is_dir:
                    try:
                        for f in os.listdir(item_path):
                            if f.startswith("."):
                                continue
                            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                            if ext in photo_exts:
                                item_data["photo_count"] += 1
                            elif ext in video_exts:
                                item_data["video_count"] += 1
                    except Exception:
                        pass
                else:
                    ext = item.rsplit(".", 1)[-1].lower() if "." in item else ""
                    if ext in photo_exts:
                        item_data["photo_count"] = 1
                    elif ext in video_exts:
                        item_data["video_count"] = 1
                items.append(item_data)
            except Exception:
                continue

        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return jsonify({"path": safe_path, "parent": os.path.dirname(safe_path) if safe_path != "/" else None, "items": items})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500
