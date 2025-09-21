"""create action_items

Revision ID: 4cb9df30de25
Revises: 12b02ca8e74e
Create Date: 2025-09-07 23:16:23.406459

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4cb9df30de25"
down_revision: Union[str, Sequence[str], None] = "12b02ca8e74e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "action_items",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("message_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("importance", sa.Integer, nullable=False, server_default="2"),
        sa.Column(
            "is_done", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("done_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.message_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("idx_ai_message", "action_items", ["message_id"])
    op.create_index("idx_ai_done", "action_items", ["is_done"])
    op.create_index(
        "idx_ai_importance",
        "action_items",
        ["importance", "is_done", "created_at"],
        postgresql_using=None,
    )
    # optional uniqueness to avoid duplicates per message
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_msg_title ON action_items (message_id, lower(title));"
    )


def downgrade():
    op.drop_index("ux_ai_msg_title", table_name="action_items")
    op.drop_index("idx_ai_importance", table_name="action_items")
    op.drop_index("idx_ai_done", table_name="action_items")
    op.drop_index("idx_ai_message", table_name="action_items")
    op.drop_table("action_items")
