"""Mark manually retried alert attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0006_alert_attempt_retry"
down_revision = "0005_call_agency_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_attempts",
        sa.Column("retry", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("alert_attempts", "retry")
