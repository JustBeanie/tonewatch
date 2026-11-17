"""Index call time for CAD incident correlation."""

from alembic import op

revision = "0010_call_started_at"
down_revision = "0009_call_drill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_calls_started_at", "calls", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_calls_started_at", table_name="calls")
