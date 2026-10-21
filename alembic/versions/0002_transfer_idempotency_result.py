"""Store transfer request hashes and idempotent responses."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_transfer_idempotency"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transfers",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )
    op.add_column("transfers", sa.Column("response_status", sa.Integer(), nullable=True))
    op.add_column("transfers", sa.Column("response_body", postgresql.JSONB(), nullable=True))
    # Existing transfer rows have no replayable request history. Give them a fixed marker and
    # reject a request with that marker as a hash mismatch instead of allowing a null hash.
    op.execute("UPDATE transfers SET request_hash = repeat('0', 64) WHERE request_hash IS NULL")
    op.alter_column("transfers", "request_hash", nullable=False)


def downgrade() -> None:
    op.drop_column("transfers", "response_body")
    op.drop_column("transfers", "response_status")
    op.drop_column("transfers", "request_hash")
