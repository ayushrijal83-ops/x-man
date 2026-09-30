"""M05: citizen photo reports

Revision ID: e4d8a1f6b209
Revises: c7e2b5a91d3f
Create Date: 2026-10-01 10:00:00.000000

Additive only: creates the citizen_reports table. No existing table is altered.
Image bytes are stored on disk (instance/uploads/reports/), not in the database.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4d8a1f6b209'
down_revision = 'c7e2b5a91d3f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'citizen_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reporter_id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=True),
        sa.Column('district_id', sa.Integer(), nullable=False),
        sa.Column('hazard_type', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('image_filename', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id']),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        sa.ForeignKeyConstraint(['district_id'], ['districts.id']),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('image_filename'),
    )
    op.create_index('ix_citizen_reports_reporter_id', 'citizen_reports', ['reporter_id'], unique=False)
    op.create_index('ix_citizen_reports_incident_id', 'citizen_reports', ['incident_id'], unique=False)
    op.create_index('ix_citizen_reports_district_id', 'citizen_reports', ['district_id'], unique=False)


def downgrade():
    op.drop_index('ix_citizen_reports_district_id', table_name='citizen_reports')
    op.drop_index('ix_citizen_reports_incident_id', table_name='citizen_reports')
    op.drop_index('ix_citizen_reports_reporter_id', table_name='citizen_reports')
    op.drop_table('citizen_reports')
