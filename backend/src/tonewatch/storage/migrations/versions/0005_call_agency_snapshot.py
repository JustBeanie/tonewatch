"""Snapshot agency identity on matched call tone sets."""

import sqlalchemy as sa
from alembic import op

revision = "0005_call_agency_snapshot"
down_revision = "0004_discovered_tones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_tone_sets", sa.Column("agency_id", sa.String(100), nullable=True))
    op.add_column("call_tone_sets", sa.Column("agency_name", sa.String(200), nullable=True))
    op.add_column("call_tone_sets", sa.Column("agency_kind", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("call_tone_sets", "agency_kind")
    op.drop_column("call_tone_sets", "agency_name")
    op.drop_column("call_tone_sets", "agency_id")
