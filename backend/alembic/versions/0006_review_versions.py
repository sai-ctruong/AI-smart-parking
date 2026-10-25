"""Add monotonic review revisions for atomic concurrency control.

Revision ID: 0006_review_versions
Revises: 0005_snapshot_processing_time
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_review_versions"
down_revision = "0005_snapshot_processing_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "predictions",
        sa.Column("review_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("reviews", sa.Column("revision_no", sa.Integer(), nullable=True))
    # Existing review rows predate this endpoint. Preserve their chronological
    # order deterministically and make the most recent row the effective state.
    bind = op.get_bind()
    reviews = bind.execute(
        sa.text(
            "SELECT id, prediction_id FROM reviews "
            "ORDER BY prediction_id, reviewed_at, id"
        )
    ).all()
    versions = {}
    for review_id, prediction_id in reviews:
        version = versions.get(prediction_id, 0) + 1
        versions[prediction_id] = version
        bind.execute(
            sa.text("UPDATE reviews SET revision_no = :version WHERE id = :id"),
            {"version": version, "id": review_id},
        )
    for prediction_id, version in versions.items():
        bind.execute(
            sa.text("UPDATE predictions SET review_version = :version WHERE id = :id"),
            {"version": version, "id": prediction_id},
        )
    with op.batch_alter_table("reviews") as batch:
        batch.alter_column("revision_no", existing_type=sa.Integer(), nullable=False)
        batch.create_check_constraint("ck_reviews_revision_no", "revision_no > 0")
        batch.create_unique_constraint(
            "uq_reviews_prediction_revision", ["prediction_id", "revision_no"]
        )


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch:
        batch.drop_constraint("uq_reviews_prediction_revision", type_="unique")
        batch.drop_constraint("ck_reviews_revision_no", type_="check")
        batch.drop_column("revision_no")
    op.drop_column("predictions", "review_version")
