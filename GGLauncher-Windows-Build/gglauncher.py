# GGLauncher — Python + PySide6
# Windows 10/11. Install: py -m pip install PySide6 minecraft-launcher-lib requests
# Microsoft login requires an Azure app CLIENT_ID and redirect URI configured for a public client.

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import minecraft_launcher_lib
import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QStackedWidget, QFrame,
    QMessageBox, QFileDialog, QLineEdit, QComboBox, QSpinBox, QProgressBar,
    QCheckBox, QInputDialog, QScrollArea
)

APP_NAME = "GGLauncher"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path.home() / ".gglauncher"
DATA_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"

# 1) Create an app in Microsoft/Azure and paste its Application (client) ID here.
# 2) Set REDIRECT_URI to the redirect URI configured for that app.
CLIENT_ID = "PASTE_YOUR_MICROSOFT_CLIENT_ID_HERE"
REDIRECT_URI = "http://localhost"

DEFAULT_CONFIG = {
    "game_dir": str(Path.home() / ".minecraft"),
    "version": "latest-release",
    "ram_gb": 4,
    "width": 1280,
    "height": 720,
    "fullscreen": False,
    "last_skin": "",
}


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback.copy() if isinstance(fallback, dict) else fallback


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


config = read_json(CONFIG_FILE, DEFAULT_CONFIG)
for key, value in DEFAULT_CONFIG.items():
    config.setdefault(key, value)
accounts = read_json(ACCOUNTS_FILE, [])


def game_dir():
    p = Path(config["game_dir"]).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


