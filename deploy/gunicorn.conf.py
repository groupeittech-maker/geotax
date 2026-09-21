"""Configuration Gunicorn optimisée pour la production."""
import multiprocessing
import os

bind = os.environ.get('GUNICORN_BIND', '127.0.0.1:8000')
workers = int(os.environ.get('GUNICORN_WORKERS', max(2, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.environ.get('GUNICORN_THREADS', '2'))
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', '30'))
keepalive = int(os.environ.get('GUNICORN_KEEPALIVE', '5'))
max_requests = int(os.environ.get('GUNICORN_MAX_REQUESTS', '1000'))
max_requests_jitter = int(os.environ.get('GUNICORN_MAX_REQUESTS_JITTER', '50'))
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')
worker_tmp_dir = os.environ.get('GUNICORN_WORKER_TMP_DIR', '/dev/shm')
accesslog = '-'
errorlog = '-'
capture_output = True
preload_app = False
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s '
    '"%(f)s" "%(a)s" %(D)s'
)
