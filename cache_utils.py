"""Cache Redis optionnel pour requêtes carte et configuration."""
import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

_redis_client = None


def redis_enabled():
    return bool(os.environ.get('REDIS_URL', '').strip())


def get_redis():
    global _redis_client
    if not redis_enabled():
        return None
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(
                os.environ['REDIS_URL'],
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _redis_client.ping()
        except Exception as exc:
            logger.warning('Redis indisponible : %s', exc)
            _redis_client = False
    return _redis_client if _redis_client else None


def cache_key(prefix, *parts):
    raw = prefix + ':' + ':'.join(str(p) for p in parts if p is not None)
    if len(raw) > 200:
        return prefix + ':' + hashlib.sha256(raw.encode()).hexdigest()
    return raw


def cache_get(key):
    client = get_redis()
    if not client:
        return None
    try:
        val = client.get(key)
        return json.loads(val) if val else None
    except Exception as exc:
        logger.debug('cache_get(%s) : %s', key, exc)
        return None


def cache_set(key, value, ttl_seconds=None):
    client = get_redis()
    if not client:
        return False
    ttl = ttl_seconds or int(os.environ.get('REDIS_CACHE_TTL', '60'))
    try:
        client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
        return True
    except Exception as exc:
        logger.debug('cache_set(%s) : %s', key, exc)
        return False


def cache_delete_pattern(prefix):
    client = get_redis()
    if not client:
        return 0
    deleted = 0
    try:
        for key in client.scan_iter(match=f'{prefix}*', count=100):
            client.delete(key)
            deleted += 1
    except Exception as exc:
        logger.debug('cache_delete_pattern(%s) : %s', prefix, exc)
    return deleted
