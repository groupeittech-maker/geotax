"""Utilitaires base de données multi-SGBD (SQLite / PostgreSQL)."""
from sqlalchemy import inspect, text


def is_sqlite(engine):
    return engine.dialect.name == 'sqlite'


def is_postgresql(engine):
    return engine.dialect.name == 'postgresql'


def table_exists(engine, table_name):
    return inspect(engine).has_table(table_name)


def get_column_names(engine, table_name):
    if not table_exists(engine, table_name):
        return set()
    return {col['name'] for col in inspect(engine).get_columns(table_name)}


def column_exists(engine, table_name, column_name):
    return column_name in get_column_names(engine, table_name)


def add_column_if_missing(engine, session, table_name, column_name, ddl):
    """Ajoute une colonne si absente. Retourne True si ajoutée."""
    if column_exists(engine, table_name, column_name):
        return False
    if is_postgresql(engine):
        session.execute(text(f"SET lock_timeout = '8s'"))
        session.execute(text(
            f'ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {ddl}'
        ))
    else:
        session.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}'))
    return True


def reset_postgres_sequences(engine, table_names):
    """Remet à jour les séquences SERIAL après import de données avec IDs explicites."""
    if not is_postgresql(engine):
        return
    with engine.begin() as conn:
        for table_name in table_names:
            if not table_exists(engine, table_name):
                continue
            conn.execute(text(f"""
                SELECT setval(seq, val, true)
                FROM (
                    SELECT pg_get_serial_sequence('{table_name}', 'id') AS seq,
                           COALESCE((SELECT MAX(id) FROM {table_name}), 1) AS val
                ) s
                WHERE seq IS NOT NULL
            """))
