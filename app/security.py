"""
壹米云相册 - 安全模块
路径遍历防护 + 文件系统访问控制
"""
import os
import logging

logger = logging.getLogger(__name__)

_BLOCKED_PATHS = ["/etc", "/proc", "/sys", "/dev", "/root", "/var/log"]

def _get_allowed_prefixes():
    from config import ALLOWED_BROWSE_ROOTS
    return ALLOWED_BROWSE_ROOTS

def is_safe_path(path: str, base_dir: str = None) -> bool:
    try:
        resolved = os.path.realpath(os.path.abspath(path))
    except (OSError, ValueError):
        return False
    for blocked in _BLOCKED_PATHS:
        if resolved.startswith(blocked + os.sep) or resolved == blocked:
            logger.warning("安全拦截: 黑名单路径 %s", resolved)
            return False
    if base_dir:
        base_resolved = os.path.realpath(os.path.abspath(base_dir))
        if not resolved.startswith(base_resolved + os.sep) and resolved != base_resolved:
            return False
        return True
    for prefix in _get_allowed_prefixes():
        if resolved.startswith(prefix + os.sep) or resolved == prefix:
            return True
    logger.warning("安全拦截: 路径 %s 不在白名单中", resolved)
    return False

def safe_path_join(base: str, *parts: str):
    joined = os.path.join(base, *parts)
    resolved = os.path.realpath(joined)
    base_resolved = os.path.realpath(base)
    if not (resolved.startswith(base_resolved + os.sep) or resolved == base_resolved):
        logger.warning("路径遍历拦截: %s -> %s", parts, resolved)
        return None
    return resolved

def safe_abs_path(filepath: str):
    real_path = filepath[4:] if filepath.startswith("abs:") else filepath
    real_path = os.path.expanduser(real_path)
    if is_safe_path(real_path):
        return os.path.realpath(real_path)
    return None

def safe_browse_path(path: str):
    if not path:
        return None, "路径不能为空"
    resolved = os.path.realpath(os.path.abspath(path))
    for blocked in _BLOCKED_PATHS:
        if resolved.startswith(blocked + os.sep) or resolved == blocked:
            return None, f"不允许访问系统目录: {blocked}"
    for prefix in _get_allowed_prefixes():
        if resolved.startswith(prefix + os.sep) or resolved == prefix:
            if not os.path.exists(resolved):
                return None, "路径不存在"
            return resolved, None
    return None, "路径不在允许的目录范围内"
