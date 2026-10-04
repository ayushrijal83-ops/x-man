"""M-LIVE-02: iot_devices.kind (sensor | camera_node) + node_evidence (camera-node field evidence)

Additive only. Existing devices become kind 'sensor' through the server default, so ESP32 telemetry
is unchanged; only camera_node devices may use POST /api/iot/evidence.

Revision ID: e7413efdd252
Revises: a9c4e2f81d57
Create Date: 2026-10-04 11:47:00.001744

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7413efdd252'
down_revision = 'a9c4e2f81d57'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('node_evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('client_event_id', sa.String(length=64), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('district_id', sa.Integer(), nullable=False),
    sa.Column('captured_at', sa.DateTime(), nullable=False),
    sa.Column('gps_fix_at', sa.DateTime(), nullable=True),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('gps_accuracy_m', sa.Float(), nullable=True),
    sa.Column('gps_status', sa.String(length=20), nullable=False),
    sa.Column('location_source', sa.String(length=20), nullable=False),
    sa.Column('device_score', sa.Float(), nullable=True),
    sa.Column('device_model', sa.String(length=100), nullable=True),
    sa.Column('device_model_version', sa.String(length=64), nullable=True),
    sa.Column('app_version', sa.String(length=32), nullable=True),
    sa.Column('battery_pct', sa.Float(), nullable=True),
    sa.Column('network_type', sa.String(length=20), nullable=True),
    sa.Column('frame_filenames', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('hold_reason', sa.String(length=30), nullable=True),
    sa.Column('review_status', sa.String(length=20), nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('ai_status', sa.String(length=20), nullable=False),
    sa.Column('ai_label', sa.String(length=20), nullable=True),
    sa.Column('ai_confidence', sa.Float(), nullable=True),
    sa.Column('ai_model', sa.String(length=100), nullable=True),
    sa.Column('ai_model_version', sa.String(length=64), nullable=True),
    sa.Column('ai_analyzed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['device_id'], ['iot_devices.id'], ),
    sa.ForeignKeyConstraint(['district_id'], ['districts.id'], ),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_id', 'client_event_id', name='uq_node_evidence_device_event')
    )
    with op.batch_alter_table('node_evidence', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_node_evidence_device_id'), ['device_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_node_evidence_district_id'), ['district_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_node_evidence_incident_id'), ['incident_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_node_evidence_received_at'), ['received_at'], unique=False)

    with op.batch_alter_table('iot_devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=20), server_default='sensor', nullable=False))



def downgrade():
    with op.batch_alter_table('iot_devices', schema=None) as batch_op:
        batch_op.drop_column('kind')

    with op.batch_alter_table('node_evidence', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_node_evidence_received_at'))
        batch_op.drop_index(batch_op.f('ix_node_evidence_incident_id'))
        batch_op.drop_index(batch_op.f('ix_node_evidence_district_id'))
        batch_op.drop_index(batch_op.f('ix_node_evidence_device_id'))

    op.drop_table('node_evidence')
