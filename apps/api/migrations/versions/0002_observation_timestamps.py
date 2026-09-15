"""separate observation time from fixture kickoff time"""

from alembic import op
import sqlalchemy as sa

revision = "0002_observation_timestamps"
down_revision = "0001_phase1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fixtures", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fixtures", sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True))
    # Existing provider_timestamp values represented kickoff, so backfill from
    # the trustworthy local ingestion time instead of copying that defect.
    op.execute("UPDATE fixtures SET observed_at = ingested_at WHERE observed_at IS NULL")
    op.create_index("ix_fixtures_observed_at", "fixtures", ["observed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fixtures_observed_at", table_name="fixtures")
    op.drop_column("fixtures", "provider_updated_at")
    op.drop_column("fixtures", "observed_at")
