"""M04: affected districts + per-user alert dedup key

Revision ID: c7e2b5a91d3f
Revises: a3f1c9d2e8b4
Create Date: 2026-09-30 23:00:00.000000

Additive only:
- new table incident_affected_districts (additional districts; primary stays incidents.district_id)
- notifications.dedup_key (nullable) + unique index (user_id, dedup_key)

Backfill gives M03 hazard notifications a key, but only the earliest row per
(user, key). Any historical duplicates keep dedup_key NULL, so the unique index
can be created without deleting or rewriting a single row.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e2b5a91d3f'
down_revision = 'a3f1c9d2e8b4'
branch_labels = None
depends_on = None

HAZARD_TYPES_SQL = "('hazard_detected', 'hazard_escalated', 'hazard_confirmed', 'hazard_resolved')"
KEY_SQL = (
    "CAST(incident_id AS VARCHAR(20)) || ':' || type || "
    "CASE WHEN type = 'hazard_escalated' THEN ':' || COALESCE(severity, '') ELSE '' END"
)


def upgrade():
    op.create_table(
        'incident_affected_districts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=False),
        sa.Column('district_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        sa.ForeignKeyConstraint(['district_id'], ['districts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('incident_id', 'district_id', name='uq_incident_affected_district'),
    )
    op.create_index('ix_incident_affected_districts_district_id', 'incident_affected_districts',
                    ['district_id'], unique=False)

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dedup_key', sa.String(length=80), nullable=True))

    op.execute(f"""
        UPDATE notifications SET dedup_key = {KEY_SQL}
        WHERE id IN (
            SELECT MIN(id) FROM notifications
            WHERE incident_id IS NOT NULL AND type IN {HAZARD_TYPES_SQL}
            GROUP BY user_id, {KEY_SQL}
        )
    """)

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index('uq_notifications_user_dedup', ['user_id', 'dedup_key'], unique=True)


def downgrade():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index('uq_notifications_user_dedup')
        batch_op.drop_column('dedup_key')
    op.drop_index('ix_incident_affected_districts_district_id', table_name='incident_affected_districts')
    op.drop_table('incident_affected_districts')
