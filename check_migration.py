from app import create_app
from app.extensions import db
from sqlalchemy import inspect

app = create_app()
with app.app_context():
    inspector = inspect(db.engine)
    cols = inspector.get_columns('seismic_event_states')
    for col in cols:
        print(f'  {col["name"]}: {col["type"]} nullable={col["nullable"]}')
    indexes = inspector.get_indexes('seismic_event_states')
    for idx in indexes:
        print(f'  Index: {idx["name"]} cols={idx["column_names"]} unique={idx["unique"]}')
    fks = inspector.get_foreign_keys('seismic_event_states')
    for fk in fks:
        print(f'  FK: {fk["name"]} -> {fk["referred_table"]}.{fk["referred_columns"]}')