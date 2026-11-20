from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
# 已有库的增量列：create_all 只建缺失的表，不补列
PATCHES = {
    'reports': {'schedule_type': "VARCHAR(16) NOT NULL DEFAULT 'interval'"},
    'deliveries': {'shift_id': 'INTEGER NULL', 'planned_at': 'DOUBLE PRECISION NULL',
                   'calendar_version': 'INTEGER NULL', 'backfill': 'BOOLEAN NOT NULL DEFAULT FALSE'},
}
def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        existing = {t: {c['name'] for c in inspect(conn).get_columns(t)} for t in PATCHES if inspect(conn).has_table(t)}
        for table, columns in PATCHES.items():
            for name, ddl in columns.items():
                if table in existing and name not in existing[table]:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
if __name__=='__main__':migrate()
