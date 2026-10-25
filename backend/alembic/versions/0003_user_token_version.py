"""Invalidate existing tokens after a password reset.

Revision ID: 0003_user_token_version
Revises: 0002_smart_parking_schema
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_user_token_version"
down_revision = "0002_smart_parking_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
