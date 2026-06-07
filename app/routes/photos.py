"""
壹米云相册 - 照片路由
上传、列表、时间线、收藏、删除、下载
"""
import os
import hashlib
import tempfile
import shutil
import threading
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, abort

from config import photos_dir, thumbs_dir, trash_dir, thumb_small, thumb_medium, get as cfg
from database import get_db, safe_execute
from auth import requires_auth
from security import safe_path_join, safe_abs_path
from utils import (
    file_md5, get_photo_date, get_image_dimensions,
    make_thumbnail, make_video_thumbnail, format_size, is_video, media_type,
)

logger = logging.getLogger(__name__)
bp = Blueprint("photos", __name__)


def photo_info(row) -> dict:
    pd = photos_dir()
    original_path = row["original_path"] if "original_path" in row.keys() else None
    rel_path = row["rel_path"]

    if original_path and os.path.isabs(original_path):
        photo_url = f"/api/photo/abs:{original_path}"
        preview_url = f"/api/thumb/abs:{original_path}" if not row["thumb_medium"] else f"/api/thumb/{row['thumb_medium']}"
    else:
        photo_url = f"/api/photo/{rel_path}"
        if row["thumb_medium"]:
            preview_url = f"/api/thumb/{row['thumb_medium']}"
        elif row["thumb_small"]:
            preview_url = f"/api/thumb/{row['thumb_small']}"
        else:
            fname = row["filename"]
            parts = rel_path.split("/")
            ym = "/".join(parts[:2]) if len(parts) >= 2 else "misc"
            preview_url = f"/api/thumb/{ym}/s_{fname}"

    if row["thumb_small"]:
        thumb_url = f"/api/thumb/{row['thumb_small']}"
    else:
        fname = row["filename"]
        parts = rel_path.split("/")
        ym = "/".join(parts[:2]) if len(parts) >= 2 else "misc"
        thumb_url = f"/api/thumb/{ym}/s_{fname}"

    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "rel_path": rel_path,
        "thumb_url": thumb_url,
        "preview_url": preview_url,
        "photo_url": photo_url,
        "file_size": row["file_size"],
        "file_size_fmt": format_size(row["file_size"]) if row["file_size"] else "",
        "media_type": row["media_type"],
        "width": row["width"],
        "height": row["height"],
        "taken_at": row["taken_at"],
        "location": row["location"],
        "is_favorite": bool(row["is_favorite"]),
        "uploaded_at": row["uploaded_at"],
    }


def _gen_thumb_async(photo_id, orig_path, rel_path, mtype):
    try:
        pd = photos_dir()
        base = os.path.splitext(os.path.basename(orig_path))[0]
        parts = rel_path.split("/")
        y, m = parts[0], parts[1] if len(parts) > 1 else "misc"
        tdir = os.path.join(thumbs_dir(), y, m)
        os.makedirs(tdir, exist_ok=True)
        quality = cfg("thumb_quality", 60)

        updates = {}
        gen_func = make_video_thumbnail if mtype == "video" else make_thumbnail
        for prefix, sz in [("s_", thumb_small()), ("m_", thumb_medium())]:
            tp = os.path.join(tdir, f"{prefix}{base}.jpg")
            if mtype == "video":
                ok = make_video_thumbnail(orig_path, tp, sz)
            else:
                ok = make_thumbnail(orig_path, tp, sz, quality)
            if ok:
                col = "thumb_small" if prefix == "s_" else "thumb_medium"
                updates[col] = os.path.relpath(tp, pd)

        if updates:
            with get_db() as conn:
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE photos SET {sets} WHERE id=?", list(updates.values()) + [photo_id])
            logger.debug("缩略图生成完成: photo %d", photo_id)
    except Exception as e:
        logger.error("缩略图生成失败 photo %d: %s", photo_id, e)


