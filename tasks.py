"""Tâches lourdes exécutées en arrière-plan via RQ."""
import logging
import os

logger = logging.getLogger(__name__)

RQ_QUEUE_NAME = os.environ.get('RQ_QUEUE_NAME', 'geotax')


def get_queue():
    """Retourne la file RQ ou None si Redis indisponible."""
    from cache_utils import get_redis
    if not get_redis():
        return None
    try:
        from rq import Queue
        return Queue(RQ_QUEUE_NAME, connection=get_redis())
    except Exception as exc:
        logger.warning('File RQ indisponible : %s', exc)
        return None


def enqueue_task(func, *args, **kwargs):
    """Enfile une tâche ou exécute de façon synchrone si RQ absent."""
    queue = get_queue()
    if queue:
        return queue.enqueue(func, *args, **kwargs)
    logger.info('Exécution synchrone (RQ absent) : %s', func.__name__)
    return func(*args, **kwargs)


def task_sync_all_geoms(app):
    """Synchronise toutes les colonnes geom PostGIS."""
    with app.app_context():
        from spatial_utils import backfill_all_geoms
        from models import db
        return backfill_all_geoms(db.session)


def task_export_boutiques_excel(app, filters, output_path):
    """Export Excel des POI (tâche lourde)."""
    with app.app_context():
        import openpyxl
        from models import Boutique

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'POI'
        ws.append(['Code', 'Nom', 'Catégorie', 'Latitude', 'Longitude', 'Statut'])
        query = Boutique.query.filter_by(active=True)
        if filters.get('categorie'):
            query = query.filter_by(categorie=filters['categorie'])
        for b in query.all():
            ws.append([
                b.code_unique, b.nom, b.categorie,
                b.latitude, b.longitude, b.statut_validation,
            ])
        wb.save(output_path)
        return output_path
