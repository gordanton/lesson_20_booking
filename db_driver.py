"""Драйвер PostgreSQL для других проектов.

Подключение такое же, как в test_connection.py: load_dotenv() и переменные
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.

Пример из другого проекта (файл лежит рядом со скриптом или в PYTHONPATH):

    from db_driver import PostgresDriver

    db = PostgresDriver()
    row = db.create("tasks", {"title": "Сверка часов", "hours": 8})
    rows = db.read("tasks", filters={"title": "Сверка часов"})
    db.update("tasks", {"hours": 10}, filters={"id": row["id"]})
    db.delete("tasks", filters={"id": row["id"]})

Каждый вызов сам открывает соединение, выполняет запрос и закрывает его.
Это отдельная транзакция: если update упадёт, create уже не отменится.
"""

from __future__ import annotations

import os
from dataclasses import MISSING, fields, is_dataclass
from datetime import datetime
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor


class DatabaseConfigError(Exception):
    """В .env не хватает параметров подключения."""


class PostgresDriver:
    """CRUD-доступ к PostgreSQL: create, read, update, delete.

    create_table создаёт таблицу по dataclass-модели, если её ещё нет.
    """

    def __init__(self, env_file: str | None = None) -> None:
        # env_file нужен, когда модуль вызывают не из папки с .env.
        load_dotenv(env_file)
        self._params = self._read_params()

    def _read_params(self) -> dict[str, str]:
        params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
        }
        required = {
            "DB_NAME": params["dbname"],
            "DB_USER": params["user"],
            "DB_PASSWORD": params["password"],
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise DatabaseConfigError(
                "В .env не заданы: " + ", ".join(missing)
            )
        return params

    def _connect(self):
        # Тот же вызов, что в test_connection.py. Ошибку соединения не глотаем:
        # внешний проект сам решит, что показать пользователю.
        return psycopg2.connect(**self._params)

    def _run(self, query: sql.Composable, values: list[Any], fetch: str):
        """Выполняет один запрос и закрывает соединение.

        fetch: "one", "all" или "count".
        with у соединения в psycopg2 фиксирует транзакцию, но само соединение
        не закрывает — поэтому close() стоит отдельно в finally.
        """
        conn = self._connect()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, values)
                    if fetch == "one":
                        row = cur.fetchone()
                        return dict(row) if row else None
                    if fetch == "all":
                        return [dict(row) for row in cur.fetchall()]
                    return cur.rowcount
        finally:
            conn.close()

    def create(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        """INSERT одной строки. Возвращает вставленную строку (нужен RETURNING *)."""
        self._require_data(data)
        columns = list(data)
        query = sql.SQL(
            "INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING *"
        ).format(
            table=self._table_name(table),
            columns=sql.SQL(", ").join(sql.Identifier(name) for name in columns),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        row = self._run(query, list(data.values()), fetch="one")
        return row

    def read(
        self,
        table: str,
        filters: dict[str, Any] | None = None,
        columns: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """SELECT. filters — условия «столбец = значение», они склеиваются через AND.

        Без filters вернутся все строки таблицы. На большой таблице передай limit.
        """
        query, values = self._select(table, filters, columns, limit)
        return self._run(query, values, fetch="all")

    def read_one(
        self,
        table: str,
        filters: dict[str, Any],
        columns: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Одна строка по фильтру. None, если ничего не нашли.

        Если фильтр подошёл нескольким строкам — это ошибка: бери read().
        """
        self._require_filters(filters, "read_one")
        rows = self.read(table, filters=filters, columns=columns, limit=2)
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(
                f"read_one для «{table}» нашёл больше одной строки. Уточни filters."
            )
        return rows[0]

    def update(
        self,
        table: str,
        data: dict[str, Any],
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """UPDATE строк, которые подходят под filters. Возвращает обновлённые строки.

        filters обязателен: без него запрос перезаписал бы всю таблицу.
        """
        self._require_data(data)
        self._require_filters(filters, "update")
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder())
            for name in data
        )
        where_sql, where_values = self._where(filters)
        query = sql.SQL(
            "UPDATE {table} SET {assignments}{where} RETURNING *"
        ).format(
            table=self._table_name(table),
            assignments=assignments,
            where=where_sql,
        )
        values = [*data.values(), *where_values]
        return self._run(query, values, fetch="all")

    def delete(self, table: str, filters: dict[str, Any]) -> int:
        """DELETE строк по filters. Возвращает, сколько строк удалено.

        filters обязателен: без него запрос очистил бы всю таблицу.
        """
        self._require_filters(filters, "delete")
        where_sql, where_values = self._where(filters)
        query = sql.SQL("DELETE FROM {table}{where}").format(
            table=self._table_name(table),
            where=where_sql,
        )
        return self._run(query, where_values, fetch="count")

    def create_table(self, model: type) -> str:
        """CREATE TABLE IF NOT EXISTS по полям модели.

        На вход — класс, как User в models/user.py, а не готовый объект.
        Имя таблицы: имя класса в нижнем регистре и «s» на конце (User → users).
        Если таблица уже есть, PostgreSQL её не меняет.
        Возвращает имя таблицы.
        """
        model = self._as_model(model)
        table = self._model_table_name(model)
        hints = get_type_hints(model)
        columns = sql.SQL(", ").join(
            self._column_def(field, hints[field.name]) for field in fields(model)
        )
        query = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {table} ({columns})"
        ).format(
            table=self._table_name(table),
            columns=columns,
        )
        self._run(query, [], fetch="count")
        return table

    def _select(self, table, filters, columns, limit):
        if columns is not None:
            if not columns:
                raise ValueError("Список columns пуст. Убери его, чтобы взять все столбцы.")
            selected = sql.SQL(", ").join(sql.Identifier(name) for name in columns)
        else:
            selected = sql.SQL("*")

        where_sql, values = self._where(filters or {})
        limit_sql = sql.SQL("")
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise ValueError("limit должен быть целым числом больше нуля.")
            limit_sql = sql.SQL(" LIMIT {}").format(sql.Literal(limit))

        query = sql.SQL("SELECT {selected} FROM {table}{where}{limit}").format(
            selected=selected,
            table=self._table_name(table),
            where=where_sql,
            limit=limit_sql,
        )
        return query, values

    def _where(self, filters: dict[str, Any]) -> tuple[sql.Composable, list[Any]]:
        if not filters:
            return sql.SQL(""), []

        parts: list[sql.Composable] = []
        values: list[Any] = []
        for name, value in filters.items():
            # В SQL сравнение с NULL через «=» ничего не находит. Нужен IS NULL.
            if value is None:
                parts.append(sql.SQL("{} IS NULL").format(sql.Identifier(name)))
            else:
                parts.append(
                    sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder())
                )
                values.append(value)
        return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts), values

    def _table_name(self, table: str) -> sql.Identifier:
        # Имя таблицы нельзя подставить через %s: так передают только значения.
        # Identifier экранирует имя, поэтому текст вроде «users; DROP» не станет командой.
        if not isinstance(table, str) or not table.strip():
            raise ValueError("Имя таблицы должно быть непустой строкой.")
        parts = table.split(".")
        if len(parts) > 2 or any(not part for part in parts):
            raise ValueError("Имя таблицы: «таблица» или «схема.таблица».")
        return sql.Identifier(*parts)

    @staticmethod
    def _as_model(model: type) -> type:
        # Можно передать и объект User(...): для схемы нужен сам класс.
        if not isinstance(model, type):
            model = type(model)
        if not is_dataclass(model):
            raise ValueError(
                "Нужен класс-модель, как User: dataclass с полями."
            )
        return model

    @staticmethod
    def _model_table_name(model: type) -> str:
        name = model.__name__.lower()
        if name.endswith("s"):
            return name
        return name + "s"

    @staticmethod
    def _split_optional(annotation: Any) -> tuple[Any, bool]:
        """str | None → (str, можно пустое). Обычный str → (str, нельзя пустое)."""
        origin = get_origin(annotation)
        if origin in (Union, UnionType):
            args = get_args(annotation)
            non_none = [arg for arg in args if arg is not NoneType]
            if len(non_none) == 1 and len(non_none) < len(args):
                return non_none[0], True
        return annotation, False

    def _column_def(self, field, annotation: Any) -> sql.Composable:
        """Одно поле модели → кусок SQL для списка столбцов."""
        base, nullable = self._split_optional(annotation)
        parts: list[sql.Composable] = [sql.Identifier(field.name)]

        # id в модели пустой, пока строка не сохранена: номер выдаёт база.
        if field.name == "id" and base is int:
            parts.append(sql.SQL("SERIAL PRIMARY KEY"))
            return sql.SQL(" ").join(parts)

        sql_type = {
            str: "TEXT",
            int: "INTEGER",
            bool: "BOOLEAN",
            datetime: "TIMESTAMPTZ",
        }.get(base)
        if sql_type is None:
            raise ValueError(
                f"Поле {field.name}: тип {base!r} не умею переводить в столбец."
            )
        parts.append(sql.SQL(sql_type))

        # created_at тоже заполняет база, поэтому у столбца есть значение по умолчанию.
        if field.name == "created_at" and base is datetime:
            parts.append(sql.SQL("NOT NULL DEFAULT NOW()"))
            return sql.SQL(" ").join(parts)

        # user_id → таблица users, table_id → таблица tables.
        if field.name.endswith("_id") and base is int:
            ref_name = field.name[: -len("_id")]
            if not ref_name.endswith("s"):
                ref_name += "s"
            parts.append(sql.SQL("NOT NULL"))
            parts.append(
                sql.SQL("REFERENCES {} ({})").format(
                    sql.Identifier(ref_name),
                    sql.Identifier("id"),
                )
            )
            return sql.SQL(" ").join(parts)

        if not nullable:
            parts.append(sql.SQL("NOT NULL"))
        if base is bool and field.default is not MISSING:
            parts.append(sql.SQL("DEFAULT {}").format(sql.Literal(field.default)))
        return sql.SQL(" ").join(parts)

    @staticmethod
    def _require_data(data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or not data:
            raise ValueError("data должен быть непустым словарём: столбец → значение.")

    @staticmethod
    def _require_filters(filters: dict[str, Any], method: str) -> None:
        if not isinstance(filters, dict) or not filters:
            raise ValueError(
                f"{method} без filters не выполняю: так можно задеть всю таблицу."
            )