class TaskThread(QThread):
    progress = Signal(int)
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit, self.status.emit)
            self.done.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class GGLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 760)
        self.setMinimumSize(1000, 650)
        self.current_account = 0 if accounts else -1
        self.task = None
        self.setStyleSheet(STYLE)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 16, 12, 12)
        side.setSpacing(9)
        logo = QLabel("🟣  GGLauncher")
        logo.setObjectName("logo")
        side.addWidget(logo)
        side.addSpacing(15)

        self.stack = QStackedWidget()
        self.nav_buttons = []
        pages = [
            ("⌂   Главная", self.home_page),
            ("♟   Скин", self.skin_page),
            ("▤   Версии", self.versions_page),
            ("✿   Моды", self.mods_page),
            ("♙   Аккаунты", self.accounts_page),
            ("⚙   Настройки", self.settings_page),
        ]
        for i, (name, builder) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, idx=i: self.navigate(idx))
            side.addWidget(b)
            self.nav_buttons.append(b)
            self.stack.addWidget(builder())
        side.addStretch()
        side.addWidget(QLabel("GGLauncher • beta"))
        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)
        self.navigate(0)
        self.refresh_home()

    def page(self, title):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("heading")
        layout.addWidget(heading)
        return w, layout

    def card(self, title, text=""):
        f = QFrame()
        f.setObjectName("card")
        l = QVBoxLayout(f)
        h = QLabel(title)
        h.setObjectName("cardTitle")
        l.addWidget(h)
        if text:
            l.addWidget(QLabel(text))
        return f, l

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == index)
        if index == 0:
            self.refresh_home()
        elif index == 3:
            self.refresh_mods()
        elif index == 4:
            self.refresh_accounts()
        elif index == 2:
            self.refresh_versions()

    def set_status(self, text):
        self.statusBar().showMessage(text, 10000)

    def run_task(self, fn, finished=None):
        if self.task and self.task.isRunning():
            QMessageBox.information(self, APP_NAME, "Дождись завершения текущей операции.")
            return
        self.task = TaskThread(fn)
        target_progress = getattr(self, "install_progress", None)
        if target_progress is not None:
            self.task.progress.connect(target_progress.setValue)
        self.task.status.connect(self.set_status)
        self.task.done.connect(lambda result: finished(result) if finished else None)
        self.task.failed.connect(lambda err: QMessageBox.critical(self, "Ошибка", err[-3500:]))
        self.task.start()

    # HOME
    def home_page(self):
        w, l = self.page("GGLauncher")
        hero, hl = self.card("Играй в Minecraft по-новому!", "Выбирай версию, управляй модами и запускай игру.")
        hl.addSpacing(10)
        self.home_account = QLabel("Аккаунт: не добавлен")
        self.home_version = QLabel("Версия: не выбрана")
        hl.addWidget(self.home_account)
        hl.addWidget(self.home_version)
        self.play_btn = QPushButton("▶   ИГРАТЬ")
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self.launch_game)
        hl.addWidget(self.play_btn)
        l.addWidget(hero)
        row = QHBoxLayout()
        for title, text, target in [
            ("Версия", "Выбрать Minecraft", 2),
            ("Моды", "Управление модами", 3),
            ("Аккаунт", "Войти или переключить", 4),
        ]:
            c, cl = self.card(title, text)
            b = QPushButton("Открыть →")
            b.clicked.connect(lambda checked=False, idx=target: self.navigate(idx))
            cl.addWidget(b)
            row.addWidget(c)
        l.addLayout(row)
        l.addStretch()
        return w

    def refresh_home(self):
        if not hasattr(self, "home_account"):
            return
        acc = accounts[self.current_account] if 0 <= self.current_account < len(accounts) else None
        self.home_account.setText("Аккаунт: " + (acc.get("name", "") if acc else "не добавлен"))
        self.home_version.setText("Версия: " + str(config.get("version", "latest-release")))
        self.play_btn.setEnabled(bool(acc and acc.get("access_token")))
        self.play_btn.setText("▶   ИГРАТЬ" if acc else "СНАЧАЛА ВОЙДИ В MICROSOFT")

    # SKINS — local PNG selection/preview. Uploading to Mojang profile is not faked.
    def skin_page(self):
        w, l = self.page("Редактор скина")
        row = QHBoxLayout()
        preview_card, pc = self.card("Предпросмотр", "Выбери PNG-файл скина Minecraft.")
        self.skin_preview = QLabel("Нет выбранного скина")
        self.skin_preview.setAlignment(Qt.AlignCenter)
        self.skin_preview.setMinimumSize(220, 300)
        self.skin_preview.setObjectName("preview")
        pc.addWidget(self.skin_preview)
        choose = QPushButton("Выбрать PNG с компьютера")
        choose.clicked.connect(self.choose_skin)
        pc.addWidget(choose)
        self.skin_variant = QComboBox()
        self.skin_variant.addItems(["classic", "slim"])
        pc.addWidget(QLabel("Тип модели"))
        pc.addWidget(self.skin_variant)
        apply_skin = QPushButton("Применить скин к аккаунту")
        apply_skin.setObjectName("primary")
        apply_skin.clicked.connect(self.apply_skin_to_account)
        pc.addWidget(apply_skin)
        row.addWidget(preview_card, 1)
        info, il = self.card("Поддержка скинов", "Можно выбрать и сохранить файл PNG для дальнейшего использования.")
        il.addWidget(QLabel("Автоматическая загрузка скина в профиль Minecraft требует отдельной реализации API и авторизованной сессии."))
        row.addWidget(info, 1)
        l.addLayout(row)
        l.addStretch()
        self.load_skin_preview()
        return w

    def choose_skin(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать скин", "", "PNG images (*.png)")
        if not path:
            return
        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, APP_NAME, "Не удалось открыть PNG-файл.")
            return
        target = DATA_DIR / "skin.png"
        shutil.copy2(path, target)
        config["last_skin"] = str(target)
        write_json(CONFIG_FILE, config)
        self.load_skin_preview()

    def apply_skin_to_account(self):
        path = config.get("last_skin", "")
        if not path or not Path(path).exists():
            QMessageBox.information(self, APP_NAME, "Сначала выбери PNG-файл скина.")
            return
        if not (0 <= self.current_account < len(accounts)):
            QMessageBox.warning(self, APP_NAME, "Сначала войди в Microsoft/Minecraft аккаунт.")
            self.navigate(4)
            return
        pix = QPixmap(path)
        if (pix.size().width(), pix.size().height()) not in ((64, 64), (64, 32), (128, 128), (128, 64)):
            QMessageBox.warning(self, APP_NAME, "Ожидается PNG-скин стандартного размера 64×64 или 64×32 (можно 128×128).")
            return
        acc = accounts[self.current_account]
        try:
            with open(path, "rb") as skin_file:
                response = requests.post(
                    "https://api.minecraftservices.com/minecraft/profile/skins",
                    headers={"Authorization": "Bearer " + acc["access_token"]},
                    data={"variant": self.skin_variant.currentText().upper()},
                    files={"file": ("skin.png", skin_file, "image/png")},
                    timeout=45,
                )
            if response.status_code in (200, 202, 204):
                QMessageBox.information(self, APP_NAME, "Скин отправлен в профиль Minecraft.")
            else:
                QMessageBox.warning(self, APP_NAME, f"Minecraft API вернул ошибку {response.status_code}:\n{response.text[:1000]}")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Не удалось загрузить скин: {e}")

    def load_skin_preview(self):
        if not hasattr(self, "skin_preview"):
            return
        path = config.get("last_skin", "")
        pix = QPixmap(path) if path and Path(path).exists() else QPixmap()
        if pix.isNull():
            self.skin_preview.setText("Нет выбранного скина")
        else:
            self.skin_preview.setPixmap(pix.scaled(190, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # VERSIONS
    def versions_page(self):
        w, l = self.page("Выбор версии")
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.version_list = QListWidget()
        self.version_list.currentItemChanged.connect(self.select_version)
        left.addWidget(self.version_list)
        refresh = QPushButton("Обновить список версий")
        refresh.clicked.connect(self.refresh_versions)
        left.addWidget(refresh)
        row.addLayout(left, 1)
        right = QVBoxLayout()
        self.selected_version_label = QLabel("Выбери версию Minecraft")
        self.selected_version_label.setObjectName("cardTitle")
        right.addWidget(self.selected_version_label)
        self.install_progress = QProgressBar()
        self.install_progress.setValue(0)
        right.addWidget(self.install_progress)
        self.install_btn = QPushButton("⬇   УСТАНОВИТЬ ВЕРСИЮ")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.install_selected_version)
        right.addWidget(self.install_btn)
        use_btn = QPushButton("Использовать выбранную версию")
        use_btn.clicked.connect(self.use_selected_version)
        right.addWidget(use_btn)
        right.addStretch()
        row.addLayout(right, 1)
        l.addLayout(row)
        self.refresh_versions()
        return w

    def refresh_versions(self):
        if not hasattr(self, "version_list"):
            return
        self.version_list.clear()
        try:
            versions = minecraft_launcher_lib.utils.get_available_versions(game_dir())
            # Display newest entries first; releases are shown before snapshots.
            versions = sorted(versions, key=lambda x: (x.get("type") != "release", x.get("id", "")), reverse=False)
            for v in versions[:250]:
                item = QListWidgetItem(f"{v['id']}   ·   {v.get('type', 'custom')}")
                item.setData(Qt.UserRole, v["id"])
                self.version_list.addItem(item)
            latest = minecraft_launcher_lib.utils.get_latest_version().get("release")
            if latest and not any(self.version_list.item(i).data(Qt.UserRole) == latest for i in range(self.version_list.count())):
                item = QListWidgetItem(f"{latest}   ·   latest release")
                item.setData(Qt.UserRole, latest)
                self.version_list.insertItem(0, item)
            self.set_status(f"Загружено версий: {self.version_list.count()}")
        except Exception as e:
            self.set_status(f"Не удалось получить список версий: {e}")

    def select_version(self, current, previous=None):
        if current:
            self.selected_version_label.setText("Выбрана версия: " + str(current.data(Qt.UserRole)))

    def selected_version(self):
        item = self.version_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def use_selected_version(self):
        v = self.selected_version()
        if not v:
            QMessageBox.information(self, APP_NAME, "Сначала выбери версию.")
            return
        config["version"] = v
        write_json(CONFIG_FILE, config)
        self.refresh_home()
        self.set_status(f"Выбрана версия {v}")

    def install_selected_version(self):
        version = self.selected_version()
        if not version:
            QMessageBox.information(self, APP_NAME, "Сначала выбери версию.")
            return
        self.install_progress.setValue(0)
        def work(progress, status):
            callback = {
                "setStatus": lambda value: status(str(value)),
                "setProgress": lambda value: progress(int(value)),
                "setMax": lambda value: None,
            }
            minecraft_launcher_lib.install.install_minecraft_version(version, game_dir(), callback=callback)
            return version
        def finished(v):
            self.install_progress.setValue(100)
            self.set_status(f"Minecraft {v} установлен")
            QMessageBox.information(self, APP_NAME, f"Версия {v} успешно установлена.")
        self.run_task(work, finished)

    # MODS
    def mods_page(self):
        w, l = self.page("Моды")
        self.mods_list = QListWidget()
        l.addWidget(self.mods_list, 1)
        row = QHBoxLayout()
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh_mods)
        toggle = QPushButton("Включить / выключить выбранный")
        toggle.clicked.connect(self.toggle_mod)
        open_folder = QPushButton("Открыть папку mods")
        open_folder.clicked.connect(self.open_mods_folder)
        row.addWidget(refresh)
        row.addWidget(toggle)
        row.addWidget(open_folder)
        l.addLayout(row)
        self.refresh_mods()
        return w

    def mods_folder(self):
        p = Path(game_dir()) / "mods"
        p.mkdir(exist_ok=True)
        return p

    def refresh_mods(self):
        if not hasattr(self, "mods_list"):
            return
        self.mods_list.clear()
        files = sorted(list(self.mods_folder().glob("*.jar")) + list(self.mods_folder().glob("*.jar.disabled")))
        for p in files:
            state = "ВКЛЮЧЁН" if p.suffix == ".jar" else "ВЫКЛЮЧЕН"
            item = QListWidgetItem(f"{p.name}   —   {state}")
            item.setData(Qt.UserRole, str(p))
            self.mods_list.addItem(item)
        if not files:
            self.mods_list.addItem("Папка mods пуста. Помести сюда .jar-файлы модов.")

    def toggle_mod(self):
        item = self.mods_list.currentItem()
        if not item or not item.data(Qt.UserRole):
            return
        p = Path(item.data(Qt.UserRole))
        target = p.with_suffix("") if p.name.endswith(".jar.disabled") else Path(str(p) + ".disabled")
        try:
            p.rename(target)
            self.refresh_mods()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Не удалось изменить мод: {e}")

    def open_mods_folder(self):
        os.startfile(str(self.mods_folder())) if os.name == "nt" else subprocess.Popen(["xdg-open", str(self.mods_folder())])

    # ACCOUNTS
    def accounts_page(self):
        w, l = self.page("Аккаунты")
        self.accounts_list = QListWidget()
        l.addWidget(self.accounts_list, 1)
        row = QHBoxLayout()
        add = QPushButton("＋  Добавить Microsoft аккаунт")
        add.setObjectName("primary")
        add.clicked.connect(self.microsoft_login)
        use = QPushButton("Сделать активным")
        use.clicked.connect(self.activate_account)
        remove = QPushButton("Удалить из лаунчера")
        remove.clicked.connect(self.remove_account)
        row.addWidget(add)
        row.addWidget(use)
        row.addWidget(remove)
        l.addLayout(row)
        self.refresh_accounts()
        return w

    def refresh_accounts(self):
        if not hasattr(self, "accounts_list"):
            return
        self.accounts_list.clear()
        for i, acc in enumerate(accounts):
            active = "  • АКТИВНЫЙ" if i == self.current_account else ""
            self.accounts_list.addItem(f"{acc.get('name', 'Minecraft user')}{active}")

    def microsoft_login(self):
        if CLIENT_ID.startswith("PASTE_"):
            QMessageBox.warning(self, "Нужна настройка Microsoft", "Сначала создай приложение Microsoft/Azure, затем вставь CLIENT_ID в начало файла gglauncher.py. Без этого настоящая авторизация невозможна.")
            return
        try:
            login_url, state, verifier = minecraft_launcher_lib.microsoft_account.get_secure_login_data(CLIENT_ID, REDIRECT_URI)
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(login_url))
            code_url, ok = QInputDialog.getText(self, "Вход Microsoft", "Войди в браузере. После перенаправления скопируй полный URL из адресной строки и вставь сюда:")
            if not ok or not code_url.strip():
                return
            auth_code = minecraft_launcher_lib.microsoft_account.parse_auth_code_url(code_url.strip(), state)
            data = minecraft_launcher_lib.microsoft_account.complete_login(CLIENT_ID, None, REDIRECT_URI, auth_code, verifier)
            acc = {"name": data["name"], "id": data["id"], "access_token": data["access_token"], "refresh_token": data.get("refresh_token", "")}
            # Keep only the data needed by the launcher. Protect this file as it contains credentials.
            existing = next((i for i, a in enumerate(accounts) if a.get("id") == acc["id"]), None)
            if existing is None:
                accounts.append(acc)
                self.current_account = len(accounts) - 1
            else:
                accounts[existing] = acc
                self.current_account = existing
            write_json(ACCOUNTS_FILE, accounts)
            self.refresh_accounts()
            self.refresh_home()
            QMessageBox.information(self, APP_NAME, f"Вход выполнен: {acc['name']}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка входа", str(e))

    def activate_account(self):
        i = self.accounts_list.currentRow()
        if i < 0:
            return
        self.current_account = i
        self.refresh_accounts()
        self.refresh_home()

    def remove_account(self):
        i = self.accounts_list.currentRow()
        if i < 0:
            return
        if QMessageBox.question(self, APP_NAME, "Удалить сохранённый аккаунт из GGLauncher?") != QMessageBox.Yes:
            return
        accounts.pop(i)
        self.current_account = min(self.current_account, len(accounts) - 1)
        write_json(ACCOUNTS_FILE, accounts)
        self.refresh_accounts()
        self.refresh_home()

    # SETTINGS
    def settings_page(self):
        w, l = self.page("Настройки")
        c, cl = self.card("Параметры игры")
        cl.addWidget(QLabel("Папка Minecraft"))
        pathrow = QHBoxLayout()
        self.path_edit = QLineEdit(config["game_dir"])
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self.choose_game_dir)
        pathrow.addWidget(self.path_edit, 1)
        pathrow.addWidget(browse)
        cl.addLayout(pathrow)
        cl.addWidget(QLabel("Оперативная память (ГБ)"))
        self.ram_spin = QSpinBox()
        self.ram_spin.setRange(2, max(2, min(32, (os.cpu_count() or 4) * 2)))
        self.ram_spin.setValue(int(config["ram_gb"]))
        cl.addWidget(self.ram_spin)
        self.fullscreen_check = QCheckBox("Полноэкранный режим")
        self.fullscreen_check.setChecked(bool(config["fullscreen"]))
        cl.addWidget(self.fullscreen_check)
        save = QPushButton("Сохранить настройки")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        cl.addWidget(save)
        l.addWidget(c)
        l.addStretch()
        return w

    def choose_game_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Выбрать папку Minecraft", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def save_settings(self):
        config["game_dir"] = self.path_edit.text().strip() or DEFAULT_CONFIG["game_dir"]
        config["ram_gb"] = self.ram_spin.value()
        config["fullscreen"] = self.fullscreen_check.isChecked()
        write_json(CONFIG_FILE, config)
        self.set_status("Настройки сохранены")
        self.refresh_mods()
        self.refresh_home()

    # LAUNCH
    def launch_game(self):
        if not (0 <= self.current_account < len(accounts)):
            QMessageBox.warning(self, APP_NAME, "Сначала войди в лицензионный Microsoft/Minecraft аккаунт.")
            self.navigate(4)
            return
        acc = accounts[self.current_account]
        version = config.get("version", "latest-release")
        if version == "latest-release":
            version = minecraft_launcher_lib.utils.get_latest_version()["release"]
        if acc.get("refresh_token") and not CLIENT_ID.startswith("PASTE_"):
            try:
                refreshed = minecraft_launcher_lib.microsoft_account.complete_refresh(CLIENT_ID, acc["refresh_token"])
                acc.update({"name": refreshed["name"], "id": refreshed["id"], "access_token": refreshed["access_token"], "refresh_token": refreshed.get("refresh_token", acc["refresh_token"])})
                write_json(ACCOUNTS_FILE, accounts)
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Не удалось обновить сессию Microsoft. Попробуй войти снова.\n{e}")
                return
        ram = int(config.get("ram_gb", 4))
        options = {
            "username": acc["name"],
            "uuid": acc["id"],
            "token": acc["access_token"],
            "jvmArguments": [f"-Xmx{ram}G", f"-Xms{min(2, ram)}G"],
        }
        if config.get("fullscreen"):
            options["fullscreen"] = True
        else:
            options["resolutionWidth"] = int(config.get("width", 1280))
            options["resolutionHeight"] = int(config.get("height", 720))

        def work(progress, status):
            status(f"Проверка файлов Minecraft {version}…")
            minecraft_launcher_lib.install.install_minecraft_version(version, game_dir(), callback={
                "setStatus": lambda value: status(str(value)),
                "setProgress": lambda value: progress(int(value)),
                "setMax": lambda value: None,
            })
            command = minecraft_launcher_lib.command.get_minecraft_command(version, game_dir(), options)
            status("Запуск Minecraft…")
            subprocess.Popen(command, cwd=game_dir())
            return version
        def finished(v):
            self.set_status(f"Minecraft {v} запущен")
        self.run_task(work, finished)


