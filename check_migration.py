from app import create_app
from app.extensions import db
from sqlalchemy import inspect

app = create_app()
with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print('Tables:', tables)
    if 'seismic_event_states' in tables:
        cols = inspector.get_columns('seismic_event_states')
        for col in cols:
            name = col["name"]
            typ = col["type"]
            nullable = col["nullable"]
            default = col.get("default")
            print(f'  {name}: {typ} nullable={nullable} default={default}')
        indexes = inspector.get_indexes('seismic_event_states')
        for idx in indexes:
            name = idx["name"]
            col_names = idx["column_names"]
            unique = idx["unique"]
            print(f'  Index: {name} cols={col_names} unique={unique}')
        fks = inspector.get_foreign_keys('seismic_event_states')
        for fk in fks:
            name = fk["name"]
            ref_table = fk["referred_table"]
            ref_cols = fk["referred_columns"]
            print(f'  FK: {name} -> {ref_table}.{ref_cols}')