import shutil
from functools import partial
from PIL import Image, ImageTk, ImageOps
from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayItem
from PIL import Image as PILImage
import io
import os
import json
import glob
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from threading import Thread, Lock
import asyncio
import logging
import platform
import subprocess
import time
import threading
from datetime import datetime, timedelta
from telegram import Bot, Update, InputMediaPhoto
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, InvalidToken, NetworkError
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Dict, Any
import warnings
import psutil
import sys
import telegram


warnings.filterwarnings("ignore", category=DeprecationWarning)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
TOKEN = ""

class ContentEditor(tk.Toplevel):
    def __init__(self, parent, content_manager):
        super().__init__(parent)
        try:
            self.iconbitmap(parent.iconbitmap())
        except:
            pass
        self.parent = parent
        self.content_manager = content_manager
        self.current_page = None
        
        # Настройки модального окна
        self.transient(parent)
        self.grab_set()
        self.title("Редактор контента")
        self.geometry("1000x700")
        
        # Обработчик закрытия окна
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Создаем вкладки
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Вкладка 1: Редактор страниц
        self.pages_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pages_frame, text="Страницы")
        self.setup_pages_ui(self.pages_frame)
        
        # Вкладка 2: Настройки бота
        self.settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_frame, text="Персонализация")
        self.setup_settings_ui(self.settings_frame)
        
        # Блокируем родительское окно
        parent.attributes('-disabled', True)

    def _run_sync(self, coro):
        """Запуск асинхронного кода из синхронного контекста"""
        try:
            return asyncio.run(coro)
        except RuntimeError as e:
            self.add_log_message(f"Ошибка запуска event loop: {str(e)}", is_error=True)
            raise

    def setup_pages_ui(self, parent_frame):
        """Настройка интерфейса для работы с двумя типами страниц"""
        # Основной контейнер с разделением на дерево и редактор
        main_frame = ttk.Frame(parent_frame)
        main_frame.pack(fill="both", expand=True)
        
        # Левая панель - дерево страниц
        tree_frame = ttk.Frame(main_frame, width=250)
        tree_frame.pack(side="left", fill="y", padx=5, pady=5)
        
        # Правая панель - редактор
        editor_frame = ttk.Frame(main_frame)
        editor_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        # Дерево страниц
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.load_content_tree()
        
        # Кнопки управления страницами
        btn_frame = ttk.Frame(tree_frame)
        btn_frame.pack(fill="x", pady=5)
        
        ttk.Button(btn_frame, text="+ Текст", command=lambda: self.add_page("text")).pack(side="left", fill="x", expand=True)
        ttk.Button(btn_frame, text="+ Видео", command=lambda: self.add_page("video")).pack(side="left", fill="x", expand=True)
        ttk.Button(btn_frame, text="Удалить", command=self.delete_page).pack(side="left", fill="x", expand=True)
        
        # Общие элементы для всех страниц (перемещены выше)
        self.page_id_var = tk.StringVar()
        ttk.Label(editor_frame, text="ID страницы:").pack(anchor="w", pady=(0, 2))
        self.page_id_entry = ttk.Entry(editor_frame, textvariable=self.page_id_var)
        self.page_id_entry.pack(fill="x", pady=(0, 5))
        self._add_paste_support(self.page_id_entry)

        # Редактор страницы
        self.editor_container = ttk.Frame(editor_frame)
        self.editor_container.pack(fill="both", expand=True)
                
        # Фрейм для текстовых страниц
        self.text_page_frame = ttk.Frame(self.editor_container)
        
        # Текстовое поле
        self.text_editor = tk.Text(self.text_page_frame, height=10)
        self.text_editor.pack(fill="both", expand=True)
        
       # Загрузка изображений (максимум 3)
        self.image_paths = [None, None, None]
        self.image_buttons = []
        self.image_previews = []
        img_frame = ttk.Frame(self.text_page_frame)
        img_frame.pack(fill="x", pady=5)
        for i in range(3):
            # Контейнер для превью и кнопки
            container = ttk.Frame(img_frame)
            container.pack(side="left", padx=5)
            
           # Поле-превью на Canvas с точным контролем размеров
            preview = tk.Canvas(
                container,
                width=150,
                height=80,
                bg='white',
                highlightthickness=1,            # толщина рамки
                highlightbackground="#888",      # цвет рамки
                relief="solid"                   # (опционально, влияет на вид)
            )
            preview.pack()
            preview.create_text(75, 40, text="Нет изображения", fill="gray", font=("Arial", 10))
            self.image_previews.append(preview)
            
            # Кнопка добавления
            btn = ttk.Button(container, text=f"Добавить фото {i+1}", 
                           command=lambda idx=i: self.add_image(idx))
            btn.pack(pady=(5, 0))
            self.image_buttons.append(btn)
        
        # Кнопки (URL и навигация)
        self.buttons_frame = ttk.Frame(self.text_page_frame)
        self.buttons_frame.pack(fill="x", pady=5)
        
        # Кнопка 1 (URL)
        ttk.Label(self.buttons_frame, text="Кнопка 1 (URL):").pack(anchor="w")
        self.btn1_text = ttk.Entry(self.buttons_frame)
        self.btn1_text.pack(fill="x")
        ttk.Label(self.buttons_frame, text="URL:").pack(anchor="w")
        self.btn1_url = ttk.Entry(self.buttons_frame)
        self.btn1_url.pack(fill="x")
        
        # Кнопка 2 (Навигация)
        ttk.Label(self.buttons_frame, text="Кнопка 2 (Навигация):").pack(anchor="w")
        self.btn2_text = ttk.Entry(self.buttons_frame)
        self.btn2_text.pack(fill="x")
        ttk.Label(self.buttons_frame, text="ID страницы для перехода, после нажатия на кнопку:").pack(anchor="w")
        self.btn2_page = ttk.Entry(self.buttons_frame)
        self.btn2_page.pack(fill="x")
        
        # Фрейм для видео-сообщений
        self.video_page_frame = ttk.Frame(self.editor_container)
        
        # Видео-сообщение
        ttk.Label(self.video_page_frame, text="Видео-сообщение (кружок):").pack(anchor="w")
        self.video_path_var = tk.StringVar()
        ttk.Entry(self.video_page_frame, textvariable=self.video_path_var, state="readonly").pack(fill="x")
        ttk.Button(self.video_page_frame, text="Выбрать видео", command=self.select_video).pack(pady=5)
        
        # Кнопка сохранения
        ttk.Button(editor_frame, text="Сохранить страницу", command=self.save_page).pack(pady=10)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self._add_paste_support(self.text_editor)
        self._add_paste_support(self.btn1_text)
        self._add_paste_support(self.btn1_url)
        self._add_paste_support(self.btn2_text)
        self._add_paste_support(self.btn2_page)
        self.current_page_type = None
        self.current_page_id = None

    def add_image(self, index):
        """Добавление изображения для текстовой страницы"""
        file_path = filedialog.askopenfilename(filetypes=[("Изображения", "*.jpg *.jpeg *.png")])
        if file_path:
            # Создаем папку media если ее нет
            os.makedirs("media", exist_ok=True)
            
            # Создаем папку для страницы если ее нет
            page_media_dir = os.path.join("media", self.current_page_id)
            os.makedirs(page_media_dir, exist_ok=True)
            
            # Копируем файл в media
            filename = f"image_{index}_{os.path.basename(file_path)}"
            dest_path = os.path.join(page_media_dir, filename)
            shutil.copy(file_path, dest_path)
            
            self.image_paths[index] = dest_path
            self.image_buttons[index].config(text=f"Фото {index+1}: ✓")
            
            # Показываем миниатюру
            self.show_image_preview(index, dest_path)

    def show_image_preview(self, index, image_path):
        try:
            self.clear_image_preview(index)

            img = Image.open(image_path).convert("RGBA")

            canvas_width = 150
            canvas_height = 80

            # Масштабируем с сохранением пропорций
            img = ImageOps.contain(img, (canvas_width, canvas_height), method=Image.Resampling.LANCZOS)

            # Создаём белый фон и вставляем изображение по центру
            background = Image.new('RGBA', (canvas_width, canvas_height), (255, 255, 255, 255))
            x_offset = (canvas_width - img.width) // 2
            y_offset = (canvas_height - img.height) // 2
            background.paste(img, (x_offset, y_offset), img)

            photo = ImageTk.PhotoImage(background)

            canvas = self.image_previews[index]
            canvas.image_ref = photo  # сохраняем ссылку на изображение
            canvas.delete("all")  # очистка канваса
            canvas.create_image(0, 0, anchor="nw", image=photo)

        except Exception as e:
            self.clear_image_preview(index)

    def clear_image_preview(self, index):
        canvas = self.image_previews[index]
        canvas.delete("all")
        canvas.create_text(75, 40, text="Нет изображения", fill="gray", font=("Arial", 10))
        canvas.config(bg="white")

    def select_video(self):
        """Выбор видео для видео-сообщения"""
        file_path = filedialog.askopenfilename(filetypes=[("Видео", "*.mp4 *.mov")])
        if file_path:
            # Создаем папку media если ее нет
            os.makedirs("media", exist_ok=True)
            
            # Создаем папку для страницы если ее нет
            page_media_dir = os.path.join("media", self.current_page_id)
            os.makedirs(page_media_dir, exist_ok=True)
            
            # Копируем видео в media
            filename = f"video_{os.path.basename(file_path)}"
            dest_path = os.path.join(page_media_dir, filename)
            shutil.copy(file_path, dest_path)
            
            self.video_path_var.set(dest_path)

    def add_page(self, page_type):
        """Добавление новой страницы указанного типа"""
        page_id = simpledialog.askstring("Новая страница", "Введите ID страницы:")
        if not page_id:
            return

        if page_id in self.content_manager.content["pages"]:
            messagebox.showerror("Ошибка", "Страница с таким ID уже существует!")
            return

        # Создаем структуру страницы
        if page_type == "text":
            page_data = {
                "type": "text",
                "text": "",
                "images": [],
                "buttons": []
            }
        else:  # video
            page_data = {
                "type": "video",
                "video_path": ""
            }

        self.content_manager.content["pages"][page_id] = page_data
        self.content_manager.save_content()
        self.load_content_tree()
        self.tree.selection_set(page_id)

        if page_type == "video":
            # Очистка текстовых полей и изображений
            self.text_editor.delete("1.0", "end")
            for i in range(3):
                self.image_paths[i] = None
                self.image_buttons[i].config(text=f"Добавить фото {i+1}")
                self.image_previews[i].delete("all")
                self.image_previews[i].create_text(75, 40, text="Нет изображения", fill="gray", font=("Arial", 10))
            self.btn1_text.delete(0, "end")
            self.btn1_url.delete(0, "end")
            self.btn2_text.delete(0, "end")
            self.btn2_page.delete(0, "end")
            self.video_path_var.set("")
        else:  # page_type == "text"
            # Очистка видео-поля
            self.video_path_var.set("")

        self.on_tree_select(None)

    def save_page(self):
        """Сохранение текущей страницы"""
        if not self.current_page_id:
            messagebox.showwarning("Ошибка", "Не выбрана страница для сохранения")
            return
            
        new_id = self.page_id_var.get()
        page_data = self.content_manager.content["pages"][self.current_page_id]
        
        if page_data["type"] == "text":
            # Обновляем текст и изображения
            page_data.update({
                "text": self.text_editor.get("1.0", "end-1c"),
                "images": [path for path in self.image_paths if path],
                "buttons": []
            })
            
            # Добавляем кнопки если они заполнены
            if self.btn1_text.get() and self.btn1_url.get():
                page_data["buttons"].append({
                    "text": self.btn1_text.get(),
                    "url": self.btn1_url.get(),
                    "type": "url"
                })
                
            if self.btn2_text.get() and self.btn2_page.get():
                page_data["buttons"].append({
                    "text": self.btn2_text.get(),
                    "page": self.btn2_page.get(),
                    "type": "page"
                })
                
        else:  # video
            page_data["video_path"] = self.video_path_var.get()
        
        # Обновляем ID если он изменился
        if self.current_page_id != new_id:
            self.content_manager.content["pages"][new_id] = page_data
            del self.content_manager.content["pages"][self.current_page_id]
            self.current_page_id = new_id
            
        self.content_manager.save_content()
        self.load_content_tree()
        messagebox.showinfo("Успех", "Страница успешно сохранена")

    def on_tree_select(self, event):
        """Загрузка данных выбранной страницы в редактор"""
        selected = self.tree.selection()
        if not selected:
            return
            
        page_id = selected[0]
        self.current_page_id = page_id
        self.page_id_var.set(page_id)
        page_data = self.content_manager.get_page(page_id)
        self.current_page_type = page_data["type"]

        # Скрываем все фреймы и показываем нужный
        self.text_page_frame.pack_forget()
        self.video_page_frame.pack_forget()
        
        if page_data["type"] == "text":
            self.text_page_frame.pack(fill="both", expand=True)
            
            # Загружаем текст
            self.text_editor.delete("1.0", "end")
            self.text_editor.insert("1.0", page_data.get("text", ""))
            
            # Загружаем изображения
            self.image_paths = [None, None, None]
            for i in range(3):
                path = page_data.get("images", [])[i] if i < len(page_data.get("images", [])) else None
                self.image_paths[i] = path
                if path and os.path.exists(path):
                    self.image_buttons[i].config(text=f"Фото {i+1}: ✓")
                    self.show_image_preview(i, path)
                else:
                    self.image_buttons[i].config(text=f"Добавить фото {i+1}")
                    self.clear_image_preview(i)
            
            # Загружаем кнопки
            self.btn1_text.delete(0, "end")
            self.btn1_url.delete(0, "end")
            self.btn2_text.delete(0, "end")
            self.btn2_page.delete(0, "end")
            
            # Разделение кнопок по типу
            for btn in page_data.get("buttons", []):
                if btn.get("type") == "url":
                    self.btn1_text.insert(0, btn.get("text", ""))
                    self.btn1_url.insert(0, btn.get("url", ""))
                elif btn.get("type") == "page":
                    self.btn2_text.insert(0, btn.get("text", ""))
                    self.btn2_page.insert(0, btn.get("page", ""))
                    
        else:  # video
            self.video_page_frame.pack(fill="both", expand=True)
            self.video_path_var.set(page_data.get("video_path", ""))

    def delete_page(self):
        """Удаление текущей страницы с подтверждением"""
        if not self.current_page_id:
            messagebox.showwarning("Ошибка", "Не выбрана страница для удаления")
            return
            
        if messagebox.askyesno("Подтверждение", f"Удалить страницу {self.current_page_id}?"):
            # Удаляем связанные медиафайлы
            page_data = self.content_manager.content["pages"][self.current_page_id]
            
            if page_data["type"] == "text":
                for img_path in page_data.get("images", []):
                    try:
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    except:
                        pass
            elif page_data["type"] == "video":
                try:
                    if os.path.exists(page_data.get("video_path", "")):
                        os.remove(page_data["video_path"])
                except:
                    pass
            
            # Сбрасываем превью
            for i in range(3):
                self.image_previews[i].delete("all")
                self.image_previews[i].create_text(75, 40, text="Нет изображения", fill="gray", font=("Arial", 10))

            # Удаляем страницу
            del self.content_manager.content["pages"][self.current_page_id]
            self.content_manager.save_content()
            
            # Сбрасываем редактор
            self.current_page_id = None
            self.page_id_var.set("")
            self.text_editor.delete("1.0", "end")
            self.video_path_var.set("")
            for i in range(3):
                self.image_paths[i] = None
                self.image_buttons[i].config(text=f"Добавить фото {i+1}")
            
            self.load_content_tree()

    def setup_settings_ui(self, parent_frame):
        """Настройка интерфейса персонализации бота"""
        # Основной контейнер
        main_frame = ttk.Frame(parent_frame)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Область контента (grid)
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill="both", expand=True)
        
        # Настройка колонок (метки выравниваются вправо)
        content_frame.columnconfigure(0, weight=1, minsize=150)  # Колонка меток
        content_frame.columnconfigure(1, weight=2)               # Колонка полей ввода
        
        # Поля ввода с выравниванием меток вправо
        ttk.Label(content_frame, text="Название бота:", anchor="e").grid(
            row=0, column=0, sticky="e", pady=5, padx=(0, 10))

        self.bot_name_entry = ttk.Entry(content_frame)
        self.bot_name_entry.grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(content_frame, text="Описание бота:", anchor="e").grid(
            row=1, column=0, sticky="e", pady=5, padx=(0, 10))

        self.bot_desc_entry = ttk.Entry(content_frame)
        self.bot_desc_entry.grid(row=1, column=1, sticky="ew", pady=5)

        ttk.Label(content_frame, text="Приветственное сообщение:", anchor="e").grid(
            row=2, column=0, sticky="ne", pady=5, padx=(0, 10))

        self.bot_start_msg_text = tk.Text(content_frame, height=5, wrap="word")
        self.bot_start_msg_text.grid(row=2, column=1, sticky="ew", pady=5)

        ttk.Label(content_frame, text="Токен бота:", anchor="e").grid(
            row=3, column=0, sticky="e", pady=5, padx=(0, 10))

        self.bot_token_entry = ttk.Entry(content_frame)
        self.bot_token_entry.grid(row=3, column=1, sticky="ew", pady=5)

        # ДОБАВЬ ЭТО: Поддержка Ctrl+C/Ctrl+V для всех полей
        self._add_paste_support(self.bot_name_entry)
        self._add_paste_support(self.bot_desc_entry)
        self._add_paste_support(self.bot_start_msg_text)
        self._add_paste_support(self.bot_token_entry)
        
        # Блок аватарки
        """
        ttk.Label(content_frame, text="Аватарка бота:", anchor="e").grid(
            row=4, column=0, sticky="ne", pady=5, padx=(0, 10))
        
        avatar_container = ttk.Frame(content_frame)
        avatar_container.grid(row=4, column=1, sticky="nsew", pady=5)
        
        self.avatar_canvas = tk.Canvas(avatar_container, 
                                     width=256, 
                                     height=256,
                                     bg="#f0f0f0",
                                     relief="solid",
                                     borderwidth=1)
        self.avatar_canvas.pack()
        
        # Метка "Путь к фото" с выравниванием вправо
        ttk.Label(content_frame, text="Путь к фото:", anchor="e").grid(
            row=5, column=0, sticky="e", pady=5, padx=(0, 10))
        
        path_frame = ttk.Frame(content_frame)
        path_frame.grid(row=5, column=1, sticky="ew", pady=5)
        
        self.bot_photo_path = tk.StringVar()
        ttk.Entry(path_frame, 
                 textvariable=self.bot_photo_path, 
                 state="readonly").pack(side="left", fill="x", expand=True)
        
        ttk.Button(path_frame, 
                  text="Выбрать...", 
                  command=self.select_bot_photo).pack(side="right")
        """
        # Кнопка сохранения (внизу справа)
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(10, 0))
        
        left_spacer = ttk.Frame(btn_frame)
        left_spacer.pack(side="left", expand=True, fill="x")
        
        ttk.Button(btn_frame, 
                  text="Сохранить настройки", 
                  command=self.save_bot_settings).pack(side="right")
        
        self.load_bot_settings()

    def _add_paste_support(self, widget):
        """Добавляет поддержку вставки с учётом раскладки клавиатуры"""
        # Универсальная комбинация для вставки (Ctrl+V или Ctrl+м)
        widget.bind("<Control-KeyPress>", lambda e: self._handle_ctrl_v(e, widget))
        
        # Контекстное меню (ПКМ)
        if isinstance(widget, tk.Text):
            widget.bind("<Button-3>", lambda e: self._show_context_menu(e, widget, is_text=True))
        else:
            widget.bind("<Button-3>", lambda e: self._show_context_menu(e, widget, is_text=False))

    def _handle_ctrl_v(self, event, widget):
        """Обработчик Ctrl+V независимо от раскладки"""
        if event.keysym.lower() == 'v' or event.keysym.lower() == 'м':  # 'м' — это 'v' в русской раскладке
            self._handle_paste(widget)
        return "break"  # Блокируем дальнейшую обработку

    def _handle_paste(self, widget):
        """Вставляет текст из буфера обмена"""
        try:
            text = self.clipboard_get()
            if isinstance(widget, tk.Text):
                widget.insert(tk.INSERT, text)
            else:  # Для Entry
                widget.delete(0, tk.END)  # Очищаем перед вставкой
                widget.insert(0, text)
        except tk.TclError:
            pass  # Буфер обмена пуст

    def _show_context_menu(self, event, widget, is_text):
        """Контекстное меню с копированием/вставкой"""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Вставить", command=lambda: self._handle_paste(widget))
        if is_text:
            menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        else:
            menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        menu.tk.call("tk_popup", menu, event.x_root, event.y_root)

    def update_avatar_preview(self, image_path):
        """Обновление превью аватарки"""
        try:
            from PIL import Image, ImageTk
            
            img = Image.open(image_path)
            img.thumbnail((256, 256), Image.Resampling.LANCZOS)
            
            # Создаем квадратное изображение
            bg = Image.new('RGB', (256, 256), '#f0f0f0')
            offset = ((256 - img.width) // 2, (256 - img.height) // 2)
            bg.paste(img, offset)
            
            photo = ImageTk.PhotoImage(bg)
            self.avatar_canvas.delete("all")
            self.avatar_canvas.create_image(128, 128, image=photo)
            self.avatar_canvas.image = photo  # Сохраняем ссылку!
            
        except Exception as e:
            self.avatar_canvas.delete("all")
            self.avatar_canvas.create_text(
                128, 128, 
                text=f"Ошибка загрузки:\n{str(e)}",
                fill="red",
                font=("Arial", 9)
            )

    def load_bot_settings(self):
        """Загрузка настроек бота, включая аватарку"""
        settings = self.content_manager.get_bot_settings()
        
        # Заполняем поля
        self.bot_name_entry.delete(0, tk.END)
        self.bot_name_entry.insert(0, settings.get("name", ""))
        
        self.bot_desc_entry.delete(0, tk.END)
        self.bot_desc_entry.insert(0, settings.get("description", ""))
        
        self.bot_start_msg_text.delete("1.0", tk.END)
        self.bot_start_msg_text.insert("1.0", settings.get("start_message", ""))
        
        self.bot_token_entry.delete(0, tk.END)
        self.bot_token_entry.insert(0, settings.get("token", ""))
        
        # Загрузка аватарки
        """
        avatar_path = settings.get("photo_path", "")
        self.bot_photo_path.set(avatar_path)
        
        if avatar_path and os.path.exists(avatar_path):
            self.update_avatar_preview(avatar_path)
        else:
            self.avatar_canvas.delete("all")
            self.avatar_canvas.create_text(
                128, 128, 
                text="Изображение не выбрано",
                fill="#999999",
                font=("Arial", 10)
            )
        """
    def save_bot_settings(self):
        """Сохранение настроек бота с валидацией и отправкой в Telegram API"""
        try:
            # 1. Валидация обязательных полей
            if not self.bot_token_entry.get():
                messagebox.showwarning("Ошибка", "Токен не может быть пустым!")
                return

            # 2. Подготовка данных
            new_settings = {
                "name": self.bot_name_entry.get(),
                "description": self.bot_desc_entry.get(),
                "start_message": self.bot_start_msg_text.get("1.0", "end-1c"),
                "token": self.bot_token_entry.get(),
                "photo_path": self.content_manager.content.get("bot_settings", {}).get("photo_path", "")
            }

            # 3. Сохраняем локально
            self.content_manager.content["bot_settings"] = new_settings
            self.content_manager.save_content()

            # 4. Обновляем глобальный токен
            global TOKEN
            TOKEN = new_settings["token"]

            # 5. Отправляем все данные в Telegram API
            try:
                # Получаем родительское приложение
                parent_app = self.parent.winfo_toplevel().app
                parent_app._run_sync(self._update_telegram_bot_info(new_settings))
                messagebox.showinfo("Успех", "Все настройки успешно сохранены и отправлены в Telegram!")
            except Exception as e:
                messagebox.showwarning("Частичный успех", 
                                    f"Настройки сохранены локально, но не отправлены в Telegram:\n{str(e)}")

            # 6. Перезагружаем бота если он запущен
            if hasattr(parent_app, 'bot_running') and parent_app.bot_running:
                parent_app.restart_bot()

        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось сохранить настройки:\n{str(e)}")

    def restart_bot(self):
        """Плавная перезагрузка бота"""
        try:
            if self.bot_running:
                logger.info("Инициирована перезагрузка бота...")
                self.stop_bot()
                # Даем время на остановку перед запуском
                self.root.after(2000, self.start_bot)
        except Exception as e:
            logger.error("Ошибка перезагрузки бота: %s", str(e), exc_info=True)

    async def _update_telegram_bot_info(self, settings):
        """Обновление информации бота в Telegram API с правильным распределением текста"""
        try:
            bot = Bot(settings["token"])
            
            # 1. Устанавливаем имя бота
            await bot.set_my_name(settings["name"])
            
            # 2. Основное описание (description) - приветственное сообщение
            await bot.set_my_description(settings["start_message"])
            
            # 3. Короткое описание (about) - дополнительная информация
            short_desc = settings["description"][:100]  # Ограничение Telegram - 120 символов
            await bot.set_my_short_description(short_desc)
            
            # 4. Настройка команд меню
            commands = [
                ("start", settings["start_message"][:256]),
                ("help", settings["description"][:256] if settings["description"] else "Помощь")
            ]
            await bot.set_my_commands(commands)
            
            # 5. Обновление фото (если указано)
            if settings.get("photo_path") and os.path.exists(settings["photo_path"]):
                with open(settings["photo_path"], 'rb') as photo:
                    await bot.set_my_photo(photo=photo)
            
            logger.info("Настройки бота успешно обновлены в Telegram API")
            
        except InvalidToken:
            raise Exception("Неверный токен бота")
        except NetworkError:
            raise Exception("Ошибка сети. Проверьте подключение")
        except Exception as e:
            raise Exception(f"Ошибка Telegram API: {str(e)}")

        def restart_bot(self):
            """Плавная перезагрузка бота"""
            try:
                if self.bot_running:
                    logger.info("Инициирована перезагрузка бота...")
                    self.stop_bot()
                    self.start_bot()
            except Exception as e:
                logger.error("Ошибка перезагрузки бота: %s", str(e), exc_info=True)

    def on_close(self):
        """Обработчик закрытия окна"""
        try:
            if self.parent.winfo_exists():
                self.parent.attributes('-disabled', False)
        except:
            pass
        self.destroy()
        
    def setup_ui(self):
        self.title("Редактор контента")
        self.geometry("1000x700")  # Увеличили размер окна
        
        # Фрейм для дерева контента
        tree_frame = ttk.Frame(self)
        tree_frame.pack(side="left", fill="y", padx=5, pady=5)
        
        # Дерево контента
        self.tree = ttk.Treeview(tree_frame)
        self.tree.pack(fill="both", expand=True)
        
        # Заполняем дерево
        self.load_content_tree()
        
        # Фрейм для редактирования
        self.edit_frame = ttk.Frame(self)
        self.edit_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        # Элементы редактора
        ttk.Label(self.edit_frame, text="ID страницы:").pack(anchor="w")
        self.page_id_entry = ttk.Entry(self.edit_frame)
        self.page_id_entry.pack(fill="x")
        
        ttk.Label(self.edit_frame, text="Текст:").pack(anchor="w")
        self.text_editor = tk.Text(self.edit_frame, height=10)
        self.text_editor.pack(fill="both", expand=True)
        
        # Кнопки
        btn_frame = ttk.Frame(self.edit_frame)
        btn_frame.pack(fill="x", pady=5)
        
        ttk.Button(btn_frame, text="Сохранить", command=self.save_page).pack(side="left")
        ttk.Button(btn_frame, text="Добавить страницу", command=self.add_page).pack(side="left")
        ttk.Button(btn_frame, text="Удалить страницу", command=self.delete_page).pack(side="left")
        
        # Привязываем выбор элемента в дереве
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
    
    def load_content_tree(self):
        """Загружает структуру контента в дерево"""
        self.tree.delete(*self.tree.get_children())
        for page_id, page_data in self.content_manager.content["pages"].items():
            if page_data.get("type") == "text":
                preview = page_data.get("text", "")[:50] + "..."
            else:
                preview = "[видео страница]"
            self.tree.insert("", "end", iid=page_id, text=page_id, values=(preview,))
    def validate_page_id(self, page_id):
        """Проверяет ID страницы на допустимые символы"""
        import re
        return bool(re.match(r'^[a-zA-Z0-9_\-]+$', page_id))

    def setup_bot_settings_ui(self, parent_frame):
        """Настройка интерфейса персонализации бота"""
        # Поля для ввода
        ttk.Label(parent_frame, text="Название бота:").pack(anchor="w")
        self.bot_name_entry = ttk.Entry(parent_frame)
        self.bot_name_entry.pack(fill="x")

        ttk.Label(parent_frame, text="Описание бота:").pack(anchor="w")
        self.bot_desc_entry = ttk.Entry(parent_frame)
        self.bot_desc_entry.pack(fill="x")

        ttk.Label(parent_frame, text="Приветственное сообщение (/start):").pack(anchor="w")
        self.bot_start_msg_text = tk.Text(parent_frame, height=5)
        self.bot_start_msg_text.pack(fill="x")

        ttk.Label(parent_frame, text="Токен бота:").pack(anchor="w")
        self.bot_token_entry = ttk.Entry(parent_frame)
        self.bot_token_entry.pack(fill="x")

        # Кнопка загрузки аватарки
        ttk.Label(parent_frame, text="Аватарка бота:").pack(anchor="w")
        self.bot_photo_path = tk.StringVar()
        ttk.Entry(parent_frame, textvariable=self.bot_photo_path, state="readonly").pack(fill="x", side="left", expand=True)
        ttk.Button(parent_frame, text="Выбрать файл", command=self.select_bot_photo).pack(side="left")

        # Кнопка сохранения
        ttk.Button(parent_frame, text="Сохранить настройки", command=self.save_bot_settings).pack(pady=10)

        # Загружаем текущие настройки
        self.load_bot_settings()

    def select_bot_photo(self):
        """Выбор файла аватарки"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.gif")]
        )
        if file_path:
            self.bot_photo_path.set(file_path)
            self.update_avatar_preview(file_path)  # Важно: этот вызов должен быть!

class ContentManager:
    def __init__(self, config_path: str = "content.json"):
        self.config_path = config_path
        self.content = self.load_content()
    
    def get_bot_settings(self) -> dict:
        """Возвращает настройки бота"""
        return self.content.get("bot_settings", {})

    def update_bot_settings(self, new_settings: dict):
        """Обновляет настройки бота"""
        self.content["bot_settings"] = new_settings
        self.save_content()

    def load_content(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            # Создаем базовую структуру
            content = {
                "bot_settings": {},
                "pages": {
                    "start": {
                        "type": "text",
                        "text": "Добро пожаловать!",
                        "images": [],
                        "buttons": []
                    }
                }
            }
            # Сохраняем в файл
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            return content

        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    def get_page(self, page_id: str) -> Dict[str, Any]:
        return self.content["pages"].get(page_id)
        
    def save_content(self):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.content, f, ensure_ascii=False, indent=2)

class TelegramBotApp:
    def __init__(self, root):
        self._shutting_down = False
        self._finalized = False
        self.user_locks = set()
        self.active_tasks = {}
        self.root = root
        self.root.app = self
        self.application = None
        self.bot_running = False
        self.last_error = ""
        self.connection_status = False
        self.log_history = []
        self.last_connection_status = None
        self.content_manager = ContentManager()
        self._stop_event = threading.Event()  # Для координации остановки
        self._stop_lock = threading.Lock()
        self._stop_requested = False
        self._is_stopping = False
        self._bot_loop = None
        self.tray_icon = None
        self.tray_image = PILImage.open("icon.ico")

        self.load_bot_settings()
        self.center_window(800, 600)  # Центрирование окна
        # Сначала инициализируем все UI компоненты
        self._init_ui_components()

        self.setup_ui()
        
        # Затем настраиваем остальные компоненты
        self.setup_file_logging()
        self._setup_keyboard_shortcuts()
        self.start_status_check()
        self.check_connection_initial()

    def center_window(self, width, height):
        """Центрирует главное окно"""
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def minimize_to_tray(self):
        self.root.withdraw()
        if self.tray_icon is None:
            menu = TrayMenu(
                TrayItem('Открыть', lambda icon, item: self.show_window()),
                TrayItem('Выход', lambda icon, item: self.exit_app())
            )
            self.tray_icon = TrayIcon("TelegramBot", self.tray_image, menu=menu)
            Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self):
        self.root.after(0, self.root.deiconify)
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

    def exit_app(self):
        try:
            # Быстрый выход - просто завершаем процесс
            os._exit(0)
                
        except Exception as e:
            # Аварийный выход в любом случае
            os._exit(1)

    
    def load_bot_settings(self):
        """Загружает настройки бота из content.json"""
        settings = self.content_manager.get_bot_settings()
        global TOKEN
        TOKEN = settings.get("token", TOKEN)  # Обновляем токен, если он есть в настройках

    async def show_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page_id: str):
        """Показ страницы с учетом нового формата"""
        page = self.content_manager.get_page(page_id)
        if not page:
            await update.message.reply_text("Страница не найдена!")
            return
        
        chat_id = update.effective_chat.id
        
        if page["type"] == "text":
            # Отправка текста с изображениями
            text = page["text"]
            images = page.get("images", [])
            
            # Формируем клавиатуру из кнопок
            keyboard = []
            for btn in page.get("buttons", []):
                if btn["type"] == "url":
                    keyboard.append([InlineKeyboardButton(btn["text"], url=btn["url"])])
                else:
                    keyboard.append([InlineKeyboardButton(btn["text"], callback_data=btn["page"])])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            if images:
                # Отправляем медиагруппу с первым изображением и текстом
                media = []
                for i, img_path in enumerate(images):
                    if os.path.exists(img_path):
                        with open(img_path, 'rb') as photo:
                            if i == 0:
                                media.append(InputMediaPhoto(photo, caption=text))
                            else:
                                media.append(InputMediaPhoto(photo))
                
                if media:
                    await context.bot.send_media_group(chat_id=chat_id, media=media)
                    if reply_markup:
                        await context.bot.send_message(chat_id=chat_id, text="Дополнительные действия:", reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
                
        elif page["type"] == "video":
            # Отправка видео-сообщения
            if os.path.exists(page["video_path"]):
                with open(page["video_path"], 'rb') as video:
                    await context.bot.send_video_note(chat_id=chat_id, video_note=video)
            else:
                await context.bot.send_message(chat_id=chat_id, text="Видео не найдено")


    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.callback_query.from_user.id

        old_task = self.active_tasks.get(user_id)
        if old_task and not old_task.done():
            old_task.cancel()

        task = asyncio.create_task(self._process_button(update, context))
        self.active_tasks[user_id] = task

    async def _process_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            start_page_id = query.data
            await self.continue_sequence_from(update, context, start_page_id)
        except asyncio.CancelledError:
            pass

    async def continue_sequence_from(self, update: Update, context: ContextTypes.DEFAULT_TYPE, start_page_id: str):
        """Показ страниц начиная с указанного ID, с паузой и остановкой на кнопке"""
        pages = self.content_manager.content.get("pages", {})
        keys = list(pages.keys())

        if start_page_id not in keys:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Страница не найдена.")
            return

        start_index = keys.index(start_page_id)

        for page_id in keys[start_index:]:
            page_data = pages[page_id]
            await self.show_page(update, context, page_id)
            await asyncio.sleep(0.1)

            if page_data.get("type") == "text":
                for btn in page_data.get("buttons", []):
                    if btn.get("type") == "page":
                        return  # Остановить, дожидаясь следующего нажатия

    async def handle_start_sequence(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start — показывает страницы по порядку с паузами"""
        pages = self.content_manager.content.get("pages", {})
        chat_id = update.effective_chat.id

        for page_id, page_data in pages.items():
            await self.show_page(update, context, page_id)

            # ⏱ Пауза 1 секунда между сообщениями
            await asyncio.sleep(1)

            # Если есть кнопка навигации — остановить цепочку
            if page_data.get("type") == "text":
                for btn in page_data.get("buttons", []):
                    if btn.get("type") == "page":
                        return  # Остановить отправку

    def _init_ui_components(self):
        """Инициализация всех UI компонентов"""
        self.status_frame = tk.LabelFrame(self.root, text="Состояние системы", padx=10, pady=10)
        self.error_frame = tk.LabelFrame(self.root, text="Журнал событий", padx=10, pady=10)
        self.button_panel = tk.Frame(self.root)
        
        self.status_label = tk.Label(self.status_frame, text="Проверяем подключение...", font=("Helvetica", 12))
        self.error_text = tk.Text(
            self.error_frame,
            height=15,
            wrap=tk.WORD,
            font=("Consolas", 9),
            padx=5,
            pady=5,
            state=tk.NORMAL
        )
        self.error_text.tag_config("error", foreground="red")
        
        self._add_paste_support(self.error_text)

        self.copy_button = tk.Button(
            self.button_panel,
            text="Копировать журнал",
            command=self.copy_log_to_clipboard,
            width=15
        )
        self.clear_button = tk.Button(
            self.button_panel,
            text="Очистить журнал",
            command=self.clear_log,
            width=15
        )
        self.start_button = tk.Button(
            self.button_panel, 
            text="Запустить бота", 
            command=self.start_bot,
            state=tk.DISABLED,
            width=15
        )
        self.stop_button = tk.Button(
            self.button_panel, 
            text="Остановить бота", 
            command=self.stop_bot,
            state=tk.DISABLED,
            width=15
        )
        self.refresh_button = tk.Button(
            self.button_panel, 
            text="Проверить сеть", 
            command=self.force_check,
            width=15
        )
        self.edit_button = tk.Button(
            self.button_panel,
            text="Редактировать контент",
            command=self.open_editor,
            width=20
        )

    def _add_paste_support(self, widget):
        """Добавляет поддержку вставки с учётом раскладки клавиатуры"""
        # Универсальная комбинация для вставки (Ctrl+V или Ctrl+м)
        widget.bind("<Control-KeyPress>", lambda e: self._handle_ctrl_v(e, widget))
        
        # Контекстное меню (ПКМ)
        if isinstance(widget, tk.Text):
            widget.bind("<Button-3>", lambda e: self._show_context_menu(e, widget, is_text=True))
        else:
            widget.bind("<Button-3>", lambda e: self._show_context_menu(e, widget, is_text=False))

    def _handle_ctrl_v(self, event, widget):
        """Обработчик Ctrl+V независимо от раскладки"""
        if event.keysym.lower() == 'v' or event.keysym.lower() == 'м':  # 'м' — это 'v' в русской раскладке
            self._handle_paste(widget)
        return "break"  # Блокируем дальнейшую обработку

    def _handle_paste(self, widget):
        """Вставляет текст из буфера обмена"""
        try:
            text = self.root.clipboard_get()
            if isinstance(widget, tk.Text):
                widget.insert(tk.INSERT, text)
            else:  # Для Entry
                widget.delete(0, tk.END)  # Очищаем перед вставкой
                widget.insert(0, text)
        except tk.TclError:
            pass  # Буфер обмена пуст

    def _show_context_menu(self, event, widget, is_text):
        """Контекстное меню с копированием/вставкой"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Вставить", command=lambda: self._handle_paste(widget))
        if is_text:
            menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        else:
            menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        menu.tk.call("tk_popup", menu, event.x_root, event.y_root)

    def setup_ui(self):
        """Настройка размещения UI компонентов"""
        self.root.title("Телеграм Бот")
        self.root.geometry("800x600")  # Увеличили размер окна
        self.root.minsize(800, 600)  # Минимальный размер окна
        self.root.resizable(True, True)

        self.status_frame.pack(pady=10, fill="x", padx=10)
        self.status_label.pack(pady=5)
        
        self.error_frame.pack(pady=10, fill="both", expand=True, padx=10)
        scrollbar = tk.Scrollbar(self.error_frame, command=self.error_text.yview)
        self.error_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.error_text.pack(fill="both", expand=True)
        
        self.button_panel.pack(pady=10, fill="x", padx=10)
        self.copy_button.pack(side="left", padx=5)
        self.clear_button.pack(side="left", padx=5)
        self.start_button.pack(side="left", padx=5)
        self.stop_button.pack(side="left", padx=5)
        self.refresh_button.pack(side="left", padx=5)
        self.edit_button.pack(side="left", padx=5)


    def get_timestamp(self):
        """Возвращает строку с текущим временем"""
        now = datetime.now()
        return now.strftime("[%Y-%m-%d %H:%M:%S.%f")[:-3] + "]"

    def center_window_on_screen(self, window, width=None, height=None):
        """Центрирует окно относительно экрана с учетом taskbar"""
        window.update_idletasks()
        
        # Получаем доступную область экрана (исключая панель задач)
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        
        # Размеры окна
        if width is None:
            width = window.winfo_width()
        if height is None:
            height = window.winfo_height()
        
        # Вычисляем позицию с учетом видимой области
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        
        # Устанавливаем геометрию
        window.geometry(f'{width}x{height}+{x}+{y}')

    def add_log_message(self, message, is_error=False):
        """Добавляет сообщение в журнал"""
        timestamp = self.get_timestamp()
        log_entry = f"{timestamp} {message}"
        self.log_history.append((log_entry, is_error))
        
        # Дублируем в файл через стандартный logging
        if is_error:
            logger.error(message)
        else:
            logger.info(message)
            
        self.update_log_display()

    def update_log_display(self):
        """Обновляет отображение журнала"""
        self.error_text.config(state=tk.NORMAL)
        self.error_text.delete(1.0, tk.END)
        
        for log_entry, is_error in self.log_history:
            self.error_text.insert(tk.END, log_entry + "\n")
            if is_error:
                start_pos = self.error_text.index("end-2l linestart")
                end_pos = self.error_text.index("end-2l lineend")
                self.error_text.tag_add("error", start_pos, end_pos)
        
        self.error_text.see(tk.END)
        self.error_text.config(state=tk.DISABLED)

    def update_ui_state(self):
        """Обновляет состояние интерфейса"""
        if self.connection_status:
            self.status_label.config(text="✅ Подключение установлено", fg="green")
            self.start_button.config(state=tk.DISABLED if self.bot_running else tk.NORMAL)
            self.stop_button.config(state=tk.NORMAL if self.bot_running else tk.DISABLED)
        else:
            self.status_label.config(text="❌ Нет подключения", fg="red")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)

    def _setup_keyboard_shortcuts(self):
        """Настройка горячих клавиш"""
        self.root.bind('<Control-c>', self.copy_selected_text)
        self.root.bind('<Control-C>', self.copy_selected_text)

    def copy_selected_text(self, event=None):
        """Копирование выделенного текста"""
        try:
            selected_text = self.error_text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
        except tk.TclError:
            self.copy_log_to_clipboard()
        return "break"

    def copy_log_to_clipboard(self):
        """Копирование всего журнала"""
        log_content = "\n".join([entry[0] for entry in self.log_history])
        if log_content:
            self.root.clipboard_clear()
            self.root.clipboard_append(log_content)
            messagebox.showinfo("Успешно", "Журнал скопирован в буфер обмена!")
            
            if platform.system() == "Linux":
                try:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=log_content.encode("utf-8"))
                except FileNotFoundError:
                    pass

    def clear_log(self):
        """Очистка журнала"""
        self.log_history = []
        self.update_log_display()
        self.add_log_message("Журнал очищен")

    def open_editor(self):
        """Открытие модального редактора контента с центрированием на экране"""
        if getattr(self, '_editor_open', False):
            return

        try:
            self._editor_open = True
            editor = ContentEditor(self.root, self.content_manager)
            
            # Устанавливаем размеры редактора (можно настроить под ваши нужды)
            editor.geometry("1000x700")  # Ширина x Высота
            
            # Центрируем на экране
            self.center_window_on_screen(editor, 1000, 700)
            
            # Ждем закрытия редактора
            self.root.wait_window(editor)
        except Exception as e:
            logger.error(f"Ошибка открытия редактора: {e}", exc_info=True)
            messagebox.showerror("Ошибка", f"Ошибка при открытии редактора:\n{str(e)}")
        finally:
            self._editor_open = False

    def setup_file_logging(self):
        """Настройка файлового логирования"""
        os.makedirs("logs", exist_ok=True)
        self.cleanup_old_logs()
        
        log_filename = f"logs/бот_{datetime.now().strftime('%Y-%m-%d')}.log"
        
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        
        logging.getLogger().addHandler(file_handler)

    def cleanup_old_logs(self):
        """Удаление старых логов"""
        try:
            now = datetime.now()
            cutoff_date = now - timedelta(days=90)
            
            log_files = glob.glob("logs/бот_*.log")
            
            for log_file in log_files:
                try:
                    date_str = os.path.basename(log_file).split('_')[1].split('.')[0]
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    if file_date < cutoff_date:
                        os.remove(log_file)
                        logger.info(f"Удален старый лог-файл: {log_file}")
                except (ValueError, IndexError) as e:
                    logger.warning(f"Не удалось обработать файл {log_file}: {str(e)}")
        except Exception as e:
            logger.error(f"Ошибка при очистке старых логов: {str(e)}")

    def _run_sync(self, coro):
        """Запуск асинхронного кода из синхронного контекста"""
        try:
            return asyncio.run(coro)
        except RuntimeError as e:
            self.add_log_message(f"Ошибка запуска event loop: {str(e)}", is_error=True)

    async def _run_async_task(self, coro):
        """Запуск асинхронной задачи"""
        try:
            return await coro
        except Exception as e:
            self.add_log_message(f"Ошибка в асинхронной задаче: {str(e)}", is_error=True)
            raise

    def start_status_check(self):
        """Запуск периодической проверки статуса"""
        async def check():
            while True:
                try:
                    await self.check_connection()
                    await asyncio.sleep(60)
                except Exception as e:
                    self.add_log_message(f"Ошибка проверки статуса: {str(e)}", is_error=True)
        
        Thread(target=lambda: asyncio.run(check())).start()

    def check_connection_initial(self):
        """Первоначальная проверка подключения"""
        try:
            self.add_log_message("Проверка подключения к Telegram...")
            self._run_sync(self.check_connection())
        except Exception as e:
            self.add_log_message(f"Ошибка при первоначальной проверке: {str(e)}", is_error=True)

    async def check_connection(self):
        """Проверка соединения с Telegram"""
        try:
            bot = Bot(TOKEN)
            info = await bot.get_me(read_timeout=20)
            
            if not self.connection_status or self.last_connection_status != info.username:
                self.connection_status = True
                self.last_connection_status = info.username
                self.add_log_message(f"Успешное подключение к боту @{info.username}")
            
        except InvalidToken:
            self.last_error = "⛔ Неверный токен бота!"
            self.add_log_message(self.last_error, is_error=True)
        except NetworkError:
            self.last_error = "🌐 Проблемы с интернет-соединением"
            self.add_log_message(self.last_error, is_error=True)
        except Exception as e:
            self.last_error = f"❌ Неизвестная ошибка: {type(e).__name__}: {str(e)}"
            self.add_log_message(self.last_error, is_error=True)
        finally:
            self.root.after(0, self.update_ui_state)

    def force_check(self):
        """Принудительная проверка соединения"""
        try:
            self._run_sync(self.check_connection())
        except Exception as e:
            self.add_log_message(f"Ошибка при проверке: {str(e)}", is_error=True)

    def handle_error(self, error):
        """Обработка ошибок"""
        if isinstance(error, (InvalidToken, TelegramError)) and "Unauthorized" in str(error):
            self.last_error = "⛔ Неверный токен или нет доступа"
        elif isinstance(error, NetworkError):
            self.last_error = "🌐 Проблемы с интернет-соединением"
        else:
            self.last_error = f"⚠️ Ошибка: {type(error).__name__}: {str(error)}"
        
        self.add_log_message(self.last_error, is_error=True)
        self.connection_status = False
        self.update_ui_state()
        self.stop_bot()

    def start_bot(self):
        """Запуск бота в отдельном потоке"""
        if self.bot_running:
            return

        # СБРАСЫВАЕМ ФЛАГИ ПЕРЕД КАЖДЫМ ЗАПУСКОМ
        with self._stop_lock:
            self.bot_running = True
            self._is_stopping = False
            self._stop_requested = False
            self._finalized = False

        Thread(target=self._run_bot_wrapper, daemon=True).start()
        self.update_ui_state()

    def _run_bot_wrapper(self):
        """Обертка для запуска бота в потоке"""
        try:
            asyncio.run(self._run_bot_async())
        except Exception as ex:
            error_msg = f"Ошибка при запуске бота: {str(ex)}"
            self.root.after(0, lambda msg=error_msg: self.add_log_message(msg, is_error=True))
    
    async def _run_bot_async(self):
        """Основной цикл работы бота с graceful shutdown"""
        try:
            self._bot_loop = asyncio.get_running_loop()
            request = HTTPXRequest(connect_timeout=20, read_timeout=120)
            self.application = Application.builder().token(TOKEN).request(request).build()
            self.setup_handlers()
            
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            self.root.after(0, lambda: self.add_log_message("Бот успешно запущен"))
            
            # Основной цикл с проверкой флага остановки
            while self.bot_running:
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.info("Работа бота была отменена")
        except Exception as err:
            error_msg = f"Ошибка в работе бота: {str(err)}"
            logger.error(error_msg, exc_info=True)
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(0, lambda: self.add_log_message(error_msg, is_error=True))
        finally:
            # Корректная остановка при выходе из цикла
            await self._graceful_shutdown()

    async def _graceful_shutdown(self):
        """Корректное завершение работы бота"""
        try:
            if self.application:
                logger.info("Начало graceful shutdown...")
                
                # 1. Останавливаем приложение
                try:
                    await self.application.stop()
                    logger.info("Приложение остановлено")
                except Exception as ex:
                    logger.error(f"Ошибка при остановке приложения: {ex}")
                
                # 2. Завершаем работу приложения с обработкой ошибки Updater
                try:
                    await self.application.shutdown()
                    logger.info("Приложение завершено")
                except Exception as ex:
                    if "Updater is still running" in str(ex):
                        logger.warning("Updater не был полностью остановлен - это нормально")
                        # Это безопасно, так как приложение уже остановлено
                    else:
                        logger.error(f"Ошибка при завершении работы: {ex}")
                    
        except Exception as ex:
            logger.error(f"Ошибка при graceful shutdown: {str(ex)}", exc_info=True)
        finally:
            # Всегда выполняем финализацию
            self._finalize_shutdown()

    async def _safe_shutdown(self):
        """Безопасное завершение при ошибках"""
        try:
            if self.application:
                try:
                    await self.application.stop()
                except:
                    pass
                try:
                    await self.application.shutdown()
                except:
                    pass
        except Exception as ex:
            logger.error(f"Ошибка при безопасном завершении: {ex}")
        finally:
            self.bot_running = False
            self._is_stopping = False

    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.handle_start_sequence))
        self.application.add_handler(CallbackQueryHandler(self.handle_button))

    def stop_bot(self):
        """Упрощенная остановка бота через флаг"""
        if not self.bot_running or self._is_stopping:
            return

        with self._stop_lock:
            if self._is_stopping:
                return
                
            self._is_stopping = True
            self.bot_running = False
            self._stop_requested = True
            
        self.update_ui_state()
        self.add_log_message("Получен запрос на остановку...")

        # Просто устанавливаем флаг остановки - основной цикл сам завершится
        # Не создаем новый loop, ждем graceful shutdown

    def _async_stop_wrapper(self):
        """Упрощенная асинхронная остановка"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._shutdown_async())
            loop.close()
        except Exception as ex:
            logger.error(f"Ошибка при остановке: {str(ex)}")
            self._emergency_shutdown()

    def _emergency_shutdown(self):
        """Аварийная остановка"""
        try:
            logger.warning("Аварийная остановка бота...")
            
            # Отменяем активные задачи
            for user_id, task in list(self.active_tasks.items()):
                if not task.done():
                    try:
                        task.cancel()
                    except:
                        pass
            self.active_tasks.clear()
            
        except Exception as ex:
            logger.error(f"Ошибка при аварийной остановке: {ex}")
        finally:
            self._finalize_shutdown()

    async def _shutdown_async(self):
        """Упрощенная корректная остановка бота"""
        try:
            logger.info("Начало процесса остановки бота...")
            
            if not self.application:
                logger.warning("Приложение уже остановлено")
                return

            # 1. Останавливаем приложение (это остановит и updater)
            try:
                await self.application.stop()
                logger.info("Приложение остановлено")
            except Exception as ex:
                logger.error(f"Ошибка при остановке приложения: {ex}")

            # 2. Завершаем работу приложения
            try:
                await self.application.shutdown()
                logger.info("Приложение завершено")
            except Exception as ex:
                logger.error(f"Ошибка при завершении работы: {ex}")
                    
        except Exception as ex:
            logger.error(f"Ошибка при остановке: {str(ex)}", exc_info=True)
        finally:
            self._finalize_shutdown()


    def _finalize_shutdown(self):
        """Финальная очистка"""
        if hasattr(self, '_finalized') and self._finalized:
            return
            
        try:
            self._finalized = True
            
            # Сбрасываем флаги состояния, но НЕ блокируем запуск
            self._is_stopping = False
            self._stop_requested = False
            
            # Очищаем ссылки
            self.application = None
            self._bot_loop = None
            
            # Обновляем UI
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(0, self.update_ui_state)
                self.root.after(0, lambda: self.add_log_message("Бот остановлен"))
            
            logger.info("Финальная очистка завершена")
            
        except Exception as ex:
            logger.error(f"Ошибка при финализации: {ex}")

    def show_exit_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Выход")
        dialog.geometry("280x100")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # Центрируем окно относительно главного
        self.center_window_on_screen(dialog, 280, 100)

        # Стиль для кнопок (подстраивается под систему)
        button_style = {
            "font": ("Segoe UI", 9) if platform.system() == "Windows" else ("Arial", 10),
            "width": 12,
            "padx": 10,
            "pady": 5
        }

        # Основной текст
        tk.Label(
            dialog,
            text="Выберите действие:",
            font=("Segoe UI", 10) if platform.system() == "Windows" else ("Arial", 11),
            pady=10
        ).pack()

        # Фрейм для кнопок
        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=5)

        def do_minimize():
            dialog.destroy()
            self.minimize_to_tray()

        def do_exit():
            dialog.destroy()
            self.exit_app()

        # Кнопка "Свернуть в трей"
        minimize_btn = tk.Button(
            button_frame,
            text="Свернуть в трей",
            command=do_minimize,
            **button_style
        )
        minimize_btn.pack(side="left", padx=5)

        # Кнопка "Выйти"
        exit_btn = tk.Button(
            button_frame,
            text="Выйти",
            command=do_exit,
            **button_style
        )
        exit_btn.pack(side="right", padx=5)

        # Делаем окно модальным (блокирует родительское)
        dialog.focus_set()
        dialog.wait_window()

