"""
壹米云相册 - 配置管理
支持环境变量 + 配置文件 + 首次安装向导
多进程安全：自动检测配置文件变更并重载
"""
import os
import json
import secrets
import threading
import logging

__version__ = "2.1.2"

logger = logging.getLogger(__name__)

DEFAULTS = {
    "photos_dir": "/data/photos",
    "port": 8080,
    "max_upload_mb": 500,
    "allowed_extensions": "jpg,jpeg,png,gif,heic,heif,bmp,tiff,webp,mp4,mov,avi,mkv,webm,3gp",
    "thumb_small_w": 200,
    "thumb_small_h": 200,
    "thumb_medium_w": 800,
    "thumb_medium_h": 800,
    "thumb_quality": 60,
    "db_max_connections": 10,
    "db_busy_timeout": 10000,
    "max_scan_depth": 3,
    "rate_limit_per_minute": 30,
}

ALLOWED_BROWSE_ROOTS = ["/mnt", "/data", "/media", "/home", "/opt"]

_config = {}
_initialized = False
_config_mtime = 0.0
_lock = threading.Lock()


def _config_path() -> str:
    pd = _config.get("photos_dir", DEFAULTS["photos_dir"])
    return os.path.join(pd, ".config", "settings.json")


def _load_file() -> tuple[dict, float]:
    """加载配置文件，返回 (config_dict, mtime)"""
    path = _config_path()
    if os.path.exists(path):
        try:
            mtime = os.path.getmtime(path)
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), mtime
        except Exception as e:
            logger.warning("配置文件读取失败: %s", e)
    return {}, 0.0


def _save_file():
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_config, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _check_reload():
    """检查配置文件是否被其他进程修改，如果是则重载"""
    global _config, _config_mtime
    path = _config_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return
    if mtime > _config_mtime:
        with _lock:
            # 双重检查
            try:
                mtime2 = os.path.getmtime(path)
            except OSError:
                return
            if mtime2 > _config_mtime:
                file_cfg, _ = _load_file()
                if file_cfg:
                    _config.update(file_cfg)
                    _config_mtime = mtime2
                    logger.debug("配置文件已重载")


def init_config(force=False):
    global _config, _initialized, _config_mtime
    if _initialized and not force:
        return _config

    _config = dict(DEFAULTS)
    file_cfg, mtime = _load_file()
    _config.update(file_cfg)
    _config_mtime = mtime

    env_map = {
        "YIMI_DATA_DIR": ("photos_dir", str),
        "PORT": ("port", int),
        "MAX_UPLOAD_MB": ("max_upload_mb", int),
        "ALLOWED_EXTENSIONS": ("allowed_extensions", str),
        "YIMI_PASSWORD": ("password", str),
    }
    for env_key, (cfg_key, typ) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            _config[cfg_key] = typ(val)

    if "password" not in _config:
        _config["password"] = secrets.token_urlsafe(12)
        _config["password_is_default"] = True
        _save_file()
        _config_mtime = os.path.getmtime(_config_path())
        logger.warning("=" * 50)
        logger.warning("首次启动！默认密码: %s", _config["password"])
        logger.warning("请尽快在设置页面修改密码！")
        logger.warning("=" * 50)
    elif not file_cfg:
        _save_file()
        _config_mtime = os.path.getmtime(_config_path())

    pd = _config["photos_dir"]
    for sub in ("", ".thumbs", ".trash", ".faces", ".config"):
        os.makedirs(os.path.join(pd, sub), exist_ok=True)

    _initialized = True
    return _config


def get(key: str, default=None):
    if not _initialized:
        init_config()
    _check_reload()
    return _config.get(key, default)


def set_config(key: str, value):
    if not _initialized:
        init_config()
    _config[key] = value
    _save_file()
    global _config_mtime
    try:
        _config_mtime = os.path.getmtime(_config_path())
    except OSError:
        pass
    return value


def get_all() -> dict:
    if not _initialized:
        init_config()
    _check_reload()
    safe = dict(_config)
    for k in ("password", "token_secret"):
        if k in safe:
            safe[k] = "***"
    return safe


def is_first_run() -> bool:
    return get("password_is_default", False)


def photos_dir() -> str:
    return get("photos_dir", DEFAULTS["photos_dir"])

def thumbs_dir() -> str:
    return os.path.join(photos_dir(), ".thumbs")

def trash_dir() -> str:
    return os.path.join(photos_dir(), ".trash")

def faces_dir() -> str:
    return os.path.join(photos_dir(), ".faces")

def db_path() -> str:
    return os.path.join(photos_dir(), ".photo_index.db")

def allowed_exts() -> set:
    raw = get("allowed_extensions", DEFAULTS["allowed_extensions"])
    return set(raw.split(",")) if isinstance(raw, str) else set(raw)

def thumb_small() -> tuple:
    return (get("thumb_small_w", 200), get("thumb_small_h", 200))

def thumb_medium() -> tuple:
    return (get("thumb_medium_w", 800), get("thumb_medium_h", 800))
