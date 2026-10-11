"""Модель стола мини-системы бронирования.

Один объект Table — это один конкретный стол в ресторане,
а не таблица в базе. Файл только хранит поля и ничего не записывает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Table:
    """Данные одного стола.

    number — номер в зале, seats — сколько гостей за ним помещается.
    id и created_at стоят в конце из-за правила dataclass:
    поля со значением по умолчанию идут после обязательных.
    Пока строка не сохранена, эти два поля пустые.
    """

    number: int
    seats: int
    description: str | None = None
    is_active: bool = True
    id: int | None = None
    created_at: datetime | None = None
