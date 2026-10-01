"""M09: authority response — status history, investigation notes, response actions

Revision ID: c3d7f1a9b6e2
Revises: b5c9e3f7a142
Create Date: 2026-10-01 18:00:00.000000

Additive only: three new tables. incidents.status is an existing String(20) column, so the
new 'response' status needs no schema change. No existing table or row is touched.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d7f1a9b6e2'
down_revision = 'b5c9e3f7a142'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'incident_status_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=False),
        sa.Column('previous_status', sa.String(length=20), nullable=False),
        sa.Column('new_status', sa.String(length=20), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_incident_status_history_incident_id', 'incident_status_history', ['incident_id'])

    op.create_table(
        'incident_investigations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_incident_investigations_incident_id', 'incident_investigations', ['incident_id'])

    op.create_table(
        'incident_response_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(length=30), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_incident_response_actions_incident_id', 'incident_response_actions', ['incident_id'])


def downgrade():
    op.drop_index('ix_incident_response_actions_incident_id', table_name='incident_response_actions')
    op.drop_table('incident_response_actions')
    op.drop_index('ix_incident_investigations_incident_id', table_name='incident_investigations')
    op.drop_table('incident_investigations')
    op.drop_index('ix_incident_status_history_incident_id', table_name='incident_status_history')
    op.drop_table('incident_status_history')
