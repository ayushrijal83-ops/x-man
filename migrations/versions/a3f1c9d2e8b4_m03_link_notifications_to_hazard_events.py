"""M03: link notifications to hazard events

Revision ID: a3f1c9d2e8b4
Revises: 199353c81cdc
Create Date: 2026-09-30 21:00:00.000000

Additive only: two nullable columns and two indexes on `notifications`.
Existing (legacy) notifications are untouched and keep incident_id/severity NULL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f1c9d2e8b4'
down_revision = '199353c81cdc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('incident_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('severity', sa.String(length=20), nullable=True))
        batch_op.create_foreign_key('fk_notifications_incident_id', 'incidents', ['incident_id'], ['id'])
        batch_op.create_index('ix_notifications_incident_id', ['incident_id'], unique=False)
        batch_op.create_index('ix_notifications_user_read', ['user_id', 'is_read'], unique=False)


def downgrade():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index('ix_notifications_user_read')
        batch_op.drop_index('ix_notifications_incident_id')
        batch_op.drop_constraint('fk_notifications_incident_id', type_='foreignkey')
        batch_op.drop_column('severity')
        batch_op.drop_column('incident_id')
