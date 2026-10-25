"""Store measured upload decode and inference time.

Revision ID: 0005_snapshot_processing_time
Revises: 0004_camera_reference_geometry
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_snapshot_processing_time"
down_revision = "0004_camera_reference_geometry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("snapshots", sa.Column("processing_time_ms", sa.Float()))
    with op.batch_alter_table("snapshots") as batch:
        batch.create_check_constraint(
            "ck_snapshots_processing_time",
            "processing_time_ms IS NULL OR processing_time_ms >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("snapshots") as batch:
        batch.drop_constraint("ck_snapshots_processing_time", type_="check")
    op.drop_column("snapshots", "processing_time_ms")
