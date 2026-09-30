"""M02: extend incidents into the hazard-event table

Revision ID: 199353c81cdc
Revises: 9493a03322a7
Create Date: 2026-09-30 19:51:23.934904

Additive only. The legacy `category` column is kept (made nullable, no longer
written) so no existing data is lost; legacy rows are backfilled into the new
fields.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '199353c81cdc'
down_revision = '9493a03322a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_type', sa.String(length=20), nullable=False, server_default='road_damage'))
        batch_op.add_column(sa.Column('source', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('river_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('road_segment_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('title', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('source_reference', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('detected_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('resolved_at', sa.DateTime(), nullable=True))
        batch_op.alter_column('category', existing_type=sa.String(length=50), nullable=True)
        batch_op.create_foreign_key('fk_incidents_river_id', 'rivers', ['river_id'], ['id'])
        batch_op.create_foreign_key('fk_incidents_road_segment_id', 'road_segments', ['road_segment_id'], ['id'])

    # Backfill legacy rows. Unrecognised categories fall back to road_damage; the
    # original text is preserved in both `category` and `title`.
    op.execute("""
        UPDATE incidents SET
            event_type = CASE
                WHEN lower(category) LIKE '%flood%' THEN 'flood'
                WHEN lower(category) LIKE '%landslide%' THEN 'landslide'
                ELSE 'road_damage' END,
            title = COALESCE(title, category),
            source = COALESCE(source, 'citizen_report'),
            detected_at = COALESCE(detected_at, created_at),
            status = CASE WHEN status = 'active' OR status IS NULL THEN 'detected' ELSE status END
        WHERE category IS NOT NULL OR status = 'active' OR status IS NULL
    """)
    op.execute("UPDATE incidents SET severity = 'medium' WHERE severity NOT IN ('low', 'medium', 'high', 'critical') OR severity IS NULL")
    op.execute("UPDATE incidents SET status = 'resolved' WHERE status NOT IN ('detected', 'investigating', 'confirmed', 'resolved', 'rejected')")

    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.alter_column('event_type', existing_type=sa.String(length=20), server_default=None)


def downgrade():
    op.execute("UPDATE incidents SET category = COALESCE(category, event_type)")
    op.execute("UPDATE incidents SET status = 'active' WHERE status IN ('detected', 'investigating', 'confirmed')")
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_incidents_road_segment_id', type_='foreignkey')
        batch_op.drop_constraint('fk_incidents_river_id', type_='foreignkey')
        batch_op.alter_column('category', existing_type=sa.String(length=50), nullable=False)
        batch_op.drop_column('resolved_at')
        batch_op.drop_column('detected_at')
        batch_op.drop_column('source_reference')
        batch_op.drop_column('title')
        batch_op.drop_column('road_segment_id')
        batch_op.drop_column('river_id')
        batch_op.drop_column('source')
        batch_op.drop_column('event_type')
