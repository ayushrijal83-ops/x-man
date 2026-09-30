"""Initial schema with IoT models

Revision ID: 9493a03322a7
Revises: 
Create Date: 2026-09-30 16:12:50.079933

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9493a03322a7'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # IoT Device table
    op.create_table(
        'iot_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('district_id', sa.Integer(), nullable=False),
        sa.Column('authority_id', sa.Integer(), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('location_description', sa.String(length=200), nullable=True),
        sa.Column('firmware_version', sa.String(length=50), nullable=True),
        sa.Column('api_key_hash', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['authority_id'], ['authorities.id'], ),
        sa.ForeignKeyConstraint(['district_id'], ['districts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id')
    )
    op.create_index(op.f('ix_iot_devices_device_id'), 'iot_devices', ['device_id'], unique=True)

    # Sensor Reading table
    op.create_table(
        'sensor_readings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('sensor_type', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('quality', sa.String(length=20), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('raw_payload', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['iot_devices.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sensor_readings_device_id'), 'sensor_readings', ['device_id'], unique=False)
    op.create_index(op.f('ix_sensor_readings_sensor_type'), 'sensor_readings', ['sensor_type'], unique=False)
    op.create_index('ix_sensor_readings_device_time', 'sensor_readings', ['device_id', 'recorded_at'], unique=False)
    op.create_index('ix_sensor_readings_type_time', 'sensor_readings', ['sensor_type', 'recorded_at'], unique=False)


def downgrade():
    op.drop_index('ix_sensor_readings_type_time', table_name='sensor_readings')
    op.drop_index('ix_sensor_readings_device_time', table_name='sensor_readings')
    op.drop_index(op.f('ix_sensor_readings_sensor_type'), table_name='sensor_readings')
    op.drop_index(op.f('ix_sensor_readings_device_id'), table_name='sensor_readings')
    op.drop_table('sensor_readings')
    op.drop_index(op.f('ix_iot_devices_device_id'), table_name='iot_devices')
    op.drop_table('iot_devices')