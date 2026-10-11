"""Окно системы бронирования.

Запуск из папки проекта, виртуальное окружение уже включено:

    python gui.py

Само окно в базу не ходит. Кнопки вызывают функции из backend.py.
«Создать таблицы» — это create_tables().
На каждой вкладке: список — read_*, «Добавить» — add_*,
«Сохранить изменения» — update_*, «Удалить» — delete_*.
Поле «Фильтр по id» вызывает read_* с номером строки.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import psycopg2

import backend
from db_driver import DatabaseConfigError
from models.booking import Booking
from models.tables import Table
from models.user import User


def format_dt(value) -> str:
    """Дата для списка и формы: 2026-10-11 19:00."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if value is None:
        return ""
    return str(value)


def parse_dt(text: str, label: str) -> datetime:
    raw = text.strip()
    if not raw:
        raise ValueError(f"Заполни поле «{label}».")
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"«{label}»: укажи дату как 2026-10-11 19:00 или 11.10.2026 19:00."
    )


def parse_int(text: str, label: str, minimum: int | None = None) -> int:
    raw = text.strip()
    if not raw:
        raise ValueError(f"Заполни поле «{label}».")
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"«{label}» должно быть целым числом.") from None
    if minimum is not None and value < minimum:
        raise ValueError(f"«{label}» должно быть не меньше {minimum}.")
    return value


def required_text(text: str, label: str) -> str:
    raw = text.strip()
    if not raw:
        raise ValueError(f"Заполни поле «{label}».")
    return raw


def optional_text(text: str) -> str | None:
    """Пустое поле становится None: в базе это NULL, а не пустая строка."""
    return text.strip() or None


def yes_no(value: bool) -> str:
    return "да" if value else "нет"


def explain_error(exc: Exception) -> str:
    """Короткий текст для окна ошибки. Техническую фразу базы переводим."""
    if isinstance(exc, DatabaseConfigError):
        return str(exc)
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, psycopg2.OperationalError):
        return (
            "Не удалось подключиться к PostgreSQL. "
            "Проверь, что сервер запущен, а DB_HOST, DB_PORT, DB_NAME, "
            "DB_USER и DB_PASSWORD в файле .env указаны верно."
        )
    if isinstance(exc, psycopg2.Error):
        if exc.pgcode == "42P01":
            return "Таблиц в базе ещё нет. Нажми кнопку «Создать таблицы»."
        if exc.pgcode == "23503":
            primary = ""
            if exc.diag is not None and exc.diag.message_primary:
                primary = exc.diag.message_primary.lower()
            if "insert" in primary or "вставк" in primary:
                return (
                    "Нельзя сохранить бронь: такого пользователя или стола уже нет. "
                    "Обнови список и выбери их снова."
                )
            return (
                "Нельзя удалить пользователя или стол, пока на них есть брони. "
                "Сначала удали связанные брони на вкладке «Брони»."
            )
        if exc.pgcode == "23502":
            column = exc.diag.column_name if exc.diag is not None else None
            if column:
                return f"В базе не заполнено обязательное поле «{column}»."
            return "Не заполнено обязательное поле."
        if exc.diag is not None and exc.diag.message_primary:
            return f"База данных вернула ошибку: {exc.diag.message_primary}"
        return "Ошибка базы данных."
    return f"Непредвиденная ошибка: {exc}"


