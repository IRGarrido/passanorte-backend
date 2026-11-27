"""Modelos Route/Prize (RF18–RF20) — T041, data-model.md."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.catalog.app.db import Base


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (CheckConstraint("reward_amount >= 0", name="ck_route_reward_amount"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    prize_id: Mapped[str | None] = mapped_column(String(36))
    category_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    reward_amount: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False)

    points: Mapped[list[RoutePoint]] = relationship(
        back_populates="route", order_by="RoutePoint.position", cascade="all, delete-orphan"
    )


class RoutePoint(Base):
    """Associação N:M ordenável e inativável (edge case: ponto removido no catalog)."""

    __tablename__ = "route_points"
    __table_args__ = (UniqueConstraint("route_id", "tourist_spot_id", name="uq_route_spot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), index=True)
    tourist_spot_id: Mapped[str] = mapped_column(String(36))
    position: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    route: Mapped[Route] = relationship(back_populates="points")
