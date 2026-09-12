"""Store auto-discovered tone clusters."""

import sqlalchemy as sa
from alembic import op

revision = "0004_discovered_tones"
down_revision = "0003_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovered_tones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mean_frequencies", sa.JSON(), nullable=False),
        sa.Column("median_durations", sa.JSON(), nullable=False),
        sa.Column("duration_samples", sa.JSON(), nullable=False),
        sa.Column("frequency_minimums", sa.JSON(), nullable=False),
        sa.Column("frequency_maximums", sa.JSON(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("observed_frequency_spread_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="new"),
        sa.Column("best_clip_recording_path", sa.Text(), nullable=True),
        sa.Column("best_mean_purity", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("discovered_tones")
