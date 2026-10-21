"""Link each reversal transfer to its original at most once."""

import sqlalchemy as sa

from alembic import op

revision = "0003_reversals"
down_revision = "0002_transfer_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transfers",
        sa.Column("reversal_of", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_transfers_reversal_of_transfers",
        "transfers",
        "transfers",
        ["reversal_of"],
        ["id"],
    )
    op.create_unique_constraint("uq_transfers_reversal_of", "transfers", ["reversal_of"])
    op.create_check_constraint(
        "ck_transfers_not_own_reversal", "transfers", "reversal_of IS NULL OR reversal_of <> id"
    )


def downgrade() -> None:
    op.drop_constraint("ck_transfers_not_own_reversal", "transfers", type_="check")
    op.drop_constraint("uq_transfers_reversal_of", "transfers", type_="unique")
    op.drop_constraint("fk_transfers_reversal_of_transfers", "transfers", type_="foreignkey")
    op.drop_column("transfers", "reversal_of")
