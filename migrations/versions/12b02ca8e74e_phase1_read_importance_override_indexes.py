"""phase1: read + importance_override + indexes

Revision ID: 12b02ca8e74e
Revises: 576c071a1789
Create Date: 2025-08-10 15:00:47.997300

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "12b02ca8e74e"
down_revision: Union[str, Sequence[str], None] = "576c071a1789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # messages: add is_read + importance_override
    op.add_column(
        "messages",
        sa.Column(
            "is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "messages",
        sa.Column("importance_override", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "messages_importance_override_chk",
        "messages",
        "(importance_override IS NULL) OR (importance_override BETWEEN 0 AND 3)",
    )

    # helpful indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages (received_at DESC);"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_is_read ON messages (is_read);")

    # trigram (optional but recommended for search) — safe if extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_subject_trgm ON messages USING gin (subject gin_trgm_ops);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_sender_trgm  ON messages USING gin (sender  gin_trgm_ops);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_summary_trgm ON messages USING gin ((summary_json->>'summary') gin_trgm_ops);"
    )

    # drop server default to keep behavior explicit
    op.alter_column("messages", "is_read", server_default=None)


def downgrade():
    op.drop_constraint("messages_importance_override_chk", "messages", type_="check")
    op.drop_index("idx_messages_summary_trgm", table_name="messages")
    op.drop_index("idx_messages_sender_trgm", table_name="messages")
    op.drop_index("idx_messages_subject_trgm", table_name="messages")
    op.drop_index("idx_messages_is_read", table_name="messages")
    op.drop_index("idx_messages_received_at", table_name="messages")
    op.drop_column("messages", "importance_override")
    op.drop_column("messages", "is_read")
