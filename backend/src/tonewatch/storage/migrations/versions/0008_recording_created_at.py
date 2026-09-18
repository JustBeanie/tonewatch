"""Track recording creation time for safe orphan cleanup."""

import sqlalchemy as sa
from alembic import op

revision = "0008_recording_created_at"
down_revision = "0007_cad_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("'1970-01-01 00:00:00'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recordings", "created_at")