if __name__ == "__main__":
    root = tk.Tk()
    root.iconbitmap("icon.ico")  # путь к .ico-файлу
    app = None
    
    try:
        app = TelegramBotApp(root)
        
        def on_closing():
            app.show_exit_dialog()
        
        root.protocol("WM_DELETE_WINDOW", on_closing)
        
        root.mainloop()
        
    except KeyboardInterrupt:
        # Обработка Ctrl+C в консоли
        if app and hasattr(app, 'stop_bot') and not getattr(app, '_stop_requested', True):
            app.stop_bot()
        if root:
            root.after(500, root.destroy)
            
    except Exception as e:
        logging.critical(f"Критическая ошибка: {str(e)}", exc_info=True)
        try:
            if root and root.winfo_exists():
                try:
                    messagebox.showerror("Фатальная ошибка", f"Программа завершена из-за ошибки:\n{str(e)}")
                except:
                    pass
                    
                if (app and 
                    hasattr(app, 'stop_bot') and 
                    hasattr(app, 'bot_running') and 
                    hasattr(app, '_stop_requested')):
                    
                    if app.bot_running and not app._stop_requested:
                        app.stop_bot()
                        
                root.after(1000, lambda: root.destroy() if root.winfo_exists() else None)
        except Exception as ex:
            logger.critical(f"Ошибка при обработке критической ошибки: {ex}")
        finally:
            os._exit(1)

import atexit

def cleanup():
    """Функция cleanup при выходе"""
    try:
        if 'app' in globals() and app:
            app.exit_app()
    except:
        pass

atexit.register(cleanup)