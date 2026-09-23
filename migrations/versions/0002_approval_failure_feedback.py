"""Add approval failure and customer feedback fields.

Revision ID: 0002_approval_feedback
Revises: 0001_initial
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_approval_feedback"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("approvals") as batch_op:
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("result", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("approvals") as batch_op:
        batch_op.drop_column("notified_at")
        batch_op.drop_column("result")
        batch_op.drop_column("error_message")
