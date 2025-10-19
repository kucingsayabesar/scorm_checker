import tkinter as tk
from tkinter import filedialog, scrolledtext
import customtkinter as ctk
import os
import sys
import subprocess
import webview
import csv
from datetime import datetime
from checker import check_scorm, generate_html_report

# Создание папок
os.makedirs("results", exist_ok=True)
os.makedirs("lms_db", exist_ok=True)

app = tk.Tk()
app.title("SCORM Checker embedded: Blade RUNNER Edition")
app.geometry("512x512")
app.configure(bg="#0f0c1a")
app.resizable(False, False)

current_zip_path = None
launch_file_path = None
check_log_lines = []

log_box = scrolledtext.ScrolledText(app, font=("Consolas", 10), bg="#1a1a2e", fg="#00ffe1",
                                    insertbackground="#00ffe1", bd=0)
log_box.pack(fill='both', expand=True, padx=10, pady=10)
log_box.tag_config("ok", foreground="#00ff88")
log_box.tag_config("warn", foreground="#ffcc00")
log_box.tag_config("err", foreground="#ff003c")
log_box.tag_config("normal", foreground="#00ffe1")
log_box.configure(state='disabled')

def insert_log_line(text_widget, line):
    tag = "ok" if "✅" in line else "warn" if "⚠️" in line else "err" if "❌" in line else "normal"
    text_widget.configure(state='normal')
    text_widget.insert(tk.END, line + "\n", tag)
    text_widget.configure(state='disabled')
    text_widget.see(tk.END)

def log_to_gui(message, tag=None):
    if tag:
        log_box.configure(state='normal')
        log_box.insert(tk.END, message + "\n", tag)
        log_box.configure(state='disabled')
    else:
        insert_log_line(log_box, message)
    log_box.see(tk.END)

log_to_gui("👤 Пользователь: Jesse Pinkman (ID: user01)", "ok")

