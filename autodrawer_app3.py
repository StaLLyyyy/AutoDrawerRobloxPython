import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageGrab
import cv2
import numpy as np
import time
import threading
import keyboard
import math
import random
import json
import tempfile
import os
import ctypes
from ctypes import wintypes
from collections import deque

try:
    from sklearn.cluster import KMeans
    from pynput import mouse
    from scipy.spatial import KDTree
except ImportError as e:
    missing_module = str(e).split("'")[1]
    messagebox.showerror("Отсутствует модуль", 
                         f"Необходимый модуль '{missing_module}' не найден.\n\n"
                         f"Пожалуйста, установите его, выполнив команду в терминале:\n"
                         f"pip install scikit-learn pynput scipy")
    exit()

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event):
        if self.tooltip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tooltip(self, event):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

class MouseController:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.MOUSEEVENTF_LEFTDOWN = 0x0002
        self.MOUSEEVENTF_LEFTUP = 0x0004
        self.MOUSEEVENTF_MOVE = 0x0001
        self.MOUSEEVENTF_ABSOLUTE = 0x8000
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)
        
    def set_position(self, x, y):
        x, y = int(x), int(y)
        abs_x = int(x * 65535 / self.screen_width)
        abs_y = int(y * 65535 / self.screen_height)
        self.user32.mouse_event(self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE, abs_x, abs_y, 0, 0)
        
    def get_position(self):
        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return (point.x, point.y)
        
    def press(self):
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        
    def release(self):
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

class ColorManager:
    def __init__(self):
        self.current_color = None

class AutoDrawerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoDrawer | Roblox")
        self.root.geometry("650x950")
        self.root.resizable(False, False)
        self.mouse = MouseController()
        self.color_manager = ColorManager()
        
        self.config_vars = {
            'scale_factor': tk.DoubleVar(value=1.0), 'movement_speed': tk.DoubleVar(value=40.0),
            'luminance_threshold': tk.IntVar(value=127), 'threshold_mode': tk.StringVar(value="adaptive"),
            'adaptive_block_size': tk.IntVar(value=11), 'adaptive_c_constant': tk.IntVar(value=2),
            'simplification_factor': tk.DoubleVar(value=0.2), 'auto_simplification': tk.BooleanVar(value=True),
            'pixel_skip': tk.IntVar(value=1), 'drawing_mode': tk.StringVar(value="fill"),
            'human_jitter': tk.BooleanVar(value=False), 'keep_alive_nudge': tk.BooleanVar(value=True),
            'nudge_interval': tk.DoubleVar(value=10.0), 'random_pause_chance': tk.DoubleVar(value=0.5),
            'max_pause_duration': tk.DoubleVar(value=20.0), 'click_duration': tk.DoubleVar(value=5.0),
            'action_pause': tk.DoubleVar(value=1.0), 'step_pause': tk.DoubleVar(value=0.0),
            'fill_spacing': tk.IntVar(value=2), 'contour_min_area': tk.IntVar(value=10),
            'turbo_mode': tk.BooleanVar(value=False), 'fill_pattern': tk.StringVar(value="zigzag"),
            'color_mode': tk.BooleanVar(value=False),
            'stabilization_time': tk.DoubleVar(value=0.1), 'micro_adjustments': tk.BooleanVar(value=True),
            'pixel_grid_size': tk.IntVar(value=1), 'preview_quality': tk.StringVar(value="fast"),
            'optimize_paths': tk.BooleanVar(value=True),
            'pixelization_factor': tk.IntVar(value=1),
        }
        
        self.image_path = tk.StringVar()
        self.live_preview = tk.BooleanVar(value=False)
        self.drawing_state = "idle"
        self.last_progress_index = 0
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.processing_done_event = threading.Event()
        self.processing_done_event.set()
        self.drawing_data = []
        self.color_grouped_data = {}
        
        self.palette_setup_mode = False
        self.hex_input_position = None
        
        self._setup_styles()
        self._create_widgets()
        self.setup_hotkeys()
        self.toggle_threshold_mode()
        self._update_ui_for_mode()
        self.root.bind("<Control-v>", self.paste_from_clipboard)
        self.root.bind("<Control-V>", self.paste_from_clipboard)
        self.root.focus_set()

    def _setup_styles(self):
        try:
            self.root.tk.call('source', 'breeze.tcl')
            style = ttk.Style()
            style.theme_use('breeze')
        except tk.TclError:
            style = ttk.Style()
            style.theme_use('clam')
        style.configure("TButton", padding=6, relief="flat")
        style.configure("TNotebook.Tab", padding=[12, 5])

    def _create_widgets(self):
        main_paned_window = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        main_paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        top_frame = ttk.Frame(main_paned_window)
        main_paned_window.add(top_frame, weight=2)
        
        bottom_frame = ttk.Frame(main_paned_window)
        main_paned_window.add(bottom_frame, weight=1)

        file_frame = ttk.LabelFrame(top_frame, text="1. Изображение (Ctrl+V для вставки)", padding="10")
        file_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(file_frame, textvariable=self.image_path, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.browse_button = ttk.Button(file_frame, text="📂 Обзор...", command=self.select_image)
        self.browse_button.pack(side=tk.LEFT)

        preview_frame = ttk.LabelFrame(top_frame, text="Превью", padding="10")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.preview_label = ttk.Label(preview_frame, anchor=tk.CENTER)
        self.preview_label.pack(expand=True, fill=tk.BOTH)

        self.settings_frame = ScrollableFrame(bottom_frame)
        self.settings_frame.pack(fill=tk.BOTH, expand=True)
        
        notebook = ttk.Notebook(self.settings_frame.scrollable_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)
        
        tabs = [ttk.Frame(notebook, padding=10) for _ in range(5)]
        tab_names = ['  Основные  ', '  Точность  ', '  Рисование  ', '🎨 Цвета 🎨', ' Гуманизация ']
        for tab, name in zip(tabs, tab_names): notebook.add(tab, text=name)
        
        self._create_main_tab(tabs[0])
        self._create_precision_tab(tabs[1])
        self._create_drawing_tab(tabs[2])
        self._create_color_tab(tabs[3])
        self._create_humanization_tab(tabs[4])

        control_frame = ttk.LabelFrame(bottom_frame, text="2. Управление", padding="10")
        control_frame.pack(fill=tk.X, pady=5)
        
        self.toggle_overlay_button = ttk.Button(control_frame, text="👁️ Показать / Скрыть оверлей", 
                                                command=self.toggle_overlay, state=tk.DISABLED)
        self.toggle_overlay_button.pack(fill=tk.X, pady=2)
        
        action_buttons_frame = ttk.Frame(control_frame)
        action_buttons_frame.pack(fill=tk.X, expand=True, pady=2)

        self.start_button = ttk.Button(action_buttons_frame, text="▶️ Старт / Пауза (Insert)", 
                                       command=self.toggle_pause_resume, state=tk.DISABLED)
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self.stop_button = ttk.Button(action_buttons_frame, text="⏹️ Стоп (Delete)", 
                                      command=self.stop_drawing, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        
        ttk.Checkbutton(control_frame, text="Живое превью", variable=self.live_preview).pack(pady=5, anchor='w')
        
        ttk.Label(control_frame, 
                  text="🔥 Горячие клавиши: End (Экстренная остановка)", 
                  anchor=tk.CENTER, font=('TkDefaultFont', 8)).pack(fill=tk.X)
        
        config_frame = ttk.Frame(bottom_frame)
        config_frame.pack(fill=tk.X, pady=5)
        ttk.Button(config_frame, text="💾 Сохранить конфиг", command=self.save_config).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(config_frame, text="📂 Загрузить конфиг", command=self.load_config).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        progress_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        progress_frame.pack(fill=tk.X)
        self.progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', mode='determinate')
        self.progress_bar.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 5))
        self.etr_label = ttk.Label(progress_frame, text="Время: --:--")
        self.etr_label.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="🚀 Готов к рисованию!")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5).pack(side=tk.BOTTOM, fill=tk.X)

    def _create_main_tab(self, tab):
        self._create_slider(tab, "Масштаб:", self.config_vars['scale_factor'], 0.1, 2.0, 0)
        self._create_slider(tab, "Скорость движения:", self.config_vars['movement_speed'], 5.0, 50.0, 1)
        
        turbo_frame = ttk.LabelFrame(tab, text="⚡ Режим производительности", padding=5)
        turbo_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)
        turbo_check = ttk.Checkbutton(turbo_frame, text="ТУРБО РЕЖИМ (максимальная скорость)", 
                                variable=self.config_vars['turbo_mode'], command=self.toggle_turbo_mode)
        turbo_check.pack(anchor='w')
        ToolTip(turbo_check, "Отключает гуманизацию и точность для максимальной скорости.")

        precision_frame = ttk.LabelFrame(tab, text="🎯 Ультра точность", padding=5)
        precision_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)
        micro_check = ttk.Checkbutton(precision_frame, text="Микрокоррекции позиции", 
                                      variable=self.config_vars['micro_adjustments'])
        micro_check.grid(row=0, column=0, columnspan=3, sticky='w')
        ToolTip(micro_check, "После перемещения мыши, проверяет позицию и корректирует ее при необходимости.")
        self._create_slider(precision_frame, "Стабилизация (с):", self.config_vars['stabilization_time'], 0.0, 0.5, 1)
        
        tab.columnconfigure(1, weight=1)

    def _create_precision_tab(self, tab):
        quality_frame = ttk.LabelFrame(tab, text="Качество обработки", padding=10)
        quality_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        fast_radio = ttk.Radiobutton(quality_frame, text="Быстрое", variable=self.config_vars['preview_quality'], 
                                     value="fast", command=self.on_settings_change)
        fast_radio.pack(side=tk.LEFT, padx=5)
        ToolTip(fast_radio, "Быстрая обработка для превью, но может быть менее точной.")
        accurate_radio = ttk.Radiobutton(quality_frame, text="Точное", variable=self.config_vars['preview_quality'], 
                                         value="accurate", command=self.on_settings_change)
        accurate_radio.pack(side=tk.LEFT, padx=5)
        ToolTip(accurate_radio, "Более медленная, но точная обработка изображения.")

        threshold_frame = ttk.LabelFrame(tab, text="Порог яркости", padding=10)
        threshold_frame.grid(row=1, column=0, sticky="ew")
        
        self._create_slider(threshold_frame, "Ручной:", self.config_vars['luminance_threshold'], 1, 254, 0)
        
        ttk.Radiobutton(threshold_frame, text="Ручной", variable=self.config_vars['threshold_mode'], 
                        value="manual", command=self.toggle_threshold_mode).grid(row=1, column=0, sticky='w')
        ttk.Radiobutton(threshold_frame, text="Авто (Глобальный)", variable=self.config_vars['threshold_mode'], 
                        value="global", command=self.toggle_threshold_mode).grid(row=1, column=1, sticky='w')
        ttk.Radiobutton(threshold_frame, text="Авто (Адаптивный)", variable=self.config_vars['threshold_mode'], 
                        value="adaptive", command=self.toggle_threshold_mode).grid(row=1, column=2, sticky='w', padx=5)
        
        threshold_frame.columnconfigure(1, weight=1)

        self.adaptive_frame = ttk.LabelFrame(tab, text="Настройки адаптивного порога", padding=10)
        self.adaptive_frame.grid(row=2, column=0, sticky="ew", pady=5)
        self._create_slider(self.adaptive_frame, "Размер блока:", self.config_vars['adaptive_block_size'], 3, 51, 0, is_int=True)
        self._create_slider(self.adaptive_frame, "Константа C:", self.config_vars['adaptive_c_constant'], 0, 15, 1, is_int=True)
        self.adaptive_frame.columnconfigure(1, weight=1)

        simplification_frame = ttk.LabelFrame(tab, text="Оптимизация контуров", padding=10)
        self.simplification_frame = simplification_frame
        simplification_frame.grid(row=3, column=0, sticky="ew", pady=5)
        
        opt_frame = ttk.Frame(simplification_frame)
        opt_frame.grid(row=0, column=0, columnspan=3, sticky=tk.W)
        opt_check = ttk.Checkbutton(opt_frame, text="Оптимизация пути (Быстрая)", 
                                    variable=self.config_vars['optimize_paths'], 
                                    command=self.on_settings_change)
        opt_check.pack(side=tk.LEFT)
        ToolTip(opt_check, "Переупорядочивает пути для минимизации движений мыши. Может занять время при первом анализе.")

        self._create_slider(simplification_frame, "Упрощение:", self.config_vars['simplification_factor'], 0.0, 2.0, 1)
        ttk.Checkbutton(simplification_frame, text="Авто-упрощение", 
                        variable=self.config_vars['auto_simplification'], 
                        command=self.toggle_simplification_mode).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=5)
        self._create_slider(simplification_frame, "Мин. область:", self.config_vars['contour_min_area'], 1, 50, 3, is_int=True)
        simplification_frame.columnconfigure(1, weight=1)

        pixelization_frame = ttk.LabelFrame(tab, text="⚡ Ускорение (Пикселизация)", padding=10)
        pixelization_frame.grid(row=4, column=0, sticky="ew", pady=5)
        self._create_slider(pixelization_frame, "Размер пикселя:", self.config_vars['pixelization_factor'], 1, 20, 0, is_int=True)
        ToolTip(pixelization_frame, "Увеличивает 'пиксели' изображения для ускорения рисования. Чем больше значение, тем быстрее и менее детально.")
        pixelization_frame.columnconfigure(1, weight=1)
        
        tab.columnconfigure(0, weight=1)

    def _create_drawing_tab(self, tab):
        mode_frame = ttk.LabelFrame(tab, text="Режим рисования", padding=10)
        mode_frame.grid(row=0, column=0, sticky="ew")
        
        modes = {"Контуры": "outline", "Заливка": "fill", "Скелет (для линий)": "skeleton", 
                 "Pixel Art": "pixel", "Пиксельная сетка (точно)": "pixel_grid"}
        for text, value in modes.items():
            rb = ttk.Radiobutton(mode_frame, text=text, variable=self.config_vars['drawing_mode'], 
                                 value=value, command=self._update_ui_for_mode)
            rb.pack(anchor='w')
            if value == 'skeleton':
                ToolTip(rb, "Рисует только центральные линии объектов. Идеально для контурных рисунков.")
            if value == 'pixel_grid':
                ToolTip(rb, "Самый точный режим. Рисует цветные квадраты по сетке.")

        fill_frame = ttk.LabelFrame(tab, text="🎨 Настройки заливки", padding=10)
        self.fill_frame = fill_frame
        fill_frame.grid(row=1, column=0, sticky="ew", pady=5)
        
        ttk.Label(fill_frame, text="Паттерн заливки:").grid(row=0, column=0, sticky='w')
        pattern_frame = ttk.Frame(fill_frame)
        pattern_frame.grid(row=1, column=0, sticky='w')
        
        patterns = [("Горизонтальный", "horizontal"), ("Вертикальный", "vertical"), 
                    ("Зигзаг", "zigzag"), ("Диагональ", "diagonal")]
        for pattern_name, pattern_value in patterns:
            ttk.Radiobutton(pattern_frame, text=pattern_name, variable=self.config_vars['fill_pattern'], 
                            value=pattern_value, command=self.on_settings_change).pack(side='left')
        
        self._create_slider(fill_frame, "Плотность:", self.config_vars['fill_spacing'], 1, 5, 2, is_int=True)
        fill_frame.columnconfigure(1, weight=1)

        pixel_frame = ttk.LabelFrame(tab, text="Настройки Pixel Art / Сетки", padding=10)
        self.pixel_frame = pixel_frame
        pixel_frame.grid(row=2, column=0, sticky="ew", pady=5)
        self._create_slider(pixel_frame, "Пропуск пикселей:", self.config_vars['pixel_skip'], 1, 10, 0, is_int=True)
        self._create_slider(pixel_frame, "Размер сетки (px):", self.config_vars['pixel_grid_size'], 1, 10, 1, is_int=True)
        pixel_frame.columnconfigure(1, weight=1)
        
        tab.columnconfigure(0, weight=1)

    def _create_color_tab(self, tab):
        color_mode_frame = ttk.LabelFrame(tab, text="🎨 Цветной режим", padding=10)
        color_mode_frame.grid(row=0, column=0, sticky="ew")
        
        ttk.Checkbutton(color_mode_frame, text="Включить цветное рисование", 
                        variable=self.config_vars['color_mode'], 
                        command=self.toggle_color_mode).pack(anchor='w', pady=2)

        ttk.Label(color_mode_frame, text="⚠️ Требуется настроить поле для ввода HEX", 
                  foreground='red', font=('TkDefaultFont', 9)).pack(anchor='w', pady=2)

        hex_frame = ttk.LabelFrame(tab, text="🎯 Настройка ввода HEX", padding=10)
        hex_frame.grid(row=1, column=0, sticky="ew", pady=5)
        
        ttk.Button(hex_frame, text="⌨️ Выделить поле для HEX", 
                   command=self.start_hex_input_setup).pack(fill=tk.X, pady=2)

        self.hex_info_label = ttk.Label(hex_frame, text="Поле HEX не настроено", 
                                            foreground='orange')
        self.hex_info_label.pack(anchor='w', pady=5)
        
        tab.columnconfigure(0, weight=1)

    def _create_humanization_tab(self, tab):
        human_motion_frame = ttk.LabelFrame(tab, text="Движения", padding=10)
        human_motion_frame.grid(row=0, column=0, sticky="ew")
        
        ttk.Checkbutton(human_motion_frame, text="Микро-движения (Jitter)", 
                        variable=self.config_vars['human_jitter']).grid(row=0, column=0, sticky='w', columnspan=3)
        
        self._create_slider(human_motion_frame, "Случ. паузы (%):", 
                             self.config_vars['random_pause_chance'], 0, 10, 1)
        self._create_slider(human_motion_frame, "Макс. пауза (мс):", 
                             self.config_vars['max_pause_duration'], 0, 100, 2)
        
        human_motion_frame.columnconfigure(1, weight=1)

        anti_detection_frame = ttk.LabelFrame(tab, text="Anti-Detection", padding=10)
        anti_detection_frame.grid(row=1, column=0, sticky="ew", pady=5)
        
        ttk.Checkbutton(anti_detection_frame, text="Keep-Alive движения", 
                        variable=self.config_vars['keep_alive_nudge']).grid(row=0, column=0, columnspan=3)
        
        self._create_slider(anti_detection_frame, "Интервал (сек):", 
                             self.config_vars['nudge_interval'], 5, 60, 1)
        
        anti_detection_frame.columnconfigure(1, weight=1)

        sync_frame = ttk.LabelFrame(tab, text="⚙️ Тайминги", padding=10)
        sync_frame.grid(row=2, column=0, sticky="ew", pady=5)
        
        self._create_slider(sync_frame, "Пауза шага (мс):", self.config_vars['step_pause'], 0, 10, 0)
        self._create_slider(sync_frame, "Клик (мс):", self.config_vars['click_duration'], 5, 50, 1)
        self._create_slider(sync_frame, "Пауза действия (мс):", self.config_vars['action_pause'], 1, 25, 2)
        
        sync_frame.columnconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

    def _create_slider(self, parent, text, variable, from_, to, row, is_int=False):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky=tk.W, pady=3)
        slider = ttk.Scale(parent, from_=from_, to=to, orient=tk.HORIZONTAL, variable=variable, command=self.on_settings_change)
        slider.grid(row=row, column=1, sticky=tk.EW, padx=5)
        value_label = ttk.Label(parent, width=8)
        value_label.grid(row=row, column=2, sticky=tk.E)
        
        def update_label(*args):
            val = variable.get()
            if is_int: 
                variable.set(round(val))
                value_label.config(text=f"{variable.get():.0f}")
            else: 
                value_label.config(text=f"{val:.2f}")
        
        variable.trace_add("write", update_label)
        update_label()
        
        if text == "Ручной:": 
            self.threshold_slider_components = (parent.winfo_children()[0], slider, value_label)
        elif text == "Упрощение:": 
            self.simplification_scale = slider
        elif text == "Размер блока:": 
            self.adaptive_block_slider_components = (parent.winfo_children()[0], slider, value_label)
        elif text == "Константа C:": 
            self.adaptive_c_slider_components = (parent.winfo_children()[0], slider, value_label)

    def _update_ui_for_mode(self, event=None):
        mode = self.config_vars['drawing_mode'].get()

        def set_frame_state(frame, state):
            if not frame: return
            for child in frame.winfo_children():
                try:
                    if 'state' in child.configure():
                        child.configure(state=state)
                except tk.TclError:
                    pass

        fill_frame = getattr(self, 'fill_frame', None)
        pixel_frame = getattr(self, 'pixel_frame', None)
        simplification_frame = getattr(self, 'simplification_frame', None)

        set_frame_state(simplification_frame, 'normal' if mode in ['outline', 'skeleton'] else 'disabled')
        set_frame_state(fill_frame, 'normal' if mode == 'fill' else 'disabled')
        set_frame_state(pixel_frame, 'normal' if mode in ['pixel', 'pixel_grid'] else 'disabled')

        if simplification_frame and mode in ['outline', 'skeleton']:
            is_auto = self.config_vars['auto_simplification'].get()
            self.simplification_scale.config(state=tk.DISABLED if is_auto else tk.NORMAL)

    def toggle_simplification_mode(self):
        self.on_settings_change()

    def toggle_color_mode(self):
        is_color = self.config_vars['color_mode'].get()
        if is_color:
            self.status_var.set("🎨 Цветной режим активен! Настройте поле для ввода HEX")
        else:
            self.status_var.set("🚀 Обычный режим")
        self.on_settings_change()

    def start_hex_input_setup(self):
        self.status_var.set("🖱️ Кликните на поле для ввода HEX кода...")
        self.setup_window = tk.Toplevel(self.root)
        self.setup_window.attributes("-fullscreen", True)
        self.setup_window.attributes("-alpha", 0.1)
        self.setup_window.attributes("-topmost", True)
        self.setup_window.configure(bg='blue')
        self.setup_window.bind("<Button-1>", self.end_hex_input_setup)
        self.setup_window.bind("<Escape>", self.cancel_palette_setup)

    def end_hex_input_setup(self, event):
        self.hex_input_position = (event.x_root, event.y_root)
        self.hex_info_label.config(text=f"✅ Поле HEX настроено на ({event.x_root}, {event.y_root})", foreground='green')
        self.status_var.set("⌨️ Поле для ввода HEX кода выбрано!")
        self.cancel_palette_setup()

    def cancel_palette_setup(self, event=None):
        if hasattr(self, 'setup_window'):
            self.setup_window.destroy()
        self.palette_setup_mode = False

    def toggle_turbo_mode(self):
        is_turbo = self.config_vars['turbo_mode'].get()
        
        if is_turbo:
            self.status_var.set("🔥 ТУРБО РЕЖИМ АКТИВЕН!")
            settings = {
                'movement_speed': 50.0,
                'step_pause': 0.0,
                'click_duration': 5.0,
                'action_pause': 0.5,
                'human_jitter': False,
                'random_pause_chance': 0.0,
                'stabilization_time': 0.0,
                'micro_adjustments': False
            }
        else:
            self.status_var.set("🎯 Точный режим активен")
            settings = {
                'movement_speed': 15.0,
                'step_pause': 0.5,
                'click_duration': 8.0,
                'action_pause': 2.0,
                'human_jitter': False,
                'random_pause_chance': 0.5,
                'stabilization_time': 0.1,
                'micro_adjustments': True
            }
        
        for key, value in settings.items():
            if key in self.config_vars:
                self.config_vars[key].set(value)

    def toggle_threshold_mode(self, _=None):
        mode = self.config_vars['threshold_mode'].get()
        
        manual_state = tk.NORMAL if mode == 'manual' else tk.DISABLED
        adaptive_state = tk.NORMAL if mode == 'adaptive' else tk.DISABLED
        
        if hasattr(self, 'threshold_slider_components'):
            for widget in self.threshold_slider_components:
                widget.config(state=manual_state)
        if hasattr(self, 'adaptive_block_slider_components'):
            for widget in self.adaptive_block_slider_components:
                widget.config(state=adaptive_state)
        if hasattr(self, 'adaptive_c_slider_components'):
            for widget in self.adaptive_c_slider_components:
                widget.config(state=adaptive_state)
                
        self.on_settings_change()

    def setup_hotkeys(self):
        try:
            keyboard.add_hotkey('insert', self.toggle_pause_resume, suppress=True)
            keyboard.add_hotkey('delete', self.stop_drawing, suppress=True)
            keyboard.add_hotkey('end', self.emergency_stop, suppress=True)
        except:
            pass

    def emergency_stop(self):
        self.drawing_state = "emergency_stop"
        self.stop_event.set()
        self.pause_event.set()
        
        if getattr(self, 'drawing_thread', None) and self.drawing_thread.is_alive():
            self.drawing_thread.join(timeout=1.0)
            
        self.status_var.set("🛑 ЭКСТРЕННАЯ ОСТАНОВКА!")
        self.reset_progress()
        self.drawing_state = "idle"

    def select_image(self):
        path = filedialog.askopenfilename(
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp")]
        )
        if path:
            self.load_image_from_path(path)

    def paste_from_clipboard(self, event=None):
        def _paste_task():
            try:
                clipboard_content = ImageGrab.grabclipboard()
                if clipboard_content:
                    if isinstance(clipboard_content, Image.Image):
                        temp_path = os.path.join(tempfile.gettempdir(), 
                                                 f"autodrawer_paste_{int(time.time())}.png")
                        clipboard_content.save(temp_path, "PNG")
                        self.root.after(0, lambda: self.load_image_from_path(temp_path))
                        self.root.after(0, lambda: self.status_var.set("✅ Изображение вставлено из буфера обмена"))
                    else:
                        self.root.after(0, lambda: self.status_var.set("❌ Неподдерживаемый формат в буфере"))
                else:
                    self.root.after(0, lambda: self.status_var.set("❌ Нет изображения в буфере обмена"))
            except Exception as e:
                error_msg = f"❌ Ошибка вставки: {str(e)[:30]}"
                self.root.after(0, lambda: self.status_var.set(error_msg))
        
        self.status_var.set("⏳ Вставка из буфера...")
        threading.Thread(target=_paste_task, daemon=True).start()
        return "break"

    def load_image_from_path(self, path):
        self.image_path.set(path)
        self.root.after(100, self.update_preview)
        self.toggle_overlay_button.config(state=tk.NORMAL)
        self.reset_progress()

    def update_preview(self):
        try:
            img = Image.open(self.image_path.get())
            frame_w = self.preview_label.winfo_width()
            frame_h = self.preview_label.winfo_height()
            
            if frame_w > 1 and frame_h > 1:
                img.thumbnail((frame_w, frame_h), Image.Resampling.LANCZOS)
                self.preview_photo_image = ImageTk.PhotoImage(img)
                self.preview_label.config(image=self.preview_photo_image)
                
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить превью: {e}")

    def on_settings_change(self, _=None):
        if hasattr(self, 'fill_frame'):
                 self._update_ui_for_mode()

        if (self.live_preview.get() and 
            getattr(self, 'overlay_window', None) and 
            self.overlay_window.winfo_exists()):
            self.start_image_processing_thread(recreate_overlay=True)

    def toggle_overlay(self):
        self.reset_progress()
        
        if (getattr(self, 'overlay_window', None) and 
            self.overlay_window.winfo_exists()):
            self.overlay_window.destroy()
            self.overlay_window = None
            self.status_var.set("Оверлей скрыт. Нажмите Insert для старта.")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
        else:
            self.start_image_processing_thread()

    def start_image_processing_thread(self, recreate_overlay=False):
        self.toggle_overlay_button.config(state=tk.DISABLED)
        self.browse_button.config(state=tk.DISABLED)
        self.status_var.set("⏳ Идет обработка изображения...")
        self.processing_done_event.clear()
        
        processing_thread = threading.Thread(
            target=self.process_image,
            args=(recreate_overlay,),
            daemon=True
        )
        processing_thread.start()

    def on_image_processing_complete(self, recreate_overlay=False):
        if getattr(self, 'overlay_photo_image', None):
            self.create_overlay_window(recreate=recreate_overlay)
            self.status_var.set("🎯 Расположите оверлей и нажмите Старт!")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.NORMAL)
        else:
            self.status_var.set("🚀 Готов к рисованию!")
        
        self.toggle_overlay_button.config(state=tk.NORMAL)
        self.browse_button.config(state=tk.NORMAL)

    def _estimate_stroke_width(self, binary_image):
        try:
            dist = cv2.distanceTransform(binary_image, cv2.DIST_L2, 3)
            _, max_val, _, _ = cv2.minMaxLoc(dist)
            
            if max_val == 0:
                return 1.0
                
            stroke_width = max_val * 2
            
            if stroke_width < 3:
                return 0.8
            elif stroke_width < 8:
                return 1.2
            else:
                return min(2.5, stroke_width / 6)
                
        except:
            return 1.0

    def process_image(self, recreate_overlay=False):
        error_msg = None
        try:
            with open(self.image_path.get(), 'rb') as f:
                img_bytes = np.frombuffer(f.read(), np.uint8)
            img_cv = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)

            if img_cv is None:
                raise ValueError("Не удалось загрузить изображение.")
            
            self.root.after(0, lambda: self.status_var.set("⏳ Масштабирование..."))
            scale = self.config_vars['scale_factor'].get()
            self.image_width = max(1, int(img_cv.shape[1] * scale))
            self.image_height = max(1, int(img_cv.shape[0] * scale))
            
            self.color_image = cv2.resize(img_cv, (self.image_width, self.image_height), interpolation=cv2.INTER_LANCZOS4)
            
            pixel_size = self.config_vars['pixelization_factor'].get()
            if pixel_size > 1:
                self.root.after(0, lambda: self.status_var.set("⏳ Пикселизация изображения..."))
                h, w = self.color_image.shape[:2]
                temp_img = cv2.resize(self.color_image, (w // pixel_size, h // pixel_size), interpolation=cv2.INTER_LINEAR)
                self.color_image = cv2.resize(temp_img, (w, h), interpolation=cv2.INTER_NEAREST)

            quality = self.config_vars['preview_quality'].get()
            max_dim = 800 if quality == 'fast' else 1280

            processing_scale = 1.0
            if max(self.image_width, self.image_height) > max_dim:
                processing_scale = max_dim / max(self.image_width, self.image_height)
                proc_w = int(self.image_width * processing_scale)
                proc_h = int(self.image_height * processing_scale)
                processing_image = cv2.resize(self.color_image, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
            else:
                processing_image = self.color_image

            if quality == 'accurate':
                self.root.after(0, lambda: self.status_var.set("⏳ Анализ яркости (точный режим, может быть медленно)..."))
            else:
                self.root.after(0, lambda: self.status_var.set("⏳ Анализ яркости..."))

            img_gray = cv2.cvtColor(processing_image, cv2.COLOR_BGR2GRAY)
            img_blurred = cv2.GaussianBlur(img_gray, (3, 3), 0)
            
            mode = self.config_vars['threshold_mode'].get()
            if mode == 'adaptive':
                block_size = self.config_vars['adaptive_block_size'].get()
                if block_size % 2 == 0: block_size += 1
                binary_map = cv2.adaptiveThreshold(img_blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block_size, self.config_vars['adaptive_c_constant'].get())
            else:
                thresh_type = cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU if mode == 'global' else cv2.THRESH_BINARY_INV
                _, binary_map = cv2.threshold(img_blurred, self.config_vars['luminance_threshold'].get(), 255, thresh_type)
            
            kernel = np.ones((2, 2), np.uint8)
            self.processed_pixel_map = cv2.morphologyEx(binary_map, cv2.MORPH_CLOSE, kernel)
            
            self.drawing_data = []
            self.color_grouped_data = {}

            self.root.after(0, lambda: self.status_var.set("⏳ Подготовка данных для рисования..."))
            draw_mode = self.config_vars['drawing_mode'].get()
            if draw_mode == 'outline': self._prepare_outline_data(processing_scale)
            elif draw_mode == 'fill': self._prepare_fill_data(processing_scale)
            elif draw_mode == 'skeleton': self._prepare_skeleton_data(processing_scale)
            elif draw_mode == 'pixel': self._prepare_pixel_data(processing_scale)
            elif draw_mode == 'pixel_grid': self._prepare_pixel_grid_data(processing_scale)
            
            self.root.after(0, lambda: self.status_var.set("⏳ Группировка по цвету..."))
            self._group_data_by_color()
            
            self.root.after(0, lambda: self.status_var.set("⏳ Создание превью..."))
            self._create_preview_image()
            self.root.after(0, self.on_image_processing_complete, recreate_overlay)
            
            self.root.after(0, lambda: self.status_var.set("✅ Данные для рисования готовы!"))

        except Exception as e:
            error_msg = f"Ошибка: {str(e)}"
            self.drawing_data = []
            self.color_grouped_data = {}
        finally:
            if error_msg:
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("Ошибка обработки", msg))
            self.processing_done_event.set()

    def _create_preview_image(self):
        is_color = self.config_vars['color_mode'].get()
        draw_mode = self.config_vars['drawing_mode'].get()

        if not is_color:
            preview_map = cv2.resize(self.processed_pixel_map, (self.image_width, self.image_height), interpolation=cv2.INTER_NEAREST)
            rgba_img = cv2.cvtColor(preview_map, cv2.COLOR_GRAY2RGBA)
            rgba_img[preview_map == 0] = [0, 0, 0, 0]
            rgba_img[preview_map == 255] = [0, 0, 0, 255]
        else:
            preview_canvas = np.zeros((self.image_height, self.image_width, 4), dtype=np.uint8)
            
            if draw_mode == 'pixel_grid':
                grid_size = self.config_vars['pixel_grid_size'].get()
                for (pos, color) in self.drawing_data:
                    if self._is_color_white(color): continue
                    bgr_color = (color[2], color[1], color[0], 255)
                    cv2.rectangle(preview_canvas, pos, (pos[0] + grid_size -1, pos[1] + grid_size -1), bgr_color, -1)
            else:
                for path, color in self.drawing_data:
                    if self._is_color_white(color): continue
                    bgr_color = (color[2], color[1], color[0], 255)
                    pts = np.array(path, np.int32).reshape((-1, 1, 2))
                    if draw_mode == 'fill':
                        cv2.fillPoly(preview_canvas, [pts], bgr_color)
                    else:
                        cv2.polylines(preview_canvas, [pts], isClosed=(draw_mode=='outline'), color=bgr_color, thickness=1)

            rgba_img = cv2.cvtColor(preview_canvas, cv2.COLOR_BGRA2RGBA)

        self.overlay_photo_image = ImageTk.PhotoImage(Image.fromarray(rgba_img))

    def _group_data_by_color(self):
        self.color_grouped_data = {}
        draw_mode = self.config_vars['drawing_mode'].get()

        for action, color in self.drawing_data:
            if color not in self.color_grouped_data:
                self.color_grouped_data[color] = []
            self.color_grouped_data[color].append(action)
        
        if draw_mode != 'pixel_grid' and self.config_vars['optimize_paths'].get():
            for color in self.color_grouped_data:
                self.color_grouped_data[color] = self._optimize_path_order(self.color_grouped_data[color])

    def _prepare_outline_data(self, processing_scale):
        if self.config_vars['auto_simplification'].get():
            self.config_vars['simplification_factor'].set(self._estimate_stroke_width(255 - self.processed_pixel_map))
            
        contours, _ = cv2.findContours(self.processed_pixel_map, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        min_area = self.config_vars['contour_min_area'].get()
        scaled_min_area = min_area * (processing_scale ** 2)
        
        for cnt in contours:
            if cv2.contourArea(cnt) >= scaled_min_area:
                epsilon = (self.config_vars['simplification_factor'].get() / 100 * cv2.arcLength(cnt, True))
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                
                if len(approx) >= 2:
                    path = (approx / processing_scale).astype(int)
                    path = [tuple(p[0]) for p in path]
                    path.append(path[0])
                    
                    mid_point = path[len(path) // 2]
                    color = self.get_pixel_color(mid_point[0], mid_point[1])
                    if not self._is_color_white(color):
                        self.drawing_data.append((path, color))
        
    def _prepare_fill_data(self, processing_scale):
        h, w = self.processed_pixel_map.shape
        spacing = self.config_vars['fill_spacing'].get()
        pattern = self.config_vars['fill_pattern'].get()

        if pattern in ['horizontal', 'zigzag']:
            for i in range(0, h, spacing):
                line_data = self.processed_pixel_map[i, :]
                starts = np.where((line_data[:-1] == 0) & (line_data[1:] == 255))[0] + 1
                ends = np.where((line_data[:-1] == 255) & (line_data[1:] == 0))[0]
                if len(line_data) > 0 and line_data[0] == 255: starts = np.concatenate([[0], starts])
                if len(line_data) > 0 and line_data[-1] == 255: ends = np.concatenate([ends, [len(line_data) - 1]])
                for start, end in zip(starts, ends):
                    if end > start:
                        line_points = [(int(start / processing_scale), int(i / processing_scale)), (int(end / processing_scale), int(i / processing_scale))]
                        if pattern == 'zigzag' and (i // spacing) % 2 == 1: line_points.reverse()
                        
                        mid_point = line_points[0]
                        color = self.get_pixel_color(mid_point[0], mid_point[1])
                        if not self._is_color_white(color):
                            self.drawing_data.append((line_points, color))
        
    def _prepare_skeleton_data(self, processing_scale):
        try:
            thinned = cv2.ximgproc.thinning(self.processed_pixel_map)
            paths = self._trace_skeleton_paths(thinned)
            for path in paths:
                scaled_path = [(int(p[0] / processing_scale), int(p[1] / processing_scale)) for p in path]
                mid_point = scaled_path[len(scaled_path) // 2]
                color = self.get_pixel_color(mid_point[0], mid_point[1])
                if not self._is_color_white(color):
                    self.drawing_data.append((scaled_path, color))
        except AttributeError:
            self._prepare_outline_data(processing_scale)

    def _trace_skeleton_paths(self, skeleton_img):
        paths = []
        visited = skeleton_img.copy()
        h, w = skeleton_img.shape
        
        for y in range(h):
            for x in range(w):
                if visited[y, x] == 255:
                    path = []
                    q = deque([(x, y)])
                    
                    while q:
                        px, py = q.popleft()
                        if visited[py, px] != 255: continue
                        path.append((px, py))
                        visited[py, px] = 128
                        neighbors = []
                        for dy in range(-1, 2):
                            for dx in range(-1, 2):
                                if dx == 0 and dy == 0: continue
                                ny, nx = py + dy, px + dx
                                if (0 <= ny < h and 0 <= nx < w and visited[ny, nx] == 255):
                                    neighbors.append((nx, ny))
                        if len(neighbors) == 1:
                            q.append(neighbors[0])
                    if len(path) > 2:
                        paths.append(path)
                        
        return paths

    def _prepare_pixel_data(self, processing_scale):
        skip = max(1, self.config_vars['pixel_skip'].get())
        h, w = self.processed_pixel_map.shape
        
        for y in range(0, h, skip):
            x = 0
            while x < w:
                if self.processed_pixel_map[y, x] == 255:
                    x_start = x
                    while x < w and self.processed_pixel_map[y, x] == 255:
                        x += 1
                    end_x = x - 1
                    if end_x >= x_start:
                        segment = [(int(x_start / processing_scale), int(y / processing_scale)), (int(end_x / processing_scale), int(y / processing_scale))]
                        color = self.get_pixel_color(segment[0][0], segment[0][1])
                        if not self._is_color_white(color):
                            self.drawing_data.append((segment, color))
                else:
                    x += 1
    
    def _prepare_pixel_grid_data(self, processing_scale):
        grid_size = self.config_vars['pixel_grid_size'].get()
        
        ys, xs = np.where(self.processed_pixel_map == 255)
        
        drawn_cells = set()
        h, w = self.color_image.shape[:2]

        for y, x in zip(ys, xs):
            orig_x, orig_y = int(x / processing_scale), int(y / processing_scale)
            
            grid_x = (orig_x // grid_size) * grid_size
            grid_y = (orig_y // grid_size) * grid_size
            
            cell = (grid_x, grid_y)
            if cell not in drawn_cells:
                if 0 <= grid_y < h and 0 <= grid_x < w:
                    bgr = self.color_image[grid_y, grid_x]
                    rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
                    if not self._is_color_white(rgb):
                        self.drawing_data.append(((grid_x, grid_y), rgb))
                    drawn_cells.add(cell)
        
        self.root.after(0, lambda: self.status_var.set(f"🖼️ Режим сетки: {len(self.drawing_data)} пикселей для отрисовки."))

    def _optimize_path_order(self, paths):
        if not paths or len(paths) < 2:
            return paths
            
        optimized = [paths[0]]
        remaining = list(paths[1:])
        
        while remaining:
            last_point = optimized[-1][-1]
            
            best_idx = 0
            best_dist = float('inf')
            reverse = False
            
            for i, path in enumerate(remaining):
                start_dist = math.hypot(path[0][0] - last_point[0], path[0][1] - last_point[1])
                end_dist = math.hypot(path[-1][0] - last_point[0], path[-1][1] - last_point[1])
                
                if start_dist < best_dist:
                    best_dist = start_dist
                    best_idx = i
                    reverse = False
                    
                if end_dist < best_dist:
                    best_dist = end_dist
                    best_idx = i
                    reverse = True
            
            next_path = remaining.pop(best_idx)
            if reverse:
                next_path = list(reversed(next_path))
            optimized.append(next_path)
            
        return optimized

    def create_overlay_window(self, recreate=False):
        current_pos = None
        
        if recreate and getattr(self, 'overlay_window', None) and self.overlay_window.winfo_exists():
            current_pos = (self.overlay_window.winfo_x(), self.overlay_window.winfo_y())
            self.overlay_window.destroy()
            
        self.overlay_window = tk.Toplevel(self.root)
        self.overlay_window.overrideredirect(True)
        self.overlay_window.attributes("-alpha", 0.7)
        self.overlay_window.attributes("-topmost", True)
        self.overlay_window.attributes("-transparentcolor", "white")
        
        if current_pos:
            self.overlay_window.geometry(f"+{current_pos[0]}+{current_pos[1]}")

        self.overlay_canvas = tk.Canvas(
            self.overlay_window, 
            width=self.image_width, 
            height=self.image_height, 
            bg='white', 
            highlightthickness=0
        )
        self.overlay_canvas.pack()
        self.overlay_canvas.create_image(0, 0, anchor=tk.NW, image=self.overlay_photo_image)
        
        self.overlay_canvas.bind("<ButtonPress-1>", self.start_move)
        self.overlay_canvas.bind("<B1-Motion>", self.do_move)

    def start_move(self, event):
        self.overlay_window.x = event.x
        self.overlay_window.y = event.y

    def do_move(self, event):
        x = self.overlay_window.winfo_x() + (event.x - self.overlay_window.x)
        y = self.overlay_window.winfo_y() + (event.y - self.overlay_window.y)
        self.overlay_window.geometry(f"+{x}+{y}")

    def toggle_pause_resume(self):
        if self.drawing_state == "idle":
            if getattr(self, 'overlay_window', None) and self.overlay_window.winfo_exists():
                if not self.drawing_data:
                    self.status_var.set("❌ Нет данных для рисования! Обработайте изображение сначала.")
                    return
                self.drawing_state = "drawing"
                self.stop_event.clear()
                self.pause_event.set()
                self.drawing_thread = threading.Thread(target=self.draw_controller, daemon=True)
                self.drawing_thread.start()
        elif self.drawing_state == "drawing":
            self.drawing_state = "paused"
            self.pause_event.clear()
            self.status_var.set("⏸️ Пауза. Нажмите Старт для продолжения.")
        elif self.drawing_state == "paused":
            self.drawing_state = "drawing"
            self.pause_event.set()
            self.status_var.set("▶️ Продолжение рисования...")

    def stop_drawing(self):
        if self.drawing_state != "idle":
            self.drawing_state = "stopping"
            self.stop_event.set()
            self.pause_event.set()
            self.status_var.set("🛑 Остановка... Прогресс сохранен.")

    def reset_progress(self):
        self.last_progress_index = 0
        self.progress_bar['value'] = 0
        self.etr_label.config(text="Время: --:--")

    def get_pixel_color(self, x, y):
        if hasattr(self, 'color_image') and self.color_image is not None:
            if 0 <= y < self.color_image.shape[0] and 0 <= x < self.color_image.shape[1]:
                bgr = self.color_image[y, x]
                return (int(bgr[2]), int(bgr[1]), int(bgr[0]))
        return None

    def _is_color_white(self, color, threshold=245):
        """Checks if a color is close to white."""
        if color is None:
            return True 
        return all(c > threshold for c in color)

    def select_color(self, target_color):
        if not self.config_vars['color_mode'].get():
            return True

        if target_color == self.color_manager.current_color:
            return True

        if not self.hex_input_position: 
            self.status_var.set("❌ Поле для ввода HEX не настроено!")
            self.stop_drawing()
            return False
        
        hex_code = f'{target_color[0]:02x}{target_color[1]:02x}{target_color[2]:02x}'
        
        self.smooth_move(self.hex_input_position[0], self.hex_input_position[1])
        self.mouse.press()
        time.sleep(0.05)
        self.mouse.release()
        time.sleep(0.1)

        keyboard.press_and_release('ctrl+a')
        time.sleep(0.1)
        keyboard.press_and_release('delete')
        time.sleep(0.1)

        keyboard.write(hex_code)
        time.sleep(0.1)
        keyboard.press_and_release('enter')
        time.sleep(0.2)
        
        self.color_manager.current_color = target_color
        return True

    def ultra_precise_move(self, target_x, target_y):
        if self.stop_event.is_set():
            return
            
        if self.config_vars['turbo_mode'].get():
            self.mouse.set_position(target_x, target_y)
            return

        start_x, start_y = self.mouse.get_position()
        distance = math.hypot(target_x - start_x, target_y - start_y)
        
        if distance < 0.5:
            self.mouse.set_position(target_x, target_y)
            return
        
        speed = self.config_vars['movement_speed'].get()
        steps = max(3, int(distance / (speed / 6)))
                
        for i in range(1, steps + 1):
            if self.stop_event.is_set():
                break
                
            self.pause_event.wait()
            if self.stop_event.is_set():
                break
                
            t = i / steps
            eased_t = 1 - (1 - t) ** 2
            
            curr_x = start_x + (target_x - start_x) * eased_t
            curr_y = start_y + (target_y - start_y) * eased_t
            
            if self.config_vars['human_jitter'].get():
                jitter_range = 0.3
                curr_x += random.uniform(-jitter_range, jitter_range)
                curr_y += random.uniform(-jitter_range, jitter_range)
            
            self.mouse.set_position(curr_x, curr_y)
            
            delay = self.config_vars['step_pause'].get() / 1000
            if delay > 0:
                time.sleep(delay)
        
        self.mouse.set_position(target_x, target_y)
        
        if self.config_vars['micro_adjustments'].get():
            time.sleep(self.config_vars['stabilization_time'].get())
            
            actual_pos = self.mouse.get_position()
            error_x = abs(actual_pos[0] - target_x)
            error_y = abs(actual_pos[1] - target_y)
            
            if error_x > 1 or error_y > 1:
                self.mouse.set_position(target_x, target_y)
                time.sleep(0.02)

    def smooth_move(self, target_x, target_y):
        self.ultra_precise_move(target_x, target_y)

    def _keep_alive_nudge(self):
        while self.drawing_state in ["drawing", "paused"] and not self.stop_event.is_set():
            try:
                if (self.config_vars['keep_alive_nudge'].get() and 
                    self.drawing_state == "drawing" and 
                    self.pause_event.is_set()):
                    
                    pos = self.mouse.get_position()
                    self.mouse.set_position(pos[0] + 1, pos[1])
                    time.sleep(0.01)
                    self.mouse.set_position(pos[0], pos[1])
                    
                time.sleep(self.config_vars['nudge_interval'].get())
            except:
                break

    def draw_controller(self):
        if not (getattr(self, 'overlay_window', None) and self.overlay_window.winfo_exists()):
            self.status_var.set("❌ Ошибка: оверлей не найден!")
            self.drawing_state = "idle"
            return
        
        if not self.processing_done_event.is_set():
            self.root.after(0, lambda: self.status_var.set("⏳ Ожидание завершения обработки..."))
            self.processing_done_event.wait()
            
        start_x = self.overlay_window.winfo_x()
        start_y = self.overlay_window.winfo_y()
        
        self.overlay_window.withdraw()
        time.sleep(0.3)
        self.color_manager.current_color = None # Reset current color before drawing
        
        if self.config_vars['keep_alive_nudge'].get():
            self.keep_alive_thread = threading.Thread(target=self._keep_alive_nudge, daemon=True)
            self.keep_alive_thread.start()
            
        try:
            if self.config_vars['color_mode'].get():
                self.perform_color_grouped_drawing(start_x, start_y)
            else:
                draw_mode = self.config_vars['drawing_mode'].get()
                if draw_mode == 'pixel_grid':
                    self.perform_pixel_grid_drawing(start_x, start_y)
                else:
                    self.perform_path_based_drawing(start_x, start_y)

        except Exception as e:
            error_msg = f"❌ Ошибка рисования: {str(e)[:50]}"
            self.status_var.set(error_msg)
        finally:
            if self.drawing_state == "drawing":
                self.status_var.set("✅ Рисование завершено успешно!")
            elif self.drawing_state == "stopping":
                self.status_var.set("⏹️ Рисование остановлено.")
                
            self.drawing_state = "idle"
            self.stop_event.clear()
            
            if (getattr(self, 'overlay_window', None) and 
                self.overlay_window.winfo_exists()):
                self.overlay_window.deiconify()

    def perform_color_grouped_drawing(self, start_x, start_y):
        total_items = sum(len(items) for items in self.color_grouped_data.values())
        if total_items == 0:
            self.status_var.set("⚠️ Нет данных для рисования.")
            return

        self.progress_bar['maximum'] = total_items
        self.progress_bar['value'] = 0
        items_drawn = 0
        start_time = time.time()
        draw_mode = self.config_vars['drawing_mode'].get()
        
        for color, items in self.color_grouped_data.items():
            if self.stop_event.is_set(): break
            
            self.status_var.set(f"🎨 Выбор цвета {color}...")
            if not self.select_color(color):
                items_drawn += len(items)
                self.progress_bar['value'] = items_drawn
                continue

            for item in items:
                if self.stop_event.is_set(): break
                self.pause_event.wait()
                if self.stop_event.is_set(): break

                if draw_mode == 'pixel_grid':
                    self._draw_single_pixel(item, start_x, start_y)
                else:
                    self._draw_single_path(item, start_x, start_y)

                items_drawn += 1
                self.progress_bar['value'] = items_drawn
                self.status_var.set(f"🖊️ Прогресс: {items_drawn}/{total_items}")
                
                elapsed = time.time() - start_time
                if items_drawn > 1 and elapsed > 1:
                    speed = items_drawn / elapsed
                    etr = (total_items - items_drawn) / speed if speed > 0 else 0
                    minutes, seconds = divmod(int(etr), 60)
                    self.etr_label.config(text=f"Время: {minutes:02d}:{seconds:02d}")

        self.reset_progress()
    
    def _draw_single_pixel(self, pos, start_x, start_y):
        grid_size = self.config_vars['pixel_grid_size'].get()
        target_x = start_x + pos[0]
        target_y = start_y + pos[1]
        
        if grid_size <= 1:
            self.ultra_precise_move(target_x, target_y)
            self.mouse.press()
            time.sleep(0.01)
            self.mouse.release()
        else:
            self.ultra_precise_move(target_x, target_y)
            self.mouse.press()
            self.ultra_precise_move(target_x + grid_size - 1, target_y)
            self.ultra_precise_move(target_x + grid_size - 1, target_y + grid_size - 1)
            self.ultra_precise_move(target_x, target_y + grid_size - 1)
            self.ultra_precise_move(target_x, target_y)
            self.mouse.release()

    def _draw_single_path(self, path, start_x, start_y):
        if not path: return
        
        turbo = self.config_vars['turbo_mode'].get()
        click_duration = self.config_vars['click_duration'].get() / 1000
        action_pause = self.config_vars['action_pause'].get() / 1000

        try:
            path_start_x = start_x + path[0][0]
            path_start_y = start_y + path[0][1]
            
            self.ultra_precise_move(path_start_x, path_start_y)
            if self.stop_event.is_set(): return
                
            self.mouse.press()
            if click_duration > 0 and not turbo:
                time.sleep(click_duration)
            
            for p2 in path[1:]:
                if self.stop_event.is_set(): break
                self.pause_event.wait()
                if self.stop_event.is_set(): break
                    
                target_x = start_x + p2[0]
                target_y = start_y + p2[1]
                self.ultra_precise_move(target_x, target_y)
            
            self.mouse.release()

            if not turbo and action_pause > 0:
                time.sleep(action_pause)
            
            if not turbo and random.random() < self.config_vars['random_pause_chance'].get() / 100:
                pause_time = random.uniform(0.01, self.config_vars['max_pause_duration'].get() / 1000)
                time.sleep(pause_time)
        except Exception as e:
            print(f"Ошибка при рисовании пути: {e}")

    def perform_pixel_grid_drawing(self, start_x, start_y):
        if not self.drawing_data:
            self.status_var.set("⚠️ Нет пикселей для рисования в режиме сетки.")
            return

        total_pixels = len(self.drawing_data)
        self.progress_bar['maximum'] = total_pixels
        start_time = time.time()

        for idx, (pos, color) in enumerate(self.drawing_data):
            if self.stop_event.is_set(): return
            self.pause_event.wait()
            if self.stop_event.is_set(): break

            self.status_var.set(f"🖊️ Пиксель {idx + 1}/{total_pixels}")
            self.progress_bar['value'] = idx + 1
            
            self.select_color(color)
            self._draw_single_pixel(pos, start_x, start_y)

            elapsed = time.time() - start_time
            if idx > 0 and elapsed > 1:
                speed = idx / elapsed
                etr = (total_pixels - idx) / speed if speed > 0 else 0
                minutes, seconds = divmod(int(etr), 60)
                self.etr_label.config(text=f"Время: {minutes:02d}:{seconds:02d}")

        self.reset_progress()

    def perform_path_based_drawing(self, start_x, start_y):
        if not self.drawing_data:
            self.status_var.set("⚠️ Нет данных для рисования.")
            return
            
        total_paths = len(self.drawing_data)
        self.progress_bar['maximum'] = total_paths
        start_time = time.time()
        
        for path_idx in range(self.last_progress_index, total_paths):
            if self.stop_event.is_set():
                self.last_progress_index = path_idx
                return
                
            self.status_var.set(f"🖊️ Путь {path_idx + 1}/{total_paths}")
            self.progress_bar['value'] = path_idx + 1
            
            self.pause_event.wait()
            if self.stop_event.is_set(): break
                
            path, color = self.drawing_data[path_idx]
            self.select_color(color)
            self._draw_single_path(path, start_x, start_y)
            
            elapsed = time.time() - start_time
            if path_idx > 0 and elapsed > 1:
                speed = (path_idx + 1) / elapsed
                etr = (total_paths - path_idx - 1) / speed if speed > 0 else 0
                minutes, seconds = divmod(int(etr), 60)
                self.etr_label.config(text=f"Время: {minutes:02d}:{seconds:02d}")
                
        self.reset_progress()

    def save_config(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            title="Сохранить конфигурацию"
        )
        
        if not filepath:
            return
            
        try:
            config_data = {key: var.get() for key, var in self.config_vars.items()}
            if self.hex_input_position:
                config_data['hex_input_position'] = self.hex_input_position
                
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
                
            self.status_var.set("💾 Конфигурация сохранена.")
            
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить:\n{e}")

    def load_config(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            title="Загрузить конфигурацию"
        )
        
        if not filepath:
            return
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                
            for key, value in config_data.items():
                if key in self.config_vars:
                    self.config_vars[key].set(value)
                elif key == 'hex_input_position':
                    self.hex_input_position = tuple(value)
                    self.hex_info_label.config(text=f"✅ Поле HEX настроено на {self.hex_input_position}", foreground='green')
                    
            self.toggle_threshold_mode()
            self.toggle_simplification_mode()
            self.toggle_turbo_mode()
            self.toggle_color_mode()
            
            self.status_var.set("📂 Конфигурация загружена.")
            
        except Exception as e:
            messagebox.showerror("Ошибка загрузки", f"Не удалось загрузить:\n{e}")


if __name__ == "__main__":
    try:
        root = tk.Tk()
        
        try:
            root.iconbitmap(default="icon.ico")
        except:
            pass
            
        app = AutoDrawerApp(root)
        
        def on_closing():
            try:
                if app.drawing_state != "idle":
                    app.emergency_stop()
                    time.sleep(0.5)
                    
                if (getattr(app, 'overlay_window', None) and 
                    app.overlay_window.winfo_exists()):
                    app.overlay_window.destroy()
                    
                if (getattr(app, 'setup_window', None) and 
                    app.setup_window.winfo_exists()):
                    app.setup_window.destroy()
                    
            finally:
                root.destroy()
                
        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("Произошла критическая ошибка. Нажмите Enter для выхода...")