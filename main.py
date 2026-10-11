"""Читает строки из таблицы users и печатает их в консоль.

Запуск из папки проекта, виртуальное окружение уже включено:

    python main.py
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

# load_dotenv читает .env и кладёт DB_HOST, DB_PORT и остальные в окружение.
# Пароль остаётся в файле, в этот скрипт его не вписываем.
load_dotenv()

conn = None
try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    # Курсор закрывается сам, когда блок with заканчивается.
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users;")
        rows = cur.fetchall()

    if not rows:
        print("Подключение есть, но таблица users пустая.")
        print("Добавь минимум 3 записи в pgAdmin и запусти скрипт ещё раз.")
    else:
        for row in rows:
            print(row)
except psycopg2.Error as error:
    # Сервер выключен, неверный пароль или таблицы users нет.
    print("Не удалось прочитать пользователей.")
    print(error)
    sys.exit(1)
finally:
    # finally выполняется и после успеха, и после ошибки.
    # Если connect не удался, conn ещё нет — закрывать нечего.
    if conn is not None and not conn.closed:
        conn.close()