STYLE = """
QMainWindow, QWidget { background: #09091b; color: #eeeeff; font-family: 'Segoe UI'; font-size: 14px; }
QFrame#sidebar { background: #101027; border: 1px solid #39206c; border-radius: 16px; }
QLabel#logo { color: white; font-size: 21px; font-weight: 800; padding: 8px; }
QLabel#heading { font-size: 27px; font-weight: 800; padding-bottom: 8px; }
QLabel#cardTitle { font-size: 19px; font-weight: 700; color: #ffffff; }
QFrame#card { background: #14142e; border: 1px solid #34205d; border-radius: 15px; padding: 14px; }
QLabel#preview { background: #0b0b20; border: 1px solid #5c22ba; border-radius: 12px; color: #aaa; }
QPushButton { background: #1b1b3b; color: #e9e4ff; border: 1px solid #39236c; border-radius: 9px; padding: 10px 13px; }
QPushButton:hover { border: 1px solid #a45bff; background: #29204e; }
QPushButton#nav { text-align: left; padding: 13px 12px; border: none; background: transparent; }
QPushButton#nav:checked { background: #5314d5; border: 1px solid #a35aff; font-weight: 700; }
QPushButton#primary { background: #6417ed; border: 1px solid #a65aff; color: white; font-weight: 800; padding: 14px; }
QPushButton#primary:hover { background: #7b2aff; }
QListWidget, QLineEdit, QComboBox, QSpinBox { background: #11112a; border: 1px solid #38245f; border-radius: 9px; padding: 9px; color: white; }
QListWidget::item { padding: 10px; border-bottom: 1px solid #242044; }
QListWidget::item:selected { background: #4c16ad; }
QProgressBar { background: #11112a; border: 1px solid #38245f; border-radius: 6px; text-align: center; height: 17px; }
QProgressBar::chunk { background: #852cff; border-radius: 5px; }
QCheckBox { spacing: 8px; }
QStatusBar { background: #101027; color: #c9baff; }
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = GGLauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
