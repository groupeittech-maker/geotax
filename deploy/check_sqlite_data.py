import sqlite3
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in ['instance/database.db', 'database.db']:
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        print(f'{path}: absent')
        continue
    c = sqlite3.connect(full)
    print(f'=== {path} ({os.path.getsize(full)} bytes) ===')
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    total = 0
    for (t,) in tables:
        if t.startswith('sqlite_'):
            continue
        n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        if n:
            print(f'  {t}: {n}')
            total += n
    print(f'  TOTAL lignes (tables non vides): {total}')
    c.close()
