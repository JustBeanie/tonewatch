"""Add the append-only security audit trail."""

import sqlalchemy as sa
from alembic import op

revision = "0003_audit_events"
down_revision = "0002_alert_attempt_phase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("before", sa.JSON()),
        sa.Column("after", sa.JSON()),
        sa.Column("details", sa.JSON()),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
