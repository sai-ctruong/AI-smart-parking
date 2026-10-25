"""Tie camera geometry revisions to declared reference images.

Revision ID: 0004_camera_reference_geometry
Revises: 0003_user_token_version
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_camera_reference_geometry"
down_revision = "0003_user_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("reference_image_sha256", sa.String(64)))
    op.add_column("cameras", sa.Column("reference_width", sa.Integer()))
    op.add_column("cameras", sa.Column("reference_height", sa.Integer()))
    op.add_column(
        "cameras",
        sa.Column(
            "viewpoint_version", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "polygon_revisions", sa.Column("reference_image_sha256", sa.String(64))
    )
    op.add_column("polygon_revisions", sa.Column("reference_width", sa.Integer()))
    op.add_column("polygon_revisions", sa.Column("reference_height", sa.Integer()))
    op.add_column(
        "polygon_revisions", sa.Column("camera_viewpoint_version", sa.Integer())
    )


def downgrade() -> None:
    op.drop_column("polygon_revisions", "camera_viewpoint_version")
    op.drop_column("polygon_revisions", "reference_height")
    op.drop_column("polygon_revisions", "reference_width")
    op.drop_column("polygon_revisions", "reference_image_sha256")
    op.drop_column("cameras", "viewpoint_version")
    op.drop_column("cameras", "reference_height")
    op.drop_column("cameras", "reference_width")
    op.drop_column("cameras", "reference_image_sha256")
