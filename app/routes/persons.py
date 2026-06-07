"""
壹米云相册 - 人物路由
"""
import logging
from flask import Blueprint, request, jsonify
from database import get_db, safe_execute
from auth import requires_auth

logger = logging.getLogger(__name__)
bp = Blueprint("persons", __name__)


def _photo_info(row):
    from routes.photos import photo_info
    return photo_info(row)


@bp.route("/api/persons")
@requires_auth
def list_persons():
    with get_db(write=False) as conn:
        rows = conn.execute("""
            SELECT p.id, p.name, p.cover_photo_id,
                   COUNT(pp.photo_id) as photo_count,
                   cp.id as cover_id, cp.filename as cover_filename,
                   cp.rel_path as cover_rel_path, cp.original_name as cover_original_name,
                   cp.thumb_small as cover_thumb_small, cp.thumb_medium as cover_thumb_medium,
                   cp.file_size as cover_file_size, cp.media_type as cover_media_type,
                   cp.width as cover_width, cp.height as cover_height,
                   cp.taken_at as cover_taken_at, cp.is_favorite as cover_is_favorite,
                   cp.uploaded_at as cover_uploaded_at
            FROM persons p
            LEFT JOIN photo_persons pp ON p.id=pp.person_id
            LEFT JOIN photos cp ON cp.id=p.cover_photo_id AND cp.is_deleted=0
            GROUP BY p.id ORDER BY photo_count DESC
        """).fetchall()
        persons = []
        for r in rows:
            cover = None
            if r["cover_id"]:
                cover = {
                    "id": r["cover_id"],
                    "original_name": r["cover_original_name"],
                    "rel_path": r["cover_rel_path"],
                    "thumb_url": f"/api/thumb/{r['cover_thumb_small']}" if r["cover_thumb_small"] else None,
                    "preview_url": f"/api/thumb/{r['cover_thumb_medium']}" if r["cover_thumb_medium"] else None,
                    "photo_url": f"/api/photo/{r['cover_rel_path']}",
                    "file_size": r["cover_file_size"],
                    "file_size_fmt": format_size(r["cover_file_size"]) if r["cover_file_size"] else "",
                    "media_type": r["cover_media_type"],
                    "width": r["cover_width"],
                    "height": r["cover_height"],
                    "taken_at": r["cover_taken_at"],
                    "is_favorite": bool(r["cover_is_favorite"]) if r["cover_is_favorite"] else False,
                    "uploaded_at": r["cover_uploaded_at"],
                }
            persons.append({"id": r["id"], "name": r["name"], "photo_count": r["photo_count"], "cover": cover})
    return jsonify({"persons": persons})


@bp.route("/api/persons", methods=["POST"])
@requires_auth
def create_person():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as conn:
        conn.execute("INSERT INTO persons (name) VALUES (?)", (name,))
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({"id": pid, "name": name})


@bp.route("/api/persons/<int:pid>")
@requires_auth
def get_person(pid):
    with get_db() as conn:
        person = conn.execute("SELECT * FROM persons WHERE id=?", (pid,)).fetchone()
        if not person:
            return jsonify({"error": "not found"}), 404
        photos = conn.execute("""
            SELECT p.* FROM photos p
            JOIN photo_persons pp ON p.id=pp.photo_id
            WHERE pp.person_id=? AND p.is_deleted=0
            ORDER BY p.taken_at DESC
        """, (pid,)).fetchall()
    return jsonify({"id": person["id"], "name": person["name"], "photos": [_photo_info(r) for r in photos]})


@bp.route("/api/persons/<int:pid>", methods=["DELETE"])
@requires_auth
def delete_person(pid):
    with get_db() as conn:
        safe_execute(conn, "DELETE FROM photo_persons WHERE person_id=?", (pid,))
        safe_execute(conn, "DELETE FROM persons WHERE id=?", (pid,))
    return jsonify({"ok": True})


@bp.route("/api/persons/<int:pid>/name", methods=["PUT"])
@requires_auth
def rename_person(pid):
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as conn:
        safe_execute(conn, "UPDATE persons SET name=? WHERE id=?", (name, pid))
    return jsonify({"ok": True})


@bp.route("/api/persons/<int:pid>/photos", methods=["POST"])
@requires_auth
def add_photos_to_person(pid):
    data = request.get_json()
    ids = data.get("photo_ids", [])
    with get_db() as conn:
        for photo_id in ids:
            safe_execute(conn, "INSERT OR IGNORE INTO photo_persons (photo_id, person_id) VALUES (?,?)", (photo_id, pid))
        if ids:
            safe_execute(conn, "UPDATE persons SET cover_photo_id=? WHERE id=?", (ids[0], pid))
    return jsonify({"ok": True, "added": len(ids)})


@bp.route("/api/persons/<int:pid>/photos/<int:photo_id>", methods=["DELETE"])
@requires_auth
def remove_photo_from_person(pid, photo_id):
    with get_db() as conn:
        safe_execute(conn, "DELETE FROM photo_persons WHERE photo_id=? AND person_id=?", (photo_id, pid))
    return jsonify({"ok": True})


