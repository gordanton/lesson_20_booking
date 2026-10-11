"""Запись, чтение, обновление и удаление для users, tables и bookings.

Модели остаются просто полями. В базу их отправляет PostgresDriver,
а этот файл переводит объект в словарь и обратно.
"""

from dataclasses import asdict
from datetime import datetime, timezone

from db_driver import PostgresDriver
from models.booking import Booking
from models.tables import Table
from models.user import User


def create_tables():
    """Создаёт три таблицы, если их ещё нет."""
    db = PostgresDriver()
    db.create_table(User)
    db.create_table(Table)
    db.create_table(Booking)


def _to_db(obj) -> dict:
    """Словарь для INSERT и UPDATE.

    id и created_at не отправляем: их ставит сама база.
    """
    data = asdict(obj)
    data.pop("id")
    data.pop("created_at")
    return data


def _require_id(obj, name: str) -> int:
    if obj.id is None:
        raise ValueError(f"Для изменения {name} нужен id. Сначала прочитай строку из базы.")
    return obj.id


# --- Пользователи, таблица users ---


def add_user(user: User) -> User:
    """Записывает одного пользователя и возвращает его уже с id."""
    row = PostgresDriver().create("users", _to_db(user))
    return User(**row)


def read_users(user_id: int | None = None) -> list[User]:
    """Все пользователи. Если передан user_id — только этот."""
    filters = {"id": user_id} if user_id is not None else None
    rows = PostgresDriver().read("users", filters=filters)
    return [User(**row) for row in rows]


def update_user(user: User) -> User | None:
    """Перезаписывает пользователя с этим id. None, если такой строки нет."""
    user_id = _require_id(user, "пользователя")
    rows = PostgresDriver().update("users", _to_db(user), filters={"id": user_id})
    if not rows:
        return None
    return User(**rows[0])


def delete_user(user_id: int) -> int:
    """Удаляет пользователя. Не выйдет, пока на него есть брони."""
    return PostgresDriver().delete("users", filters={"id": user_id})


# --- Столы ресторана, таблица tables ---


def add_table(table: Table) -> Table:
    """Записывает один стол и возвращает его уже с id."""
    row = PostgresDriver().create("tables", _to_db(table))
    return Table(**row)


def read_tables(table_id: int | None = None) -> list[Table]:
    """Все столы. Если передан table_id — только этот."""
    filters = {"id": table_id} if table_id is not None else None
    rows = PostgresDriver().read("tables", filters=filters)
    return [Table(**row) for row in rows]


def update_table(table: Table) -> Table | None:
    """Перезаписывает стол с этим id. None, если такой строки нет."""
    table_id = _require_id(table, "стола")
    rows = PostgresDriver().update("tables", _to_db(table), filters={"id": table_id})
    if not rows:
        return None
    return Table(**rows[0])


def delete_table(table_id: int) -> int:
    """Удаляет стол. Не выйдет, пока на него есть брони."""
    return PostgresDriver().delete("tables", filters={"id": table_id})


# --- Брони, таблица bookings ---


def _as_utc(value: datetime) -> datetime:
    """Одно и то же мгновение, чтобы времена можно было сравнить.

    Из базы время приходит с часовым поясом, из поля ввода — часто без него.
    Наивное значение считаем местным временем компьютера: так его понимает
    PostgreSQL, когда записывает timestamp with time zone.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc)


def _require_period(starts_at: datetime, ends_at: datetime) -> None:
    if _as_utc(ends_at) <= _as_utc(starts_at):
        raise ValueError("Конец брони должен быть позже начала.")


def _overlapping_booking(
    table_id: int,
    starts_at: datetime,
    ends_at: datetime,
    booking_id: int | None = None,
) -> Booking | None:
    """Активная бронь этого стола, чей промежуток пересекается с заданным.

    Промежуток полуоткрытый: [начало, конец). Бронь до 21:00 и бронь с 21:00
    стыкуются, но не пересекаются — стол в 21:00 уже свободен.
    booking_id — строка, которую сейчас меняем. Её саму в сравнение не берём,
    иначе сохранение комментария упрётся в собственное время.
    """
    rows = PostgresDriver().read(
        "bookings",
        filters={"table_id": table_id, "is_active": True},
    )
    start = _as_utc(starts_at)
    end = _as_utc(ends_at)
    for row in rows:
        other = Booking(**row)
        if booking_id is not None and other.id == booking_id:
            continue
        other_start = _as_utc(other.starts_at)
        other_end = _as_utc(other.ends_at)
        if start < other_end and other_start < end:
            return other
    return None


def check_table_availability(
    table_id: int,
    starts_at: datetime,
    ends_at: datetime,
    booking_id: int | None = None,
) -> bool:
    """True, если стол свободен на этот промежуток.

    Занятым стол считают только активные брони. Снятая галочка «Активна»
    место не держит. Неверный промежуток (конец не позже начала) — ошибка,
    а не «занято».
    """
    _require_period(starts_at, ends_at)
    return _overlapping_booking(table_id, starts_at, ends_at, booking_id) is None


def _ensure_table_available(booking: Booking, booking_id: int | None = None) -> None:
    """Не даёт записать активную бронь на уже занятый стол."""
    _require_period(booking.starts_at, booking.ends_at)
    if not booking.is_active:
        return
    conflict = _overlapping_booking(
        booking.table_id,
        booking.starts_at,
        booking.ends_at,
        booking_id,
    )
    if conflict is None:
        return
    start = conflict.starts_at.strftime("%Y-%m-%d %H:%M")
    end = conflict.ends_at.strftime("%Y-%m-%d %H:%M")
    raise ValueError(
        f"Этот стол уже занят с {start} до {end} (бронь id={conflict.id}). "
        "Выбери другой стол или другое время."
    )


def add_booking(booking: Booking) -> Booking:
    """Записывает одну бронь. user_id и table_id должны уже быть в базе.

    Активную бронь на занятое время этого стола не записывает.
    """
    _ensure_table_available(booking)
    row = PostgresDriver().create("bookings", _to_db(booking))
    return Booking(**row)


def read_bookings(booking_id: int | None = None) -> list[Booking]:
    """Все брони. Если передан booking_id — только эта."""
    filters = {"id": booking_id} if booking_id is not None else None
    rows = PostgresDriver().read("bookings", filters=filters)
    return [Booking(**row) for row in rows]


def update_booking(booking: Booking) -> Booking | None:
    """Перезаписывает бронь с этим id. None, если такой строки нет.

    Новое время тоже проверяется. Своя старая строка пересечением не считается.
    """
    booking_id = _require_id(booking, "брони")
    _ensure_table_available(booking, booking_id)
    rows = PostgresDriver().update(
        "bookings", _to_db(booking), filters={"id": booking_id}
    )
    if not rows:
        return None
    return Booking(**rows[0])


def delete_booking(booking_id: int) -> int:
    """Удаляет бронь и возвращает, сколько строк удалено."""
    return PostgresDriver().delete("bookings", filters={"id": booking_id})


def main():
    create_tables()


if __name__ == "__main__":
    main()