class BookingApp(tk.Tk):
    """Главное окно: шапка, три вкладки и строка состояния внизу."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Бронирование столов")
        self.minsize(980, 620)
        self._apply_style()
        self._build()
        self._center(1100, 700)
        # Списки грузим после того, как окно уже видно.
        # Если базы нет, пользователь всё равно увидит интерфейс и текст ошибки.
        self._initial_refresh = self.after(200, self.refresh_all)

    def _apply_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=4)
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))

    def _center(self, width: int, height: int) -> None:
        x = max((self.winfo_screenwidth() - width) // 2, 0)
        y = max((self.winfo_screenheight() - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(12, 12, 12, 0))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Бронирование столов", style="Header.TLabel").pack(side="left")
        ttk.Button(header, text="Создать таблицы", command=self.on_create_tables).pack(side="right")
        ttk.Label(
            header,
            text="Создаёт users, tables и bookings, если их ещё нет",
        ).pack(side="right", padx=(0, 8))

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        self.users_tab = UsersTab(self.notebook, self)
        self.tables_tab = TablesTab(self.notebook, self)
        self.bookings_tab = BookingsTab(self.notebook, self)
        self.notebook.add(self.users_tab, text="Пользователи")
        self.notebook.add(self.tables_tab, text="Столы")
        self.notebook.add(self.bookings_tab, text="Брони")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.status = tk.StringVar(value="Готово.")
        ttk.Label(self, textvariable=self.status, padding=(12, 0, 12, 10), anchor="w").grid(
            row=2, column=0, sticky="ew"
        )

    def set_status(self, text: str) -> None:
        self.status.set(text)

    def show_error(self, exc: Exception) -> None:
        self.status.set("Есть ошибка. Текст показан в отдельном окне.")
        messagebox.showerror("Ошибка", explain_error(exc), parent=self)

    def on_create_tables(self) -> None:
        """Кнопка шапки. CREATE TABLE IF NOT EXISTS — повторный запуск ничего не стирает."""
        try:
            backend.create_tables()
        except Exception as exc:
            self.show_error(exc)
            return
        messagebox.showinfo(
            "Таблицы",
            "Таблицы users, tables и bookings созданы или уже были в базе.",
            parent=self,
        )
        self.refresh_all()

    def refresh_all(self) -> None:
        first_error: Exception | None = None
        for tab in (self.users_tab, self.tables_tab, self.bookings_tab):
            try:
                tab.load_into_tree(None)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            self.show_error(first_error)
            return
        self.set_status("Списки загружены из базы.")

    def on_tab_changed(self, _event) -> None:
        # На вкладке броней списки гостей и столов должны быть свежими:
        # пользователь мог только что добавить человека на соседней вкладке.
        try:
            current = self.notebook.nametowidget(self.notebook.select())
        except (KeyError, tk.TclError):
            return
        if current is not self.bookings_tab:
            return
        try:
            self.bookings_tab.prepare()
        except Exception as exc:
            self.show_error(exc)


class CrudTab(ttk.Frame):
    """Общая рамка вкладки: список слева, карточка справа.

    Одинаковые кнопки живут здесь один раз.
    Вкладка пользователя, стола или брони подставляет свои поля и свои
    функции бэкенда: fetch, insert, save, remove, build_new.
    """

    entity_accusative = "запись"
    columns: tuple[tuple[str, str, int], ...] = ()

    def __init__(self, master, app: BookingApp) -> None:
        super().__init__(master, padding=12)
        self.app = app
        self.records: dict[int, object] = {}
        self.selected_id: int | None = None
        # Пока идёт очистка списка, событие выбора строки не должно заново заполнять форму.
        self._filling = False
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="Обновить список", command=self.on_refresh).pack(side="left")
        ttk.Label(toolbar, text="Фильтр по id").pack(side="left", padx=(16, 6))
        self.filter_id = ttk.Entry(toolbar, width=12)
        self.filter_id.pack(side="left")
        self.filter_id.bind("<Return>", lambda _event: self.on_find())
        ttk.Button(toolbar, text="Показать", command=self.on_find).pack(side="left", padx=(6, 0))

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        list_frame = ttk.Frame(paned)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            list_frame,
            columns=[key for key, _heading, _width in self.columns],
            show="headings",
            selectmode="browse",
        )
        for key, heading, width in self.columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=width, stretch=False, anchor="w")
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        ttk.Label(
            list_frame,
            text="Серым отмечены неактивные записи. Выбери строку, чтобы заполнить карточку.",
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.tree.tag_configure("odd", background="#f4f7fb")
        self.tree.tag_configure("inactive", foreground="#555555")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right = ttk.Frame(paned)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        form = ttk.LabelFrame(right, text="Карточка", padding=12)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)
        next_row = self.build_form(form)
        self._build_buttons(form, next_row)

        paned.add(list_frame, weight=3)
        paned.add(right, weight=2)

    def _build_buttons(self, parent, row: int) -> None:
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)

        ttk.Button(box, text="Добавить", command=self.on_add).grid(
            row=0, column=0, sticky="ew", padx=(0, 4), pady=2
        )
        self.save_button = ttk.Button(box, text="Сохранить изменения", command=self.on_update)
        self.save_button.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=2)
        self.delete_button = ttk.Button(box, text="Удалить", command=self.on_delete)
        self.delete_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=2)
        ttk.Button(box, text="Очистить форму", command=self.clear_form).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=2
        )

        self.selected_label = ttk.Label(parent, text="Запись не выбрана")
        self.selected_label.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._set_selected(None)

    def _row(self, parent, row: int, label: str, widget) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
        widget.grid(row=row, column=1, sticky="ew", pady=4)

    def _set_selected(self, item_id: int | None) -> None:
        self.selected_id = item_id
        if item_id is None:
            self.selected_label.config(text="Запись не выбрана")
            self.save_button.state(["disabled"])
            self.delete_button.state(["disabled"])
            return
        self.selected_label.config(text=f"Выбрана запись id={item_id}")
        self.save_button.state(["!disabled"])
        self.delete_button.state(["!disabled"])

    def prepare(self) -> None:
        """Хук перед чтением. Вкладке броней он нужен, чтобы заполнить списки."""

    def build_form(self, parent) -> int:
        raise NotImplementedError

    def clear_fields(self) -> None:
        raise NotImplementedError

    def fill_form(self, obj) -> None:
        raise NotImplementedError

    def build_new(self):
        raise NotImplementedError

    def fetch(self, item_id: int | None) -> list:
        raise NotImplementedError

    def insert(self, obj):
        raise NotImplementedError

    def save(self, obj):
        raise NotImplementedError

    def remove(self, item_id: int) -> int:
        raise NotImplementedError

    def row_values(self, obj) -> tuple:
        raise NotImplementedError

    def build_existing(self, item_id: int):
        """Та же карточка, но с id: backend.update_* без id не работает."""
        obj = self.build_new()
        obj.id = item_id
        return obj

    def clear_form(self) -> None:
        self._filling = True
        try:
            self.clear_fields()
            if self.tree.selection():
                self.tree.selection_remove(self.tree.selection())
            self._set_selected(None)
        finally:
            self._filling = False

    def fill_tree(self, objects: list) -> None:
        keep = self.selected_id
        self._filling = True
        try:
            children = self.tree.get_children()
            if children:
                self.tree.delete(*children)
            self.records.clear()
            for index, obj in enumerate(objects):
                self.records[obj.id] = obj
                tags: list[str] = []
                if index % 2:
                    tags.append("odd")
                if not obj.is_active:
                    tags.append("inactive")
                self.tree.insert("", "end", iid=str(obj.id), values=self.row_values(obj), tags=tags)
            if keep is not None and self.tree.exists(str(keep)):
                self.tree.selection_set(str(keep))
                self.tree.see(str(keep))
            elif keep is not None:
                self._set_selected(None)
        finally:
            self._filling = False

    def load_into_tree(self, item_id: int | None) -> list:
        self.prepare()
        rows = self.fetch(item_id)
        self.fill_tree(rows)
        return rows

    def parsed_filter(self) -> int | None:
        raw = self.filter_id.get().strip()
        if not raw:
            return None
        return parse_int(raw, "id", minimum=1)

    def _reload_current(self) -> list | None:
        try:
            item_id = self.parsed_filter()
        except ValueError:
            item_id = None
        try:
            return self.load_into_tree(item_id)
        except Exception as exc:
            self.app.show_error(exc)
            return None

    def on_refresh(self) -> None:
        self.filter_id.delete(0, "end")
        rows = self._reload_current()
        if rows is not None:
            self.app.set_status(f"В списке: {len(rows)}.")

    def on_find(self) -> None:
        try:
            item_id = self.parsed_filter()
        except ValueError as exc:
            self.app.show_error(exc)
            return
        try:
            rows = self.load_into_tree(item_id)
        except Exception as exc:
            self.app.show_error(exc)
            return
        if item_id is None:
            self.app.set_status(f"В списке: {len(rows)}.")
            return
        if not rows:
            self.app.set_status(f"Запись id={item_id} не найдена.")
            return
        self.tree.selection_set(str(item_id))
        self.tree.see(str(item_id))
        self.app.set_status(f"Найдена запись id={item_id}.")

    def on_select(self, _event) -> None:
        if self._filling:
            return
        chosen = self.tree.selection()
        if not chosen:
            return
        item_id = int(chosen[0])
        obj = self.records.get(item_id)
        if obj is None:
            return
        self._set_selected(item_id)
        self.fill_form(obj)

    def on_add(self) -> None:
        try:
            created = self.insert(self.build_new())
        except Exception as exc:
            self.app.show_error(exc)
            return
        self.filter_id.delete(0, "end")
        reloaded = self._reload_current()
        self.clear_form()
        if reloaded is not None:
            self.app.set_status(f"Добавлена запись id={created.id}.")

    def on_update(self) -> None:
        if self.selected_id is None:
            self.app.show_error(ValueError("Сначала выбери запись в списке слева."))
            return
        try:
            saved = self.save(self.build_existing(self.selected_id))
        except Exception as exc:
            self.app.show_error(exc)
            return
        if saved is None:
            self.app.show_error(ValueError("Такой записи в базе уже нет. Список обновлён."))
            self._reload_current()
            self.clear_form()
            return
        reloaded = self._reload_current()
        if reloaded is None:
            return
        if self.tree.exists(str(saved.id)):
            self.tree.selection_set(str(saved.id))
            self.tree.see(str(saved.id))
        self.app.set_status(f"Изменения сохранены, id={saved.id}.")

    def on_delete(self) -> None:
        if self.selected_id is None:
            self.app.show_error(ValueError("Сначала выбери запись в списке слева."))
            return
        agreed = messagebox.askyesno(
            "Удаление",
            f"Удалить {self.entity_accusative} id={self.selected_id}?",
            parent=self.app,
            default="no",
        )
        if not agreed:
            return
        try:
            deleted = self.remove(self.selected_id)
        except Exception as exc:
            self.app.show_error(exc)
            return
        self.clear_form()
        reloaded = self._reload_current()
        if reloaded is None:
            return
        if deleted == 0:
            self.app.set_status("Строка уже была удалена.")
            return
        self.app.set_status(f"Удалено записей: {deleted}.")


class UsersTab(CrudTab):
    """Пользователи: add_user, read_users, update_user, delete_user."""

    entity_accusative = "пользователя"
    columns = (
        ("id", "id", 50),
        ("full_name", "ФИО", 200),
        ("email", "Email", 200),
        ("phone", "Телефон", 130),
        ("is_active", "Активен", 80),
        ("created_at", "Создан", 140),
    )

    def build_form(self, parent) -> int:
        self.full_name = tk.StringVar()
        self.email = tk.StringVar()
        self.password = tk.StringVar()
        self.phone = tk.StringVar()
        self.is_active = tk.BooleanVar(value=True)
        self.show_password = tk.BooleanVar(value=False)

        self._row(parent, 0, "ФИО", ttk.Entry(parent, textvariable=self.full_name))
        self._row(parent, 1, "Email", ttk.Entry(parent, textvariable=self.email))
        self.password_entry = ttk.Entry(parent, textvariable=self.password, show="*")
        self._row(parent, 2, "Пароль", self.password_entry)
        ttk.Checkbutton(
            parent,
            text="Показать пароль",
            variable=self.show_password,
            command=self._toggle_password,
        ).grid(row=3, column=1, sticky="w")
        self._row(parent, 4, "Телефон", ttk.Entry(parent, textvariable=self.phone))
        ttk.Label(parent, text="Статус").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Checkbutton(parent, text="Активен", variable=self.is_active).grid(
            row=5, column=1, sticky="w", pady=4
        )
        ttk.Label(
            parent,
            text="Пароль в списке слева не показывается. При выборе строки он подставляется сюда.",
            wraplength=320,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return 7

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password.get() else "*")

    def clear_fields(self) -> None:
        self.full_name.set("")
        self.email.set("")
        self.password.set("")
        self.phone.set("")
        self.is_active.set(True)
        self.show_password.set(False)
        self.password_entry.configure(show="*")

    def fill_form(self, user: User) -> None:
        self.full_name.set(user.full_name)
        self.email.set(user.email)
        self.password.set(user.password)
        self.phone.set(user.phone or "")
        self.is_active.set(bool(user.is_active))

    def _email(self) -> str:
        email = required_text(self.email.get(), "Email")
        if " " in email or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Email должен содержать @ и не содержать пробелов.")
        return email

    def build_new(self) -> User:
        return User(
            full_name=required_text(self.full_name.get(), "ФИО"),
            email=self._email(),
            password=required_text(self.password.get(), "Пароль"),
            phone=optional_text(self.phone.get()),
            is_active=bool(self.is_active.get()),
        )

    def fetch(self, item_id: int | None) -> list[User]:
        return sorted(backend.read_users(item_id), key=lambda row: row.id or 0)

    def insert(self, user: User) -> User:
        return backend.add_user(user)

    def save(self, user: User) -> User | None:
        return backend.update_user(user)

    def remove(self, item_id: int) -> int:
        return backend.delete_user(item_id)

    def row_values(self, user: User) -> tuple:
        return (
            user.id,
            user.full_name,
            user.email,
            user.phone or "",
            yes_no(bool(user.is_active)),
            format_dt(user.created_at),
        )


class TablesTab(CrudTab):
    """Столы: add_table, read_tables, update_table, delete_table."""

    entity_accusative = "стол"
    columns = (
        ("id", "id", 50),
        ("number", "Номер", 80),
        ("seats", "Мест", 70),
        ("description", "Описание", 240),
        ("is_active", "Активен", 80),
        ("created_at", "Создан", 140),
    )

    def build_form(self, parent) -> int:
        self.number = tk.StringVar()
        self.seats = tk.StringVar()
        self.is_active = tk.BooleanVar(value=True)

        self._row(parent, 0, "Номер", ttk.Entry(parent, textvariable=self.number))
        self._row(parent, 1, "Мест", ttk.Entry(parent, textvariable=self.seats))
        self.description = tk.Text(parent, height=4, width=28, wrap="word", font=("Segoe UI", 10))
        self._row(parent, 2, "Описание", self.description)
        ttk.Label(parent, text="Статус").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Checkbutton(parent, text="Активен", variable=self.is_active).grid(
            row=3, column=1, sticky="w", pady=4
        )
        ttk.Label(
            parent,
            text="Описание можно оставить пустым. Номер и число мест — целые числа от 1.",
            wraplength=320,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return 5

    def _text_value(self, widget: tk.Text) -> str:
        return widget.get("1.0", "end").strip()

    def _set_text(self, widget: tk.Text, value: str | None) -> None:
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)

    def clear_fields(self) -> None:
        self.number.set("")
        self.seats.set("")
        self._set_text(self.description, "")
        self.is_active.set(True)

    def fill_form(self, table: Table) -> None:
        self.number.set(str(table.number))
        self.seats.set(str(table.seats))
        self._set_text(self.description, table.description)
        self.is_active.set(bool(table.is_active))

    def build_new(self) -> Table:
        return Table(
            number=parse_int(self.number.get(), "Номер", minimum=1),
            seats=parse_int(self.seats.get(), "Мест", minimum=1),
            description=optional_text(self._text_value(self.description)),
            is_active=bool(self.is_active.get()),
        )

    def fetch(self, item_id: int | None) -> list[Table]:
        return sorted(backend.read_tables(item_id), key=lambda row: row.id or 0)

    def insert(self, table: Table) -> Table:
        return backend.add_table(table)

    def save(self, table: Table) -> Table | None:
        return backend.update_table(table)

    def remove(self, item_id: int) -> int:
        return backend.delete_table(item_id)

    def row_values(self, table: Table) -> tuple:
        return (
            table.id,
            table.number,
            table.seats,
            table.description or "",
            yes_no(bool(table.is_active)),
            format_dt(table.created_at),
        )


class BookingsTab(CrudTab):
    """Брони: add_booking, read_bookings, update_booking, delete_booking.

    Гость и стол выбираются из уже сохранённых строк.
    backend.add_booking сам запись не создаст, если такого id нет.
    """

    entity_accusative = "бронь"
    columns = (
        ("id", "id", 50),
        ("user", "Гость", 180),
        ("table", "Стол", 90),
        ("starts_at", "Начало", 140),
        ("ends_at", "Конец", 140),
        ("guests", "Гостей", 70),
        ("comment", "Комментарий", 200),
        ("is_active", "Активна", 80),
    )

    def build_form(self, parent) -> int:
        self.users_by_id: dict[int, User] = {}
        self.tables_by_id: dict[int, Table] = {}
        self.user_labels: dict[int, str] = {}
        self.table_labels: dict[int, str] = {}
        self._original_starts: datetime | None = None
        self._original_ends: datetime | None = None
        self.is_active = tk.BooleanVar(value=True)
        self.guests = tk.StringVar()

        self.user_combo = ttk.Combobox(parent, state="readonly")
        self.table_combo = ttk.Combobox(parent, state="readonly")
        self._row(parent, 0, "Гость", self.user_combo)
        self._row(parent, 1, "Стол", self.table_combo)
        self.starts_at = ttk.Entry(parent)
        self.ends_at = ttk.Entry(parent)
        self._row(parent, 2, "Начало", self.starts_at)
        self._row(parent, 3, "Конец", self.ends_at)
        ttk.Label(
            parent,
            text="Дата: 2026-10-11 19:00 или 11.10.2026 19:00",
            wraplength=320,
        ).grid(row=4, column=1, sticky="w")
        self._row(parent, 5, "Гостей", ttk.Entry(parent, textvariable=self.guests))
        self.comment = tk.Text(parent, height=4, width=28, wrap="word", font=("Segoe UI", 10))
        self._row(parent, 6, "Комментарий", self.comment)
        ttk.Label(parent, text="Статус").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Checkbutton(parent, text="Активна", variable=self.is_active).grid(
            row=7, column=1, sticky="w", pady=4
        )
        ttk.Label(
            parent,
            text=(
                "Сначала заведи гостя и стол на соседних вкладках. "
                "На одно время стол бронируется один раз. "
                "Следующую бронь можно начать ровно тогда, когда кончается предыдущая."
            ),
            wraplength=320,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return 9

    def prepare(self) -> None:
        users = backend.read_users()
        tables = backend.read_tables()
        self.users_by_id = {user.id: user for user in users if user.id is not None}
        self.tables_by_id = {table.id: table for table in tables if table.id is not None}
        self.user_labels = {user.id: f"{user.id} — {user.full_name}" for user in users if user.id is not None}
        self.table_labels = {
            table.id: f"{table.id} — стол {table.number}, мест: {table.seats}"
            for table in tables
            if table.id is not None
        }
        self.user_combo["values"] = [self.user_labels[user.id] for user in users if user.id is not None]
        self.table_combo["values"] = [self.table_labels[table.id] for table in tables if table.id is not None]

    def _set_text(self, widget: tk.Text, value: str | None) -> None:
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)

    def clear_fields(self) -> None:
        self.user_combo.set("")
        self.table_combo.set("")
        self.starts_at.delete(0, "end")
        self.ends_at.delete(0, "end")
        self.guests.set("")
        self._set_text(self.comment, "")
        self.is_active.set(True)
        self._original_starts = None
        self._original_ends = None

    def fill_form(self, booking: Booking) -> None:
        self.user_combo.set(self.user_labels.get(booking.user_id, ""))
        self.table_combo.set(self.table_labels.get(booking.table_id, ""))
        self.starts_at.delete(0, "end")
        self.starts_at.insert(0, format_dt(booking.starts_at))
        self.ends_at.delete(0, "end")
        self.ends_at.insert(0, format_dt(booking.ends_at))
        self.guests.set(str(booking.guests))
        self._set_text(self.comment, booking.comment)
        self.is_active.set(bool(booking.is_active))
        # Если время на форме не меняли, в базу уйдёт тот же объект, что прочитали.
        # Иначе повторное сохранение могло бы сдвинуть часовой пояс.
        self._original_starts = booking.starts_at
        self._original_ends = booking.ends_at

    def _choice_id(self, combo: ttk.Combobox, labels: dict[int, str], label: str) -> int:
        text = combo.get().strip()
        if not text:
            raise ValueError(f"Выбери «{label}» из списка.")
        for item_id, caption in labels.items():
            if caption == text:
                return item_id
        raise ValueError(f"«{label}» нужно выбрать из списка.")

    def _take_dt(self, text: str, original: datetime | None, label: str) -> datetime:
        if original is not None and text.strip() == format_dt(original):
            return original
        return parse_dt(text, label)

    def build_new(self) -> Booking:
        starts_at = self._take_dt(self.starts_at.get(), self._original_starts, "Начало")
        ends_at = self._take_dt(self.ends_at.get(), self._original_ends, "Конец")
        # Из базы время приходит с часовым поясом, а из поля ввода — без него.
        # Сравниваем цифры на часах, сам объект в базу уходит как был.
        if ends_at.replace(tzinfo=None) <= starts_at.replace(tzinfo=None):
            raise ValueError("Конец брони должен быть позже начала.")
        return Booking(
            user_id=self._choice_id(self.user_combo, self.user_labels, "Гость"),
            table_id=self._choice_id(self.table_combo, self.table_labels, "Стол"),
            starts_at=starts_at,
            ends_at=ends_at,
            guests=parse_int(self.guests.get(), "Гостей", minimum=1),
            comment=optional_text(self.comment.get("1.0", "end")),
            is_active=bool(self.is_active.get()),
        )

    def fetch(self, item_id: int | None) -> list[Booking]:
        rows = backend.read_bookings(item_id)
        return sorted(rows, key=lambda row: (row.starts_at, row.id or 0))

    def insert(self, booking: Booking) -> Booking:
        return backend.add_booking(booking)

    def save(self, booking: Booking) -> Booking | None:
        return backend.update_booking(booking)

    def remove(self, item_id: int) -> int:
        return backend.delete_booking(item_id)

    def row_values(self, booking: Booking) -> tuple:
        user = self.users_by_id.get(booking.user_id)
        table = self.tables_by_id.get(booking.table_id)
        user_text = user.full_name if user is not None else f"id {booking.user_id}"
        table_text = f"№{table.number}" if table is not None else f"id {booking.table_id}"
        return (
            booking.id,
            user_text,
            table_text,
            format_dt(booking.starts_at),
            format_dt(booking.ends_at),
            booking.guests,
            booking.comment or "",
            yes_no(bool(booking.is_active)),
        )


def main() -> None:
    app = BookingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
