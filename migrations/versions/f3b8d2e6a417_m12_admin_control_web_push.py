"""M12: admin control (account status, forced password change, last login) and Web Push

Revision ID: f3b8d2e6a417
Revises: e7a2c4d9f310
Create Date: 2026-10-03 10:00:00.000000

Additive only. Existing users stay active, are not forced to change their password and start in
emergency_alert_state 'not_requested' (nobody is opted in without asking the browser).
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3b8d2e6a417'
down_revision = 'e7a2c4d9f310'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('last_login_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('emergency_alert_state', sa.String(length=20), nullable=False,
                                      server_default='not_requested'))
        batch_op.add_column(sa.Column('emergency_sound_enabled', sa.Boolean(), nullable=False,
                                      server_default=sa.true()))

    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.String(length=1000), nullable=False),
        sa.Column('p256dh_key', sa.String(length=200), nullable=False),
        sa.Column('auth_key', sa.String(length=100), nullable=False),
        sa.Column('user_agent', sa.String(length=200), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('failure_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    with op.batch_alter_table('push_subscriptions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_push_subscriptions_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('push_subscriptions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_push_subscriptions_user_id'))
    op.drop_table('push_subscriptions')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('emergency_sound_enabled')
        batch_op.drop_column('emergency_alert_state')
        batch_op.drop_column('last_login_at')
        batch_op.drop_column('must_change_password')
        batch_op.drop_column('is_active')
