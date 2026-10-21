"""Add the external opening balance baseline used when an account is funded."""

import sqlalchemy as sa

from alembic import op

revision = "0004_opening_balances"
down_revision = "0003_reversals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("opening_balance_minor", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_accounts_opening_balance_nonnegative",
        "accounts",
        "opening_balance_minor >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_opening_balance_nonnegative", "accounts", type_="check")
    op.drop_column("accounts", "opening_balance_minor")
