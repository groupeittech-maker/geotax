"""Configuration logging structuré pour la production."""
import logging
import os
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        for key in ('request_id', 'path', 'method', 'status', 'duration_ms'):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        return str(payload)


def setup_logging(app=None):
    level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if os.environ.get('LOG_FORMAT', '').lower() == 'json':
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            ))
        root.addHandler(handler)

    if app:
        app.logger.setLevel(level)

    logging.getLogger('werkzeug').setLevel(
        logging.WARNING if os.environ.get('FLASK_ENV') == 'production' else logging.INFO
    )
