"""init schema"""

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "576c071a1789"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # users table
    op.create_table(
        "users",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("gmail_user_id", sa.Text, nullable=False, unique=True),
        sa.Column("email_address", sa.Text, nullable=False, unique=True),
        sa.Column("timezone", sa.Text, server_default="America/Toronto"),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("last_history_id", sa.BigInteger),
        sa.Column("schedule_cron", sa.Text, server_default="0 7 * * *"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
    )

    # messages table
    op.create_table(
        "messages",
        sa.Column("message_id", sa.Text, primary_key=True),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("sender", sa.Text),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("summary_json", pg.JSONB),
        sa.Column("gmail_permalink", sa.Text),
        sa.Column(
            "processed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
    )

    op.create_index(
        "idx_messages_user_time",
        "messages",
        ["user_id", sa.text("received_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_messages_user_time", table_name="messages")
    op.drop_table("messages")
    op.drop_table("users")
