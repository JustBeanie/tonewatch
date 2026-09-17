"""CAD incidents and call links."""

import sqlalchemy as sa
from alembic import op

revision = "0007_cad_incidents"
down_revision = "0006_alert_attempt_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cad_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feed_id", sa.String(100), nullable=False),
        sa.Column("incident_id", sa.String(64), nullable=False),
        sa.Column("agency_name", sa.String(300), nullable=False),
        sa.Column("agency_key", sa.String(300), nullable=False),
        sa.Column("agency_category", sa.String(300), nullable=False),
        sa.Column("type_raw", sa.String(300), nullable=False),
        sa.Column("type_key", sa.String(300), nullable=False),
        sa.Column("type_code", sa.String(300)),
        sa.Column("address_clean", sa.String(300), nullable=False),
        sa.Column("cross_streets", sa.JSON(), nullable=False),
        sa.Column("municipality_raw", sa.String(300), nullable=False),
        sa.Column("municipality_name", sa.String(300)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(300), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("feed_id", "incident_id", name="uq_cad_incident_feed_id"),
    )
    op.create_table(
        "call_cad_incidents",
        sa.Column(
            "call_id", sa.Uuid(), sa.ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("feed_id", sa.String(100), primary_key=True),
        sa.Column("incident_id", sa.String(64), primary_key=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delta_s", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("call_cad_incidents")
    op.drop_table("cad_incidents")
