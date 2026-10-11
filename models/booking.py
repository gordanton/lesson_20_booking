"""Модель бронирования мини-системы.

Один объект Booking — одна бронь: кто, какой стол и на какое время.
Файл только хранит поля и ничего не записывает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Booking:
    """Данные одной брони.

    user_id — внешняя связь с пользователем: здесь лежит id строки
    из будущей таблицы users, а не сам объект User.
    table_id — то же для стола: id строки из будущей таблицы столов.

    id и created_at стоят в конце из-за правила dataclass:
    поля со значением по умолчанию идут после обязательных.
    Пока строка не сохранена, эти два поля пустые.
    """

    user_id: int
    table_id: int
    starts_at: datetime
    ends_at: datetime
    guests: int
    comment: str | None = None
    is_active: bool = True
    id: int | None = None
    created_at: datetime | None = None
