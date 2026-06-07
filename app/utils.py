"""
壹米云相册 - 工具函数
文件处理、缩略图生成、EXIF 读取
"""
import os
import hashlib
import subprocess
import logging
from datetime import datetime

from PIL import Image
from PIL.ExifTags import TAGS

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

logger = logging.getLogger(__name__)


def file_md5(filepath: str, chunk_size: int = 65536) -> str:
    """流式计算文件 MD5（不读入内存）"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_md5_fast(filepath: str) -> str:
    """
    大文件快速哈希（首尾各 64KB + 文件大小）
    用于去重检查，不是加密级哈希
    """
    size = os.path.getsize(filepath)
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        h.update(f.read(65536))
        if size > 65536:
            f.seek(max(0, size - 65536))
            h.update(f.read(65536))
    h.update(str(size).encode())
    return h.hexdigest()


def file_md5_from_data(data: bytes) -> str:
    """计算内存数据的 MD5（小文件上传用）"""
    return hashlib.md5(data).hexdigest()


def get_exif_date(filepath: str):
    """从 EXIF 读取拍摄日期"""
    try:
        img = Image.open(filepath)
        exif = img._getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in ('DateTimeOriginal', 'DateTime'):
                    try:
                        return datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                    except (ValueError, TypeError):
                        continue
    except Exception:
        pass
    return None


def get_photo_date(filepath: str, fallback_mtime: bool = True):
    """
    获取照片日期，优先级:
    1. EXIF DateTimeOriginal
    2. 文件修改时间
    3. 当前时间
    """
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if ext in ("jpg", "jpeg", "tiff", "heic", "heif", "png", "webp"):
        dt = get_exif_date(filepath)
        if dt:
            return dt
    if fallback_mtime:
        try:
            return datetime.fromtimestamp(os.path.getmtime(filepath))
        except Exception:
            pass
    return datetime.now()


def get_image_dimensions(filepath: str):
    """获取图片尺寸"""
    try:
        img = Image.open(filepath)
        return img.size
    except Exception:
        return None, None


def make_thumbnail(src_path: str, thumb_path: str, size: tuple, quality: int = 60) -> bool:
    """生成图片缩略图"""
    try:
        img = Image.open(src_path)
        img.thumbnail(size, Image.LANCZOS)
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
        img.save(thumb_path, "JPEG", quality=quality, optimize=True)
        return True
    except Exception as e:
        logger.debug("缩略图生成失败 %s: %s", src_path, e)
        return False


def make_video_thumbnail(video_path: str, thumb_path: str, size: tuple = (200, 200)) -> bool:
    """用 ffmpeg 生成视频缩略图"""
    try:
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
        result = subprocess.run(
            ["ffmpeg", "-i", video_path, "-ss", "00:00:01", "-vframes", "1",
             "-vf", f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease",
             "-y", thumb_path],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and os.path.isfile(thumb_path):
            return True
    except Exception as e:
        logger.debug("视频缩略图失败 %s: %s", video_path, e)
    return False


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if not size_bytes:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def is_video(ext: str) -> bool:
    return ext.lower() in ("mp4", "mov", "avi", "mkv", "webm", "3gp")


def is_photo(ext: str) -> bool:
    return ext.lower() in ("jpg", "jpeg", "png", "gif", "heic", "heif", "bmp", "tiff", "webp")


def media_type(ext: str) -> str:
    return "video" if is_video(ext) else "photo"
