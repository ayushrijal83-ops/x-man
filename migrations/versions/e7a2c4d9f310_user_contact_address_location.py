"""Product quality: user contact, address and current-location fields

Revision ID: e7a2c4d9f310
Revises: c3d7f1a9b6e2
Create Date: 2026-10-02 10:00:00.000000

Additive: six nullable columns + phone_verified (default false) on users, and a unique index on
users.phone. Existing phone values are normalized to E.164 where they are valid Nepal mobiles
(e.g. 9841234567 -> +9779841234567); anything else is left exactly as it was. If two users share a
number (after normalization), only the lowest user id keeps it and the duplicates are cleared to
NULL; otherwise the unique index cannot be created. Users can re-enter a number on their profile.
"""
import re

from alembic import op
import sqlalchemy as sa


revision = 'e7a2c4d9f310'
down_revision = 'c3d7f1a9b6e2'
branch_labels = None
depends_on = None

NEPAL_MOBILE = re.compile(r'^9[678]\d{8}$')


def _normalize(raw):
    number = re.sub(r'[\s\-().]', '', raw or '')
    if number.startswith('+977'):
        number = number[4:]
    elif number.startswith('00977'):
        number = number[5:]
    elif len(number) == 13 and number.startswith('977'):
        number = number[3:]
    return '+977' + number if NEPAL_MOBILE.match(number) else None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('phone_verified', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('full_name', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('permanent_address', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('current_latitude', sa.Float(), nullable=True))
        batch.add_column(sa.Column('current_longitude', sa.Float(), nullable=True))
        batch.add_column(sa.Column('current_address', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('location_updated_at', sa.DateTime(), nullable=True))

    conn = op.get_bind()
    taken = set()
    rows = conn.execute(sa.text('SELECT id, phone FROM users WHERE phone IS NOT NULL ORDER BY id')).fetchall()
    for user_id, phone in rows:
        value = _normalize(phone) or phone
        if value in taken:  # duplicate number: can't be unique, and can't be trusted for SMS
            conn.execute(sa.text('UPDATE users SET phone = NULL WHERE id = :i'), {'i': user_id})
            continue
        taken.add(value)
        if value != phone:
            conn.execute(sa.text('UPDATE users SET phone = :p WHERE id = :i'), {'p': value, 'i': user_id})
    op.create_index('uq_users_phone', 'users', ['phone'], unique=True)


def downgrade():
    op.drop_index('uq_users_phone', table_name='users')
    with op.batch_alter_table('users') as batch:
        for name in ('location_updated_at', 'current_address', 'current_longitude', 'current_latitude',
                     'permanent_address', 'full_name', 'phone_verified'):
            batch.drop_column(name)