class ScormJSBridge:
    def __init__(self):
        self.user_id = "user01"
        self.user_name = "Jesse Pinkman"
        self.lesson_id = "material_scorm"
        self.scorm_data = {
            # Эмуляция начальных значений SCORM 1.2
            "cmi.core.student_id": self.user_id,
            "cmi.core.student_name": self.user_name,
            "cmi.core.lesson_status": "not attempted" # Начальный статус
        }

    def scorm_log(self, name, value):
        log_to_gui(f"[SCORM API] {name} = {value}")
        # Сохраняем все вызовы LMSSetValue по их ключу.
        self.scorm_data[name] = value

        # ЭКСПОРТ: При LMSFinish (включая закрытие окна) ИЛИ LMSCommit
        if name in ("LMSFinish", "LMSCommit"):
            log_to_gui(f"📝 Получена команда {name}. Экспортирую CSV-отчёт.", "ok")
            self.export_csv()

    def LMSGetValue(self, name):
        # Обеспечиваем выдачу данных пользователя
        if name in ("cmi.core.student_name", "cmi.learner_name"):
            value = self.user_name
        elif name in ("cmi.core.student_id", "cmi.learner_id"):
            value = self.user_id
        else:
            value = self.scorm_data.get(name, "")
            
        log_to_gui(f"[LMSGetValue] {name} → {value}")
        return value

    def export_csv(self):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"scorm_report_{self.user_id}_{timestamp}.csv"
        full_path = os.path.join("results", filename)

        # ЛОГИКА СТАТУСА: отслеживаем только completed/passed
        status = self.scorm_data.get("cmi.core.lesson_status")
        
        if status in ("passed", "completed"):
            final_score = "100"
        else:
            if not status or status == "not attempted":
                status = "не передан"
            
            final_score = "0"
            
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        headers = ["ID пользователя", "Имя", "ID курса", "Статус", "Баллы", "Дата и время"]
        row = [self.user_id, self.user_name, self.lesson_id, status, final_score, time_str]

        try:
            with open(full_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.writer(csvfile, delimiter=";")
                writer.writerow(headers)
                writer.writerow(row)

            log_to_gui(f"📤 CSV-отчёт экспортирован: {full_path}", "ok")

            try:
                self.open_file(full_path)
            except Exception as e:
                log_to_gui(f"⚠️ Не удалось открыть CSV автоматически: {e}", "warn")

        except Exception as e:
            log_to_gui(f"❌ Ошибка при экспорте CSV: {e}", "err")

    @staticmethod
    def open_file(path):
        if sys.platform.startswith('darwin'):  # macOS
            subprocess.call(["open", path])
        elif os.name == 'nt':  # Windows
            os.startfile(path)
        elif os.name == 'posix':  # Linux
            subprocess.call(["xdg-open", path])

def open_scorm_embedded():
    global launch_file_path
    if not launch_file_path or not os.path.exists(launch_file_path):
        log_to_gui("❌ SCORM-файл не найден", "err")
        return

    file_url = f"file:///{launch_file_path.replace(os.sep, '/')}"
    js_api = ScormJSBridge()

    injected_js = """
    window.API = {
        LMSInitialize: function(arg) {
            window.pywebview.api.scorm_log("LMSInitialize", arg);
            return "true";
        },
        LMSSetValue: function(name, value) {
            window.pywebview.api.scorm_log(name, value);
            return "true";
        },
        LMSCommit: function(arg) {
            window.pywebview.api.scorm_log("LMSCommit", arg);
            return "true";
        },
        LMSFinish: function(arg) {
            window.pywebview.api.scorm_log("LMSFinish", arg);
            return "true";
        },
        LMSGetValue: function(name) {
            return window.pywebview.api.LMSGetValue(name);
        },
        LMSGetLastError: function() { return "0"; },
        LMSGetErrorString: function(code) { return "No error"; },
        LMSGetDiagnostic: function(code) { return "No diagnostic"; }
    };

    // ОБРАБОТЧИК ЗАКРЫТИЯ ОКНА
    window.onbeforeunload = function() {
        window.pywebview.api.scorm_log('LMSFinish', '');
    };
    """

    window = webview.create_window(
        title="SCORM Viewer",
        url=file_url,
        js_api=js_api,
        width=1024,
        height=768,
        background_color="#0f0c1a"
    )

    def on_loaded():
        window.evaluate_js(injected_js)

    window.events.loaded += on_loaded
    webview.start()

def select_file():
    global current_zip_path, launch_file_path, check_log_lines
    filepath = filedialog.askopenfilename(filetypes=[("SCORM ZIP", "*.zip")])
    if not filepath:
        return

    current_zip_path = filepath
    check_log_lines.clear()
    log_box.configure(state='normal')
    log_box.delete(1.0, tk.END)
    log_box.configure(state='disabled')
    log_to_gui(f"📦 Выбран SCORM ZIP: {filepath}")

    results, launch_path = check_scorm(filepath)
    launch_file_path = launch_path

    for line in results:
        insert_log_line(log_box, line)
        check_log_lines.append(line)

    with open("scorm_check_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(check_log_lines))

    generate_html_report(check_log_lines)

    if launch_file_path and os.path.exists(launch_file_path):
        open_btn.configure(state="normal")
    else:
        log_to_gui("❌ Не найден index.html")

ctk.CTkButton(master=app, text="🔍 Выбрать SCORM ZIP", command=select_file,
              fg_color="#1a1a2e", hover_color="#00ffe1", text_color="#00ffe1",
              font=("Consolas", 13, "bold"), corner_radius=12, width=240, height=40).pack(pady=10)

open_btn = ctk.CTkButton(master=app, text="🚀 Открыть SCORM", command=open_scorm_embedded,
                         state="disabled", fg_color="#1a1a2e", hover_color="#00ffcc", text_color="#00ffe1",
                         font=("Consolas", 12, "bold"), corner_radius=12, width=240, height=36)
open_btn.pack(pady=5)

tk.Label(app, text="Вопросы?: tg @kucingsayabesar", fg="#00ffe1", bg="#0f0c1a",
         font=("Consolas", 9)).pack(side="bottom", anchor="e", padx=10, pady=5)

app.mainloop()