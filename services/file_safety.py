"""Path and cookie file safety validations."""

import os

COOKIES_DIR_NAME = "saved_cookies"
MAX_COOKIE_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def is_safe_cookie_path(cookies_path, project_root=None):
    """
    Validate a cookie file path.
    Only allows .txt files inside the project's saved_cookies/ directory.
    Rejects absolute paths from frontend, traversal attempts, and oversized files.
    """
    if not cookies_path:
        return True

    if project_root is None:
        project_root = os.getcwd()

    # Reject absolute paths from frontend (they should use cookie_id instead)
    if os.path.isabs(cookies_path):
        return False

    # Normalize and prevent traversal
    norm_path = os.path.normpath(cookies_path)
    if norm_path.startswith('..') or os.path.isabs(norm_path):
        return False

    # Must be a .txt file
    if not norm_path.endswith('.txt'):
        return False

    # Resolve within project's saved_cookies/
    cookies_dir = os.path.join(project_root, COOKIES_DIR_NAME)
    full_path = os.path.abspath(os.path.join(cookies_dir, norm_path))

    # Ensure resolved path stays within cookies_dir
    cookies_dir_abs = os.path.abspath(cookies_dir)
    if not (full_path == cookies_dir_abs or full_path.startswith(cookies_dir_abs + os.sep)):
        return False

    # File must exist
    if not os.path.isfile(full_path):
        return False

    # Size check
    try:
        if os.path.getsize(full_path) > MAX_COOKIE_FILE_SIZE:
            return False
    except OSError:
        return False

    return True


def resolve_cookie_path(cookie_id, project_root=None):
    """
    Resolve a cookie_id (filename only) to a full path inside saved_cookies/.
    Returns None if the file doesn't exist or isn't safe.
    """
    if not cookie_id:
        return None

    if project_root is None:
        project_root = os.getcwd()

    if os.path.isabs(cookie_id):
        return None

    norm_id = os.path.normpath(cookie_id)
    if norm_id.startswith('..') or os.path.isabs(norm_id) or '/' in norm_id or '\\' in norm_id:
        return None

    if not norm_id.endswith('.txt'):
        return None

    cookies_dir = os.path.join(project_root, COOKIES_DIR_NAME)
    full_path = os.path.abspath(os.path.join(cookies_dir, norm_id))

    cookies_dir_abs = os.path.abspath(cookies_dir)
    if not (full_path == cookies_dir_abs or full_path.startswith(cookies_dir_abs + os.sep)):
        return None

    if not os.path.isfile(full_path):
        return None

    return full_path


def is_safe_path(filepath, allowed_dirs):
    """Enforces absolute path boundary checking to prevent directory traversal."""
    if not filepath:
        return False
    try:
        filepath_norm = os.path.abspath(os.path.normpath(filepath)).lower()
        for directory in allowed_dirs:
            dir_norm = os.path.abspath(os.path.normpath(directory)).lower()
            dir_boundary = dir_norm if dir_norm.endswith(os.sep) else dir_norm + os.sep
            if filepath_norm == dir_norm or filepath_norm.startswith(dir_boundary):
                return True
    except Exception:
        pass
    return False
