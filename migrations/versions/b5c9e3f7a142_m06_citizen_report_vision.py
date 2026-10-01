"""M06: vision analysis fields on citizen reports

Revision ID: b5c9e3f7a142
Revises: e4d8a1f6b209
Create Date: 2026-10-01 12:00:00.000000

Additive only: six nullable/defaulted columns on citizen_reports. Existing reports
become ai_status='not_analyzed'. No other table is touched; no image data in the DB.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5c9e3f7a142'
down_revision = 'e4d8a1f6b209'
branch_labels = None
depends_on = None

COLUMNS = ['ai_status', 'ai_label', 'ai_confidence', 'ai_model', 'ai_model_version', 'ai_analyzed_at']


def upgrade():
    with op.batch_alter_table('citizen_reports') as batch:
        batch.add_column(sa.Column('ai_status', sa.String(length=20), nullable=False, server_default='not_analyzed'))
        batch.add_column(sa.Column('ai_label', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('ai_confidence', sa.Float(), nullable=True))
        batch.add_column(sa.Column('ai_model', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('ai_model_version', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('ai_analyzed_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('citizen_reports') as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)
