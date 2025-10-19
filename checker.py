import zipfile
import os
import shutil
from lxml import etree
import re


def check_scorm(zip_path):
    results = []
    launch_path = None
    external_urls = set()

    tempdir = os.path.join(os.getcwd(), "extracted_scorm")
    if os.path.exists(tempdir):
        shutil.rmtree(tempdir)
    os.makedirs(tempdir, exist_ok=True)

    if not zipfile.is_zipfile(zip_path):
        return ["❌ Файл не является zip-архивом"], None

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(tempdir)
    except Exception as e:
        return [f"❌ Не удалось распаковать архив: {e}"], None

    manifest_path = os.path.join(tempdir, 'imsmanifest.xml')
    if not os.path.exists(manifest_path):
        results.append("❌ Отсутствует imsmanifest.xml")
        return results, None
    else:
        results.append("✅ Найден imsmanifest.xml")

    # --- XML парсинг и SCORM-версия ---
    try:
        tree = etree.parse(manifest_path)
        root = tree.getroot()

        manifest_id = root.attrib.get("identifier")
        if manifest_id:
            results.append("✅ Указан идентификатор манифеста")
        else:
            results.append("❌ Отсутствует атрибут 'identifier' у <manifest>")

        schema = root.find(".//{*}schema")
        if schema is not None and "SCORM" in schema.text:
            results.append(f"✅ SCORM-стандарт: {schema.text}")
        else:
            results.append("⚠️ Не указан SCORM schema или он нестандартный")

        version_warning = False
        schemaversion = root.find(".//{*}schemaversion")
        if schemaversion is not None:
            version = schemaversion.text.strip()
            results.append(f"✅ Версия SCORM: {version}")
            if version == "1.2":
                results.append("✅ Рекомендуемый формат SCORM 1.2")
            elif version.startswith("2004"):
                results.append("⚠️ SCORM 2004 — поддержка ограничена на платформе")
                version_warning = True
            else:
                results.append(f"⚠️ Неизвестная или нестандартная версия SCORM: {version}")
        else:
            results.append("⚠️ Не указана версия SCORM (schemaversion)")
    except Exception as e:
        results.append(f"❌ Ошибка парсинга imsmanifest.xml: {e}")
        return results, None

    # --- Детектор конструктора (по структуре курса) ---
    for f in os.listdir(tempdir):
        if f.lower().startswith("story") and f.lower().endswith(".html"):
            results.append("✅ Выявлен Articulate (Storyline) — рекомендуемый формат")
        if "ispring" in f.lower():
            if version_warning:
                results.append("❌ SCORM 2004 в iSpring — не поддерживается платформой")
            else:
                results.append("⚠️ Обнаружен iSpring — допускается только SCORM 1.2")

    # --- Поиск запускаемого ресурса ---
    resources = root.findall('.//{*}resource')
    if not resources:
        results.append("❌ В манифесте нет ресурсов (<resource>)")

    for res in resources:
        href = res.get('href')
        if href:
            possible_path = os.path.join(tempdir, href)
            if os.path.exists(possible_path):
                results.append(f"✅ Найден файл запуска: {href}")
                launch_path = possible_path
            else:
                results.append(f"❌ Указан файл запуска ({href}), но он отсутствует")
        else:
            results.append("⚠️ В ресурсе не указан атрибут href (файл запуска)")

    if not launch_path:
        index_root = os.path.join(tempdir, "index.html")
        if os.path.exists(index_root):
            launch_path = index_root
            results.append("⚠️ В манифесте нет рабочей ссылки, но найден index.html в корне архива")
        elif os.path.exists(os.path.join(tempdir, "res", "index.html")):
            launch_path = os.path.join(tempdir, "res", "index.html")
            results.append("⚠️ В манифесте нет рабочей ссылки, но найден index.html в папке /res")
        else:
            for root_dir, _, files in os.walk(tempdir):
                for file in files:
                    if file.lower() == "index.html":
                        launch_path = os.path.join(root_dir, file)
                        relative = os.path.relpath(launch_path, tempdir)
                        results.append(f"⚠️ В манифесте нет рабочей ссылки, но найден index.html: {relative}")
                        break
                if launch_path:
                    break

    # --- Поиск SCORM API вызовов и внешних URL ---
    scorm_calls = {
        "LMSInitialize": [],
        "Initialize(": [],
        "LMSFinish": [],
        "Terminate(": [],
        "LMSSetValue": [],
        "SetValue(": [],
        "LMSCommit": [],
        "Commit(": []
    }

    tracking_patterns = [
        "cmi.core.lesson_location",
        "cmi.suspend_data",
        "lesson_status",
        "success_status",
        "completed",
        "incomplete",
        "passed",
        "failed",
        "score.raw",
        "score.max",
        "score.min",
        "session_time"
    ]

    tracking_flags = {k: 0 for k in tracking_patterns}
    setvalue_count = 0
    url_pattern = re.compile(r'https?://[^\s\'"<>]+')

    for root_dir, _, files in os.walk(tempdir):
        for file in files:
            if file.endswith(('.js', '.html', '.htm', '.xml')):
                full_path = os.path.join(root_dir, file)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                        for call in scorm_calls:
                            if call in content:
                                relative_path = os.path.relpath(full_path, tempdir)
                                if relative_path not in scorm_calls[call]:
                                    scorm_calls[call].append(relative_path)
                        setvalue_count += content.count("SetValue")

                        for pattern in tracking_patterns:
                            if pattern in content:
                                tracking_flags[pattern] += 1

                        matches = url_pattern.findall(content)
                        for url in matches:
                            if not url.startswith("file://"):
                                external_urls.add(url.strip())
                except Exception as e:
                    results.append(f"⚠️ Ошибка при чтении {file}: {e}")

    found_any = False
    for call, files in scorm_calls.items():
        if files:
            found_any = True
            results.append(f"✅ Найден вызов {call} в:")
            for f in files:
                results.append(f"   └─ {f}")
    if not found_any:
        results.append("❌ Не найден ни один вызов SCORM API (LMSInitialize, LMSFinish, SetValue, Commit)")

    method_used = []
    if tracking_flags["completed"] or tracking_flags["incomplete"]:
        method_used.append("completed/incompleted")
    if tracking_flags["passed"] or tracking_flags["failed"]:
        method_used.append("passed/failed")

    if len(method_used) == 2:
        results.append("⚠️ Используются оба метода завершения курса (completed и passed)")
    elif method_used:
        results.append(f"✅ Метод завершения курса: {method_used[0]}")
    else:
        results.append("⚠️ Не удалось определить метод завершения (completed/incomplete или passed/failed)")

    if setvalue_count > 100:
        results.append("⚠️ Обнаружено более 100 вызовов SetValue — возможное переполнение буфера SCORM 1.2")

    if external_urls:
        results.append("⚠️ Найдены внешние обращения (возможна интернет-зависимость):")
        for url in sorted(external_urls):
            results.append(f"   └─ 🌐 {url}")
    else:
        results.append("✅ Не обнаружены внешние обращения — курс, вероятно, работает оффлайн")

    # 📊 Добавим информацию о передаваемых данных
    tracked = [k for k, v in tracking_flags.items() if v > 0]
    if tracked:
        results.append("\n📊 Передаваемые в LMS данные:")
        for key in tracked:
            results.append(f"   └─ {key} ({tracking_flags[key]} упоминаний)")
    else:
        results.append("📊 Не найдены передаваемые данные (SCORM tracking variables)")

        # 💾 Сохраняем передаваемые данные в JSON
    if tracked:
        import json
        json_data = {
            "scorm_variables_used": {
                k: tracking_flags[k] for k in tracked
            }
        }
        with open("scorm_data.json", "w", encoding="utf-8") as jf:
            json.dump(json_data, jf, indent=4, ensure_ascii=False)

    return results, launch_path


def generate_html_report(log_lines, output_path="scorm_report.html"):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>")
        f.write("<title>SCORM Report</title>")
        f.write("""
        <style>
            body { font-family: monospace; padding: 20px; background: #f8f8f8; }
            .ok    { color: green; }
            .warn  { color: orange; }
            .err   { color: red; }
            .line  { margin-bottom: 4px; }
        </style>
        </head><body>
        <h2>Отчёт проверки SCORM-курса</h2>
        <hr>
        """)

        for line in log_lines:
            cls = "line"
            if "✅" in line:
                cls += " ok"
            elif "⚠️" in line:
                cls += " warn"
            elif "❌" in line:
                cls += " err"
            f.write(f"<div class='{cls}'>{line}</div>\n")

        f.write("</body></html>")
