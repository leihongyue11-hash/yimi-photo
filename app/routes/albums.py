"""
壹米云相册 - 相册路由 (修复版)
修复: 文件夹相册创建时 database locked 问题
"""
import os
import hashlib
import logging
from flask import Blueprint, request, jsonify

from config import photos_dir, thumbs_dir, thumb_small, thumb_medium, get as cfg
from database import get_db, safe_execute
from auth import requires_auth
from utils import (
    make_thumbnail, make_video_thumbnail, get_photo_date,
    get_image_dimensions, format_size, is_video, media_type,
)

logger = logging.getLogger(__name__)
bp = Blueprint("albums", __name__)


def _photo_info_simple(row) -> dict:
    from routes.photos import photo_info
    return photo_info(row)


# ============ 相册 CRUD ============
@bp.route("/api/albums")
@requires_auth
def list_albums():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.*,
                   COUNT(ap.photo_id) as total_count,
                   SUM(CASE WHEN p.is_deleted=0 THEN 1 ELSE 0 END) as photo_count
            FROM albums a
            LEFT JOIN album_photos ap ON a.id=ap.album_id
            LEFT JOIN photos p ON p.id=ap.photo_id
            GROUP BY a.id
            ORDER BY a.created_at DESC
        """).fetchall()

        albums = []
        for r in rows:
            cover = None
            if r["cover_photo_id"]:
                cr = conn.execute("SELECT * FROM photos WHERE id=? AND is_deleted=0", (r["cover_photo_id"],)).fetchone()
                if cr:
                    cover = _photo_info_simple(cr)
            if not cover and r["photo_count"] and r["photo_count"] > 0:
                first = conn.execute("""
                    SELECT p.* FROM photos p
                    JOIN album_photos ap ON p.id=ap.photo_id
                    WHERE ap.album_id=? AND p.is_deleted=0 LIMIT 1
                """, (r["id"],)).fetchone()
                if first:
                    cover = _photo_info_simple(first)

            albums.append({
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "photo_count": r["photo_count"] or 0,
                "cover": cover,
            })
    return jsonify({"albums": albums})


@bp.route("/api/albums", methods=["POST"])
@requires_auth
def create_album():
    data = request.get_json()
    name = data.get("name", "").strip()
    description = data.get("description", "")
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as conn:
        safe_execute(conn, "INSERT INTO albums (name, description) VALUES (?,?)", (name, description))
        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({"id": aid, "name": name})


@bp.route("/api/albums/<int:aid>")
@requires_auth
def get_album(aid):
    with get_db() as conn:
        album = conn.execute("SELECT * FROM albums WHERE id=?", (aid,)).fetchone()
        if not album:
            return jsonify({"error": "not found"}), 404
        photos = conn.execute("""
            SELECT p.* FROM photos p
            JOIN album_photos ap ON p.id=ap.photo_id
            WHERE ap.album_id=? AND p.is_deleted=0
            ORDER BY ap.added_at DESC
        """, (aid,)).fetchall()
    return jsonify({
        "id": album["id"],
        "name": album["name"],
        "description": album["description"],
        "photos": [_photo_info_simple(r) for r in photos],
    })


@bp.route("/api/albums/<int:aid>", methods=["PUT"])
@requires_auth
def update_album(aid):
    data = request.get_json()
    with get_db() as conn:
        if "name" in data:
            safe_execute(conn, "UPDATE albums SET name=? WHERE id=?", (data["name"], aid))
        if "description" in data:
            safe_execute(conn, "UPDATE albums SET description=? WHERE id=?", (data["description"], aid))
    return jsonify({"ok": True})


@bp.route("/api/albums/<int:aid>", methods=["DELETE"])
@requires_auth
def delete_album(aid):
    with get_db() as conn:
        safe_execute(conn, "DELETE FROM album_photos WHERE album_id=?", (aid,))
        safe_execute(conn, "DELETE FROM albums WHERE id=?", (aid,))
    return jsonify({"ok": True})


@bp.route("/api/albums/<int:aid>/photos", methods=["POST"])
@requires_auth
def add_to_album(aid):
    data = request.get_json()
    ids = data.get("photo_ids", [])
    with get_db() as conn:
        for pid in ids:
            safe_execute(conn, "INSERT OR IGNORE INTO album_photos (album_id, photo_id) VALUES (?,?)", (aid, pid))
        if ids:
            safe_execute(conn, "UPDATE albums SET cover_photo_id=? WHERE id=?", (ids[0], aid))
    return jsonify({"ok": True, "added": len(ids)})


@bp.route("/api/albums/<int:aid>/photos/<int:pid>", methods=["DELETE"])
@requires_auth
def remove_from_album(aid, pid):
    with get_db() as conn:
        safe_execute(conn, "DELETE FROM album_photos WHERE album_id=? AND photo_id=?", (aid, pid))
    return jsonify({"ok": True})


# ============ 文件夹映射相册 ============
@bp.route("/api/albums/folder", methods=["POST"])
@requires_auth
def create_folder_album():
    """从文件夹创建相册 - 直接引用原文件，不复制
    修复: 分批提交，避免长时间锁定数据库"""
    from security import is_safe_path
    data = request.get_json()
    folder_path = data.get("folder_path", "").strip()
    album_name = data.get("name", "").strip()
    description = data.get("description", "")

    if not folder_path:
        return jsonify({"error": "folder_path required"}), 400
    if not is_safe_path(folder_path):
        return jsonify({"error": "不允许访问该路径"}), 403
    if not os.path.exists(folder_path):
        return jsonify({"error": "Folder does not exist"}), 400

    if not album_name:
        album_name = os.path.basename(folder_path) or "根目录"

    photo_exts = ("jpg", "jpeg", "png", "gif", "heic", "heif", "bmp", "tiff", "webp")
    video_exts = ("mp4", "mov", "avi", "mkv", "webm", "3gp")
    all_exts = photo_exts + video_exts

    # === 阶段1: 扫描文件（不需要数据库锁） ===
    files_to_process = []
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in all_exts:
                files_to_process.append(os.path.join(root, fname))

    if not files_to_process:
        return jsonify({"error": "文件夹中没有找到照片/视频"}), 400

    logger.info(f"[folder-album] 扫描到 {len(files_to_process)} 个媒体文件: {folder_path}")

    # === 阶段2: 创建相册（短事务） ===
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM albums WHERE name=?", (album_name,)).fetchone()
        if existing:
            album_id = existing[0]
        else:
            safe_execute(conn, "INSERT INTO albums (name, description) VALUES (?,?)",
                         (album_name, description or f"映射: {folder_path}"))
            album_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # === 阶段3: 逐批导入照片（每20个提交一次，避免长时间锁） ===
    pd = photos_dir()
    added_count = linked_count = 0
    errors = []
    batch_size = 20

    for i in range(0, len(files_to_process), batch_size):
        batch = files_to_process[i:i+batch_size]
        try:
            with get_db() as conn:
                for file_path in batch:
                    try:
                        fname = os.path.basename(file_path)
                        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                        fsize = os.path.getsize(file_path)

                        # 快速哈希去重
                        h = hashlib.md5()
                        with open(file_path, "rb") as fobj:
                            if fsize > 10 * 1024 * 1024:
                                h.update(fobj.read(65536))
                                fobj.seek(max(0, fsize - 65536))
                                h.update(fobj.read(65536))
                                h.update(str(fsize).encode())
                            else:
                                h.update(fobj.read())
                        file_hash = h.hexdigest()

                        # 检查是否已存在
                        dup = conn.execute("SELECT id FROM photos WHERE file_hash=?", (file_hash,)).fetchone()
                        if dup:
                            safe_execute(conn, "INSERT OR IGNORE INTO album_photos (album_id, photo_id) VALUES (?,?)",
                                         (album_id, dup[0]))
                            linked_count += 1
                            continue

                        mtype = media_type(ext)
                        taken = get_photo_date(file_path)
                        file_id = hashlib.md5(file_path.encode()).hexdigest()[:12]
                        td = os.path.join(thumbs_dir(), "external")
                        os.makedirs(td, exist_ok=True)

                        thumb_s = thumb_m = None
                        width = height = None
                        quality = cfg("thumb_quality", 60)

                        s_thumb = os.path.join(td, f"s_{file_id}.jpg")
                        m_thumb = os.path.join(td, f"m_{file_id}.jpg")
                        if mtype == "photo":
                            dims = get_image_dimensions(file_path)
                            if dims:
                                width, height = dims
                            if make_thumbnail(file_path, s_thumb, thumb_small(), quality):
                                thumb_s = os.path.relpath(s_thumb, pd)
                            if make_thumbnail(file_path, m_thumb, thumb_medium(), quality):
                                thumb_m = os.path.relpath(m_thumb, pd)
                        else:
                            if make_video_thumbnail(file_path, s_thumb, thumb_small()):
                                thumb_s = os.path.relpath(s_thumb, pd)
                            if make_video_thumbnail(file_path, m_thumb, thumb_medium()):
                                thumb_m = os.path.relpath(m_thumb, pd)

                        rel_id = f"ext_{file_id}_{fname}"
                        safe_execute(conn, """INSERT INTO photos
                            (filename, original_name, rel_path, original_path, thumb_small, thumb_medium,
                             file_size, file_hash, media_type, width, height, taken_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (fname, fname, rel_id, file_path, thumb_s, thumb_m,
                             fsize, file_hash, mtype, width, height, taken.isoformat()))
                        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                        safe_execute(conn, "INSERT OR IGNORE INTO album_photos (album_id, photo_id) VALUES (?,?)",
                                     (album_id, pid))
                        added_count += 1
                    except Exception as e:
                        errors.append(f"{os.path.basename(file_path)}: {str(e)}")
                # 每批提交一次
        except Exception as e:
            logger.error(f"[folder-album] 批次处理失败: {e}")
            errors.append(f"批次 {i//batch_size+1}: {str(e)}")

    # === 阶段4: 更新封面和计数（短事务） ===
    try:
        with get_db() as conn:
            first = conn.execute("SELECT photo_id FROM album_photos WHERE album_id=? LIMIT 1", (album_id,)).fetchone()
            if first:
                safe_execute(conn, "UPDATE albums SET cover_photo_id=? WHERE id=?", (first[0], album_id))
            count = conn.execute("SELECT COUNT(*) FROM album_photos WHERE album_id=?", (album_id,)).fetchone()[0]
            safe_execute(conn, "UPDATE albums SET photo_count=? WHERE id=?", (count, album_id))
    except Exception as e:
        logger.error(f"[folder-album] 更新封面失败: {e}")

    logger.info(f"[folder-album] 完成: {album_name}, 新增{added_count}, 关联{linked_count}, 错误{len(errors)}")

    return jsonify({
        "ok": True, "album_id": album_id, "name": album_name,
        "added": added_count, "linked": linked_count,
        "total": added_count + linked_count,
        "errors": errors[:5] if errors else [],
    })


