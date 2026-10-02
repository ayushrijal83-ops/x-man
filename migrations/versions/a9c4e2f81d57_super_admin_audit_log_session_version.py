"""Super Admin: append-only audit log + users.session_version (server-side session termination)

Revision ID: a9c4e2f81d57
Revises: f3b8d2e6a417
Create Date: 2026-10-02 12:00:00.000000

Additive only. Existing users start at session_version 0, which is what their current sessions
(stored as a bare user id) are treated as, so nobody is signed out by the upgrade.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a9c4e2f81d57'
down_revision = 'f3b8d2e6a417'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_version', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_username', sa.String(length=80), nullable=False),
        sa.Column('actor_role', sa.String(length=20), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target_type', sa.String(length=30), nullable=False),
        sa.Column('target_id', sa.String(length=64), nullable=False),
        sa.Column('target_label', sa.String(length=200), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('summary', sa.String(length=500), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_action'), ['action'], unique=False)
        batch_op.create_index('ix_audit_logs_target', ['target_type', 'target_id'], unique=False)


def downgrade():
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_logs_target')
        batch_op.drop_index(batch_op.f('ix_audit_logs_action'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_created_at'))
    op.drop_table('audit_logs')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('session_version')