# ============ 上传（流式处理，不全量读入内存）============
@bp.route("/api/upload", methods=["POST"])
@requires_auth
def upload():
    if "photos" not in request.files:
        return jsonify({"error": "没有文件"}), 400

    files = request.files.getlist("photos")
    results = []
    thumb_tasks = []
    allowed = cfg("allowed_extensions", "")
    if isinstance(allowed, str):
        allowed = set(allowed.split(","))
    else:
        allowed = set(allowed)

    with get_db() as conn:
        for f in files:
            if not f.filename:
                continue

            oname = f.filename
            ext = oname.rsplit(".", 1)[-1].lower() if "." in oname else ""

            if ext not in allowed:
                results.append({"name": oname, "status": "skipped"})
                continue

            # 流式写入临时文件 + 流式 hash（不读入内存）
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix="." + ext)
            try:
                h = hashlib.md5()
                size = 0
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
                tmp.close()
                fh = h.hexdigest()

            # 检查重复
            dup = safe_execute(conn, "SELECT id FROM photos WHERE file_hash=? AND is_deleted=0", (fh,)).fetchone()
            if dup:
                os.unlink(tmp.name)
                results.append({"name": oname, "status": "duplicate"})
                continue

            # 获取拍摄日期
            taken = get_photo_date(tmp.name)
            y = taken.strftime("%Y")
            m = taken.strftime("%m")
            ddir = taken.strftime("%Y-%m-%d")
            sdir = os.path.join(photos_dir(), y, m, ddir)
            os.makedirs(sdir, exist_ok=True)

            ts = taken.strftime("%H%M%S")
            sname = f"{ts}_{oname}"
            sp = os.path.join(sdir, sname)
            c = 1
            while os.path.exists(sp):
                ne, ee = os.path.splitext(sname)
                sp = os.path.join(sdir, f"{ne}_{c}{ee}")
                c += 1

            rp = os.path.relpath(sp, photos_dir())
            rp_c = 1
            while safe_execute(conn, "SELECT id FROM photos WHERE rel_path=?", (rp,)).fetchone():
                ne, ee = os.path.splitext(sname)
                sp = os.path.join(sdir, f"{ne}_{rp_c}{ee}")
                rp = os.path.relpath(sp, photos_dir())
                rp_c += 1
            sname = os.path.basename(sp)

            # 移动临时文件到目标位置
                shutil.move(tmp.name, sp)
            except Exception:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                raise

            mt = media_type(ext)
            w = h_dim = None
            if mt == "photo":
                dims = get_image_dimensions(sp)
                if dims:
                    w, h_dim = dims

            safe_execute(conn, """INSERT INTO photos
                (filename, original_name, rel_path, thumb_small, thumb_medium,
                 file_size, file_hash, media_type, width, height, taken_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (sname, oname, rp, None, None, size, fh, mt, w, h_dim, taken.isoformat()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            results.append({"name": oname, "status": "ok", "path": rp})
            thumb_tasks.append((pid, sp, rp, mt))

    for pid, sp, rp, mt in thumb_tasks:
        t = threading.Thread(target=_gen_thumb_async, args=(pid, sp, rp, mt), daemon=False)
        t.start()

    return jsonify({"results": results, "total": len(results)})


# ============ 照片列表 ============
@bp.route("/api/photos")
@requires_auth
def list_photos():
    pg = max(1, int(request.args.get("page", 1)))
    pp = min(200, max(1, int(request.args.get("per_page", 60))))
    mt = request.args.get("type", "")
    yr = request.args.get("year", "")
    mo = request.args.get("month", "")
    q = request.args.get("search", "")
    fav = request.args.get("favorite", "")
    off = (pg - 1) * pp

    wh = ["is_deleted=0"]
    pa = []
    if mt:
        wh.append("media_type=?"); pa.append(mt)
    if yr:
        wh.append("taken_at LIKE ?"); pa.append(yr + "%")
    if mo and yr:
        wh.append("taken_at LIKE ?"); pa.append(f"{yr}-{mo}%")
    if q:
        wh.append("(original_name LIKE ? OR location LIKE ?)"); pa.extend([f"%{q}%", f"%{q}%"])
    if fav == "1":
        wh.append("is_favorite=1")

    wc = "WHERE " + " AND ".join(wh)
    with get_db(write=False) as conn:
        tot = conn.execute(f"SELECT COUNT(*) FROM photos {wc}", pa).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM photos {wc} ORDER BY taken_at DESC LIMIT ? OFFSET ?",
            pa + [pp, off]
        ).fetchall()

    return jsonify({
        "photos": [photo_info(r) for r in rows],
        "total": tot, "page": pg, "per_page": pp,
        "pages": (tot + pp - 1) // pp,
    })


# ============ 时间线 ============
@bp.route("/api/timeline")
@requires_auth
def timeline():
    yr = request.args.get("year", "")
    wh = ["is_deleted=0"]
    pa = []
    if yr:
        wh.append("taken_at LIKE ?"); pa.append(yr + "%")
    wc = "WHERE " + " AND ".join(wh)

    with get_db(write=False) as conn:
        rows = conn.execute(f"""
            WITH daily AS (
                SELECT DATE(taken_at) as date, COUNT(*) as count, MIN(id) as cover_id
                FROM photos {wc} GROUP BY DATE(taken_at) ORDER BY date DESC
            )
            SELECT d.date, d.count, d.cover_id,
                   p.filename, p.original_name, p.rel_path,
                   p.thumb_small, p.thumb_medium, p.file_size,
                   p.media_type, p.width, p.height, p.taken_at, p.original_path
            FROM daily d LEFT JOIN photos p ON p.id = d.cover_id
        """, pa).fetchall()

        timeline_data = []
        for r in rows:
            if not r["date"]:
                continue
            cover = None
            if r["cover_id"]:
                cover = {
                    "id": r["cover_id"],
                    "thumb_url": f"/api/thumb/{r['thumb_small']}" if r["thumb_small"] else None,
                    "preview_url": f"/api/thumb/{r['thumb_medium']}" if r["thumb_medium"] else f"/api/photo/{r['rel_path']}",
                    "photo_url": f"/api/photo/{r['rel_path']}",
                    "media_type": r["media_type"],
                }
            timeline_data.append({"date": r["date"], "count": r["count"], "cover": cover})

        years = conn.execute("""
            SELECT DISTINCT SUBSTR(taken_at, 1, 4) as year, COUNT(*) as count
            FROM photos WHERE is_deleted=0 GROUP BY year ORDER BY year DESC
        """).fetchall()

    return jsonify({
        "timeline": timeline_data,
        "years": [{"year": r["year"], "count": r["count"]} for r in years if r["year"]],
    })


@bp.route("/api/timeline/<date>")
@requires_auth
def timeline_date(date):
    with get_db(write=False) as conn:
        rows = conn.execute(
            "SELECT * FROM photos WHERE DATE(taken_at)=? AND is_deleted=0 ORDER BY taken_at DESC",
            (date,)
        ).fetchall()
    return jsonify({"date": date, "photos": [photo_info(r) for r in rows]})


# ============ 照片详情 ============
@bp.route("/api/photo/<int:photo_id>")
@requires_auth
def get_photo(photo_id):
    with get_db(write=False) as conn:
        row = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        tags = conn.execute(
            "SELECT t.name FROM tags t JOIN photo_tags pt ON t.id=pt.tag_id WHERE pt.photo_id=?",
            (photo_id,)
        ).fetchall()
        persons = conn.execute(
            "SELECT p.id, p.name FROM persons p JOIN photo_persons pp ON p.id=pp.person_id WHERE pp.photo_id=?",
            (photo_id,)
        ).fetchall()

    info = photo_info(row)
    info["tags"] = [t["name"] for t in tags]
    info["persons"] = [{"id": p["id"], "name": p["name"]} for p in persons]
    return jsonify(info)


# ============ 照片文件服务 ============
@bp.route("/api/photo/<path:filepath>")
@requires_auth
def serve_photo(filepath):
    pd = photos_dir()
    if filepath.startswith("abs:"):
        real = safe_abs_path(filepath)
        if not real:
            abort(403)
        full = real
    else:
        full = safe_path_join(pd, filepath)
        if not full:
            abort(403)
    if not os.path.isfile(full):
        abort(404)
    return send_file(full)


# ============ 缩略图服务 ============
@bp.route("/api/thumb/<path:filepath>")
@requires_auth
def serve_thumb(filepath):
    pd = photos_dir()
    if filepath.startswith("abs:"):
        original = safe_abs_path(filepath)
        if not original or not os.path.isfile(original):
            abort(404)
        h = hashlib.md5(original.encode()).hexdigest()[:12]
        td = os.path.join(thumbs_dir(), "external")
        os.makedirs(td, exist_ok=True)
        tp = os.path.join(td, f"m_{h}.jpg")
        if not os.path.isfile(tp):
            ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
            if is_video(ext):
                make_video_thumbnail(original, tp, thumb_medium())
            else:
                make_thumbnail(original, tp, thumb_medium(), cfg("thumb_quality", 60))
        if os.path.isfile(tp):
            return send_file(tp, max_age=86400)
        abort(404)
    else:
        full = safe_path_join(pd, filepath)
        if not full:
            abort(403)
        if os.path.isfile(full):
            return send_file(full, max_age=86400)

        # 自动生成缩略图
        fname = os.path.basename(filepath)
        is_thumb = fname.startswith("s_") or fname.startswith("m_")
        if is_thumb:
            orig_fname = fname[2:]
            sz = thumb_small() if fname.startswith("s_") else thumb_medium()
            with get_db(write=False) as conn:
                row = conn.execute(
                    "SELECT rel_path, original_path, media_type FROM photos WHERE is_deleted=0 AND (filename=? OR filename LIKE ?)",
                    (orig_fname, orig_fname.rsplit(".", 1)[0] + "%")
                ).fetchone()
            if row:
                if row["original_path"] and os.path.isabs(row["original_path"]):
                    orig_path = row["original_path"]
                else:
                    orig_path = os.path.join(pd, row["rel_path"])
                if os.path.isfile(orig_path):
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    ok = (make_video_thumbnail if row["media_type"] == "video" else make_thumbnail)(
                        orig_path, full, sz, cfg("thumb_quality", 60)
                    )
                    if ok and os.path.isfile(full):
                        return send_file(full, max_age=86400)
        abort(404)


# ============ 收藏 ============
@bp.route("/api/photo/<int:photo_id>/favorite", methods=["POST"])
@requires_auth
def toggle_favorite(photo_id):
    with get_db() as conn:
        row = conn.execute("SELECT is_favorite FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        new_val = 0 if row["is_favorite"] else 1
        safe_execute(conn, "UPDATE photos SET is_favorite=? WHERE id=?", (new_val, photo_id))
    return jsonify({"ok": True, "is_favorite": bool(new_val)})


# ============ 删除 ============
@bp.route("/api/photo/<int:photo_id>", methods=["DELETE"])
@requires_auth
def delete_photo(photo_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        src = os.path.join(photos_dir(), row["rel_path"])
        if os.path.isfile(src):
            shutil.move(src, os.path.join(trash_dir(), row["filename"]))
        for col in ("thumb_small", "thumb_medium"):
            if row[col]:
                tp = os.path.join(photos_dir(), row[col])
                if os.path.isfile(tp):
                    os.remove(tp)
        safe_execute(conn, "UPDATE photos SET is_deleted=1, deleted_at=? WHERE id=?",
                     (datetime.now().isoformat(), photo_id))
    return jsonify({"ok": True})


# ============ 恢复 ============
@bp.route("/api/photo/<int:photo_id>/restore", methods=["POST"])
@requires_auth
def restore_photo(photo_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM photos WHERE id=? AND is_deleted=1", (photo_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        tp = os.path.join(trash_dir(), row["filename"])
        dst = os.path.join(photos_dir(), row["rel_path"])
        if os.path.isfile(tp):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(tp, dst)
        if row["media_type"] == "photo" and os.path.isfile(dst):
            base = os.path.splitext(row["filename"])[0]
            y, m = row["taken_at"][:4], row["taken_at"][5:7]
            tdir = os.path.join(thumbs_dir(), y, m)
            os.makedirs(tdir, exist_ok=True)
            ts_rel = tm_rel = None
            tsp = os.path.join(tdir, f"s_{base}.jpg")
            tmp2 = os.path.join(tdir, f"m_{base}.jpg")
            if make_thumbnail(dst, tsp, thumb_small(), cfg("thumb_quality", 60)):
                ts_rel = os.path.relpath(tsp, photos_dir())
            if make_thumbnail(dst, tmp2, thumb_medium(), cfg("thumb_quality", 60)):
                tm_rel = os.path.relpath(tmp2, photos_dir())
            safe_execute(conn, "UPDATE photos SET thumb_small=?, thumb_medium=?, is_deleted=0, deleted_at=NULL WHERE id=?",
                         (ts_rel, tm_rel, photo_id))
        else:
            safe_execute(conn, "UPDATE photos SET is_deleted=0, deleted_at=NULL WHERE id=?", (photo_id,))
    return jsonify({"ok": True})


# ============ 回收站 ============
@bp.route("/api/trash")
@requires_auth
def list_trash():
    with get_db(write=False) as conn:
        rows = conn.execute("SELECT * FROM photos WHERE is_deleted=1 ORDER BY deleted_at DESC").fetchall()
    return jsonify({"photos": [photo_info(r) for r in rows], "total": len(rows)})


@bp.route("/api/trash/empty", methods=["POST"])
@requires_auth
def empty_trash():
    with get_db() as conn:
        rows = conn.execute("SELECT filename FROM photos WHERE is_deleted=1").fetchall()
        for r in rows:
            tp = os.path.join(trash_dir(), r["filename"])
            if os.path.isfile(tp):
                os.remove(tp)
        safe_execute(conn, "DELETE FROM photos WHERE is_deleted=1")
    return jsonify({"ok": True, "deleted": len(rows)})


@bp.route("/api/trash/<int:photo_id>", methods=["DELETE"])
@requires_auth
def permanent_delete(photo_id):
    with get_db() as conn:
        row = conn.execute("SELECT filename FROM photos WHERE id=? AND is_deleted=1", (photo_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        tp = os.path.join(trash_dir(), row["filename"])
        if os.path.isfile(tp):
            os.remove(tp)
        safe_execute(conn, "DELETE FROM photos WHERE id=?", (photo_id,))
    return jsonify({"ok": True})


# ============ 下载 ============
@bp.route("/api/download/<int:photo_id>")
@requires_auth
def download_photo(photo_id):
    with get_db(write=False) as conn:
        row = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row:
        abort(404)
    full = os.path.join(trash_dir() if row["is_deleted"] else photos_dir(), row["filename"] if row["is_deleted"] else row["rel_path"])
    if not os.path.isfile(full):
        abort(404)
    return send_file(full, as_attachment=True, download_name=row["original_name"])


# ============ 批量操作 ============
@bp.route("/api/batch/favorite", methods=["POST"])
@requires_auth
def batch_favorite():
    data = request.get_json()
    ids = data.get("photo_ids", [])
    fav = data.get("favorite", True)
    with get_db() as conn:
        for pid in ids:
            safe_execute(conn, "UPDATE photos SET is_favorite=? WHERE id=?", (1 if fav else 0, pid))
    return jsonify({"ok": True, "updated": len(ids)})


@bp.route("/api/batch/delete", methods=["POST"])
@requires_auth
def batch_delete():
    data = request.get_json()
    ids = data.get("photo_ids", [])
    count = 0
    with get_db() as conn:
        for pid in ids:
            row = conn.execute("SELECT * FROM photos WHERE id=? AND is_deleted=0", (pid,)).fetchone()
            if not row:
                continue
            src = os.path.join(photos_dir(), row["rel_path"])
            if os.path.isfile(src):
                shutil.move(src, os.path.join(trash_dir(), row["filename"]))
            for col in ("thumb_small", "thumb_medium"):
                if row[col]:
                    tp = os.path.join(photos_dir(), row[col])
                    if os.path.isfile(tp):
                        os.remove(tp)
            safe_execute(conn, "UPDATE photos SET is_deleted=1, deleted_at=? WHERE id=?",
                         (datetime.now().isoformat(), pid))
            count += 1
    return jsonify({"ok": True, "deleted": count})


@bp.route("/api/batch/album", methods=["POST"])
@requires_auth
def batch_add_to_album():
    data = request.get_json()
    aid = data.get("album_id")
    ids = data.get("photo_ids", [])
    if not aid:
        return jsonify({"error": "album_id required"}), 400
    with get_db() as conn:
        for pid in ids:
            safe_execute(conn, "INSERT OR IGNORE INTO album_photos (album_id, photo_id) VALUES (?,?)", (aid, pid))
    return jsonify({"ok": True, "added": len(ids)})


@bp.route("/api/batch/person", methods=["POST"])
@requires_auth
def batch_add_to_person():
    data = request.get_json()
    person_id = data.get("person_id")
    ids = data.get("photo_ids", [])
    if not person_id:
        return jsonify({"error": "person_id required"}), 400
    with get_db() as conn:
        for pid in ids:
            safe_execute(conn, "INSERT OR IGNORE INTO photo_persons (photo_id, person_id) VALUES (?,?)", (pid, person_id))
        if ids:
            safe_execute(conn, "UPDATE persons SET cover_photo_id=? WHERE id=?", (ids[0], person_id))
    return jsonify({"ok": True, "added": len(ids)})


# ============ 统计（30秒缓存）============
_stats_cache = {"data": None, "ts": 0}

@bp.route("/api/stats")
@requires_auth
def stats():
    import time
    now = time.time()
    if _stats_cache["data"] and now - _stats_cache["ts"] < 30:
        return jsonify(_stats_cache["data"])

    with get_db(write=False) as conn:
        row = conn.execute("""
            SELECT COUNT(*) as total,
                SUM(CASE WHEN media_type='photo' THEN 1 ELSE 0 END) as photos,
                SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END) as videos,
                COALESCE(SUM(file_size), 0) as total_size,
                SUM(CASE WHEN is_favorite=1 THEN 1 ELSE 0 END) as favorites
            FROM photos WHERE is_deleted=0
        """).fetchone()
        trash = conn.execute("SELECT COUNT(*) FROM photos WHERE is_deleted=1").fetchone()[0]
        persons = conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
        albums = conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
        years = conn.execute("""
            SELECT DISTINCT SUBSTR(taken_at,1,4) as y, COUNT(*) as cnt
            FROM photos WHERE is_deleted=0 GROUP BY y ORDER BY y DESC
        """).fetchall()

    result = {
        "total": row["total"], "photos": row["photos"], "videos": row["videos"],
        "total_size": format_size(row["total_size"]), "total_size_bytes": row["total_size"],
        "favorites": row["favorites"], "trash": trash, "persons": persons, "albums": albums,
        "years": [{"year": r["y"], "count": r["cnt"]} for r in years if r["y"]],
    }
    _stats_cache["data"] = result
    _stats_cache["ts"] = now
    return jsonify(result)


# ============ Hash 检查 ============
@bp.route("/api/check-hash", methods=["POST"])
@requires_auth
def check_hash():
    data = request.get_json()
    hashes = data.get("hashes", [])
    if not hashes:
        return jsonify({"existing": []})
    with get_db(write=False) as conn:
        placeholders = ",".join("?" * len(hashes))
        rows = conn.execute(
            f"SELECT file_hash FROM photos WHERE file_hash IN ({placeholders}) AND is_deleted=0",
            hashes
        ).fetchall()
    return jsonify({"existing": [r["file_hash"] for r in rows]})


# ============ 搜索 ============
@bp.route("/api/search")
@requires_auth
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"photos": [], "persons": [], "albums": [], "tags": []})
    pattern = f"%{q}%"
    with get_db(write=False) as conn:
        photos = conn.execute(
            "SELECT * FROM photos WHERE is_deleted=0 AND (original_name LIKE ? OR location LIKE ?) ORDER BY taken_at DESC LIMIT 50",
            (pattern, pattern)
        ).fetchall()
        persons = conn.execute(
            "SELECT p.*, COUNT(pp.photo_id) as photo_count FROM persons p LEFT JOIN photo_persons pp ON p.id=pp.person_id WHERE p.name LIKE ? GROUP BY p.id",
            (pattern,)
        ).fetchall()
        albums = conn.execute(
            "SELECT a.*, COUNT(ap.photo_id) as photo_count FROM albums a LEFT JOIN album_photos ap ON a.id=ap.album_id WHERE a.name LIKE ? OR a.description LIKE ? GROUP BY a.id",
            (pattern, pattern)
        ).fetchall()
        tags = conn.execute(
            "SELECT t.*, COUNT(pt.photo_id) as photo_count FROM tags t LEFT JOIN photo_tags pt ON t.id=pt.tag_id WHERE t.name LIKE ? GROUP BY t.id",
            (pattern,)
        ).fetchall()
    return jsonify({
        "photos": [photo_info(r) for r in photos],
        "persons": [{"id": r["id"], "name": r["name"], "photo_count": r["photo_count"]} for r in persons],
        "albums": [{"id": r["id"], "name": r["name"], "photo_count": r["photo_count"]} for r in albums],
        "tags": [{"id": r["id"], "name": r["name"], "photo_count": r["photo_count"]} for r in tags],
    })


# ============ 缩略图批量生成 ============
@bp.route("/api/generate-thumbs", methods=["POST"])
@requires_auth
def generate_thumbs():
    with get_db(write=False) as conn:
        rows = conn.execute(
            "SELECT id, rel_path, thumb_small, thumb_medium, media_type, original_path "
            "FROM photos WHERE is_deleted=0 AND (thumb_small IS NULL OR thumb_medium IS NULL)"
        ).fetchall()

    pd = photos_dir()
    generated = errors = 0
    quality = cfg("thumb_quality", 60)

    for r in rows:
        orig = r["original_path"] if r["original_path"] and os.path.isabs(r["original_path"]) else os.path.join(pd, r["rel_path"])
        if not os.path.isfile(orig):
            errors += 1
            continue
        is_vid = r["media_type"] == "video"
        base = os.path.splitext(os.path.basename(orig))[0]
        rp_parts = r["rel_path"].split("/")
        y, m = rp_parts[0], rp_parts[1] if len(rp_parts) > 1 else "misc"
        tdir = os.path.join(thumbs_dir(), y, m)
        os.makedirs(tdir, exist_ok=True)

        updates = {}
        if not r["thumb_small"]:
            tsp = os.path.join(tdir, f"s_{base}.jpg")
            ok = (make_video_thumbnail if is_vid else make_thumbnail)(orig, tsp, thumb_small(), quality)
            if ok:
                updates["thumb_small"] = os.path.relpath(tsp, pd)
        if not r["thumb_medium"]:
            tmp = os.path.join(tdir, f"m_{base}.jpg")
            ok = (make_video_thumbnail if is_vid else make_thumbnail)(orig, tmp, thumb_medium(), quality)
            if ok:
                updates["thumb_medium"] = os.path.relpath(tmp, pd)

        if updates:
            with get_db() as conn:
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE photos SET {sets} WHERE id=?", list(updates.values()) + [r["id"]])
            generated += 1
        else:
            errors += 1

    return jsonify({"generated": generated, "errors": errors, "total": len(rows)})

