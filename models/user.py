"""Модель пользователя мини-системы бронирования.

Только поля одной строки будущей таблицы users.
Таблицу этот файл не создаёт и в базу ничего не пишет.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    """Данные одного пользователя.

    id и created_at стоят в конце: у dataclass поля со значением
    по умолчанию нельзя ставить перед обязательными.
    Пока строка не сохранена, эти два поля пустые.
    """

    full_name: str
    email: str
    password: str
    phone: str | None = None
    is_active: bool = True
    id: int | None = None
    created_at: datetime | None = None
