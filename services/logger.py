"""Structured logging for Vortex."""

import os
import sys
from datetime import datetime


class VortexLogger:
    """Simple structured logger with levels and optional file output."""

    LEVELS = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3}
    COLORS = {
        'DEBUG': '\033[90m',
        'INFO': '\033[36m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'RESET': '\033[0m'
    }

    def __init__(self, name='vortex', level='INFO', log_file=None):
        self.name = name
        self.level = self.LEVELS.get(level.upper(), 1)
        self.log_file = log_file
        if log_file:
            os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)

    def _log(self, level, module, message):
        if self.LEVELS.get(level, 1) < self.level:
            return

        timestamp = datetime.now().strftime('%H:%M:%S')
        color = self.COLORS.get(level, '')
        reset = self.COLORS['RESET']
        tag = f'[{level:7s}]'
        mod = f'[{module}]' if module else ''

        line = f"{timestamp} {color}{tag}{reset} {mod} {message}"
        print(line, flush=True)

        if self.log_file:
            plain = f"{timestamp} {tag} {mod} {message}\n"
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(plain)
            except Exception:
                pass

    def debug(self, module, msg):
        self._log('DEBUG', module, msg)

    def info(self, module, msg):
        self._log('INFO', module, msg)

    def warning(self, module, msg):
        self._log('WARNING', module, msg)

    def error(self, module, msg):
        self._log('ERROR', module, msg)


# Global logger instance
log_level = os.environ.get('VORTEX_LOG_LEVEL', 'INFO').upper()
log_file = os.path.join(os.getcwd(), 'vortex.log') if os.environ.get('VORTEX_LOG_FILE') else None
logger = VortexLogger(level=log_level, log_file=log_file)
