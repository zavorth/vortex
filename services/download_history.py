"""Download history persistence."""

import os
import json
import time
from threading import Lock

HISTORY_FILE = os.path.join(os.getcwd(), 'download_history.json')
MAX_HISTORY = 100
history_lock = Lock()


def _load_history():
    """Load history from disk."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(history):
    """Save history to disk."""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def add_download_record(title, files, download_dir, status='completed', error=''):
    """Add a download record to history."""
    with history_lock:
        history = _load_history()
        record = {
            'id': int(time.time() * 1000),
            'title': title,
            'files': files,
            'download_dir': download_dir,
            'status': status,
            'error': error,
            'timestamp': time.time(),
            'date': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        history.insert(0, record)
        history = history[:MAX_HISTORY]
        _save_history(history)
        return record


def update_download_record(record_id, status='completed', error='', downloaded_files=0):
    """Update an existing download record."""
    with history_lock:
        history = _load_history()
        for record in history:
            if record['id'] == record_id:
                record['status'] = status
                record['error'] = error
                record['downloaded_files'] = downloaded_files
                record['end_time'] = time.time()
                break
        _save_history(history)


def get_history(limit=20):
    """Get recent download history."""
    history = _load_history()
    return history[:limit]


def clear_history():
    """Clear all download history."""
    with history_lock:
        _save_history([])
