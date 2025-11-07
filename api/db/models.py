from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, func


class Base(DeclarativeBase):
    """Base class for ORM models."""
    pass


class ChannelUser(Base):
    __tablename__ = "channel_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_user_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(10))     # 'user' | 'bot'
    message: Mapped[str] = mapped_column(Text())
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
