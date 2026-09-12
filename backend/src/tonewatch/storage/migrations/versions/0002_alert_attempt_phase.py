"""Add the alert delivery phase to existing installations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_alert_attempt_phase"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a backward-compatible phase column to alert attempts."""
    with op.batch_alter_table("alert_attempts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("phase", sa.String(length=40), nullable=False, server_default="unknown")
        )


def downgrade() -> None:
    """Remove the alert delivery phase column."""
    with op.batch_alter_table("alert_attempts", schema=None) as batch_op:
        batch_op.drop_column("phase")
