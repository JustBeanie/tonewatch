"""Mark calls produced by the M19.4 end-to-end drill."""

import sqlalchemy as sa
from alembic import op

revision = "0009_call_drill"
down_revision = "0008_recording_created_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("drill", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column(
        "calls", sa.Column("drill_keep", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("calls", "drill")
    op.drop_column("calls", "drill_keep")
