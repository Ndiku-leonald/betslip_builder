"""track whether a provider usage row represents an outbound request"""

from alembic import op
import sqlalchemy as sa

revision = "0003_provider_request_accounting"
down_revision = "0002_observation_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_usage", sa.Column("external_request", sa.Boolean(), nullable=True, server_default=sa.true()))
    op.execute("UPDATE provider_usage SET external_request = 1 WHERE external_request IS NULL")


def downgrade() -> None:
    op.drop_column("provider_usage", "external_request")
