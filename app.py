import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI, RateLimitError
from documents import extract_docx_text
from storage import database_is_ready, save_generation


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024


def demo_topics(data):
    subject = data["subject"]
    themes = [item.strip() for item in data["studied"].replace("\n", ",").split(",") if item.strip()]
    focus = themes[0] if themes else subject
    audience = data.get("audience") or "пользователей"
    if data.get("language") == "kk":
        ideas = [
            (f"«{focus}» тақырыбы негізінде {audience} үшін зияткерлік жүйе әзірлеу", f"«{subject}» пәні бойынша білімді қолданатын жүйенің прототипін жасау.", ["Пәндік саланы және қолданыстағы шешімдерді зерттеу", "Талаптарды анықтап, жүйені жобалау", "Прототип жасап, жұмысын бағалау"], "Жұмыс прототипі және оны дамыту жөніндегі ұсыныстар."),
            (f"«{subject}» саласындағы «{focus}» әдістерін зерттеу және қолдану", f"Таңдалған әдістерді салыстырып, оларды тиімді қолдану жолын анықтау.", ["Негізгі ұғымдар мен әдістерді қарастыру", "Салыстыру өлшемдерін дайындау", "Тәжірибе өткізіп, нәтижелерді талдау"], "Салыстырмалы талдау және тексерілген тәжірибе нәтижелері."),
            (f"«{subject}» саласындағы міндетті шешуге арналған цифрлық сервис құру", f"«{', '.join(themes[:2]) or subject}» тақырыптарына қатысты міндетке ыңғайлы сервис жобалау.", ["Болашақ пайдаланушылардың талаптарын жинау", "Сервистің құрылымы мен интерфейсін әзірлеу", "Негізгі функцияларды жасап, тексеру"], "Сервистің демонстрациялық нұсқасы және оны жетілдіру жоспары."),
            (f"Практикалық міндетті шешуде «{focus}» қолдану тиімділігін бағалау", f"«{focus}» әдістерінің «{subject}» саласындағы пайдасын нақты мысалда тексеру.", ["Практикалық міндет пен бағалау өлшемдерін таңдау", "Әдісті дайындап, қолдану", "Нәтижелерді салыстырып, қорытынды жасау"], "Жақсарту ұсыныстары бар тәжірибе есебі."),
            (f"«{subject}» пәні бойынша оқыту құралын жобалау", f"«{focus}» тақырыбын меңгеруге көмектесетін оқу құралын жасау.", ["Оқушылардың қажеттіліктерін анықтау", "Оқу сценарийлері мен материалдарын әзірлеу", "Құралды мысалдар арқылы тексеру"], "Оқыту құралының прототипі және оқу материалдары."),
            (f"«{focus}» тақырыбы бойынша міндетті автоматтандыруға арналған ақпараттық жүйе", f"«{subject}» пәні білімін пайдаланып, таңдалған процесті жеңілдететін шешім жобалау.", ["Қазіргі процесті және мәселелерін сипаттау", "Автоматтандыру талаптарын анықтау", "Шешім жасап, нәтижесін бағалау"], "Жүйе прототипі және автоматтандырудың пайдасын бағалау."),
            (f"«{subject}» саласындағы деректерді талдау әдістемесін әзірлеу", f"«{focus}» тақырыбына қатысты деректерді талдаудың түсінікті тәсілін дайындау.", ["Деректер түрі мен зерттеу сұрағын таңдау", "Дайындау және талдау әдістерін іріктеу", "Әдістемені мысалда тексеру"], "Әдістеменің сипаттамасы, қолдану мысалы және қорытындылар."),
            (f"«{subject}» саласындағы «{focus}» тақырыбы бойынша шешімдерді салыстыру", f"Қолданыстағы шешімдерді «{subject}» бағытының міндеттеріне жарамдылығы бойынша салыстыру.", ["Бірнеше қолданыстағы шешімді таңдау", "Ортақ салыстыру өлшемдерін анықтау", "Салыстыру жасап, негізделген ұсыныстар беру"], "Салыстыру кестесі және дәлелді ұсыныстар."),
        ]
        why = f"«{subject}» пәнімен және өтілген материалмен байланысты."
    else:
        ideas = [
        (f"Разработка интеллектуальной системы для {audience} на основе темы «{focus}»",
         f"Создать прототип системы, которая применяет знания по предмету «{subject}» к выбранной области.",
         ["Изучить предметную область и существующие решения", "Определить требования и спроектировать систему", "Разработать прототип и оценить его работу"],
         "Рабочий прототип и рекомендации по его дальнейшему развитию."),
        (f"Исследование и практическое применение методов «{focus}» в области «{subject}»",
         f"Сравнить выбранные методы и определить, как их эффективнее применять в рамках предмета «{subject}».",
         ["Рассмотреть основные понятия и методы", "Подготовить набор критериев для сравнения", "Провести эксперимент и проанализировать результаты"],
         "Сравнительный анализ и проверяемые результаты эксперимента."),
        (f"Создание цифрового сервиса для решения задачи в области «{subject}»",
         f"Спроектировать удобный сервис для задачи, связанной с темами «{', '.join(themes[:2]) or subject}».",
         ["Собрать требования будущих пользователей", "Разработать структуру и интерфейс сервиса", "Создать и проверить основные функции"],
         "Демонстрационная версия сервиса и план его улучшения."),
        (f"Оценка эффективности применения «{focus}» для решения практической задачи",
         f"Проверить на конкретном примере, насколько полезны методы из темы «{focus}» для предметной области «{subject}».",
         ["Выбрать практическую задачу и критерии оценки", "Подготовить и применить выбранный метод", "Сопоставить результаты и сформулировать выводы"],
         "Отчёт об эксперименте с выводами и предложениями по улучшению."),
        (f"Проектирование обучающего инструмента по дисциплине «{subject}»",
         f"Создать учебный инструмент, который помогает осваивать пройденный материал по теме «{focus}».",
         ["Определить трудности и потребности учащихся", "Разработать сценарии и учебные материалы", "Проверить понятность инструмента на примерах"],
         "Прототип обучающего инструмента и набор учебных материалов."),
        (f"Информационная система для автоматизации задачи по теме «{focus}»",
         f"Спроектировать решение, которое упростит выбранный процесс с использованием знаний по предмету «{subject}».",
         ["Описать текущий процесс и его проблемы", "Определить требования к автоматизации", "Разработать и оценить прототип решения"],
         "Прототип системы и оценка ожидаемой пользы от автоматизации."),
        (f"Разработка методики анализа данных в области «{subject}»",
         f"Подготовить понятный способ анализа данных, связанный с пройденной темой «{focus}».",
         ["Выбрать тип данных и исследовательский вопрос", "Подобрать методы подготовки и анализа", "Проверить методику на примере и описать результаты"],
         "Описание методики, пример её применения и выводы."),
        (f"Сравнительный анализ решений по теме «{focus}» для предметной области «{subject}»",
         f"Сравнить существующие решения и определить, какие лучше подходят для задач направления «{subject}».",
         ["Выбрать несколько существующих решений", "Определить единые критерии сравнения", "Провести сравнение и дать обоснованные рекомендации"],
         "Таблица сравнения и аргументированные рекомендации."),
        ]
        why = f"Связана с предметом «{subject}» и пройденным материалом."
    return [{"title": title, "why": why, "goal": goal,
             "tasks": tasks, "result": result} for title, goal, tasks, result in ideas[:int(data.get("count", 5))]]


def normalize_generation_data(raw_data):
    data = dict(raw_data)
    subject = str(data.get("major", "")).strip()
    studied = str(data.get("studied", "")).strip()
    level = str(data.get("level", "")).strip()
    if not subject or not studied:
        raise ValueError("Выберите специальность и укажите пройденные предметы или темы.")
    if level not in {"course", "diploma"}:
        raise ValueError("Сначала выберите курсовую или дипломную работу.")

    data["subject"] = subject[:160]
    data["major"] = data["subject"]
    data["studied"] = studied[:3000]
    data["audience"] = str(data.get("audience", "")).strip()[:300]
    data["level"] = level
    language = str(data.get("language", "ru")).lower()
    data["language"] = language if language in {"ru", "kk"} else "ru"
    data["year"] = str(data.get("year", "")).strip()[:1]
    try:
        count = int(data.get("count", 5))
    except (ValueError, TypeError):
        count = 5
    data["count"] = max(3, min(8, count))
    return data


def generate_topics(data):
    requested_provider = os.environ.get("AI_PROVIDER", "auto").strip().lower()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if requested_provider == "gemini":
        provider = "gemini" if gemini_key else None
    elif requested_provider == "openai":
        provider = "openai" if openai_key else None
    else:
        provider = "gemini" if gemini_key else ("openai" if openai_key else None)
    if not provider:
        return demo_topics(data), "demo"

    level_label = "курсовой" if data["level"] == "course" else "дипломной"
    scope_guidance = (
        "Ограничь объём одной решаемой задачей и результатом, выполнимым за семестр."
        if data["level"] == "course"
        else "Предложи более глубокое исследование или полноценную практическую разработку с обоснованием и оценкой результата."
    )
    output_language = "казахском" if data["language"] == "kk" else "русском"
    prompt = f"""Подготовь {data['count']} разнообразных и выполнимых тем для {level_label} работы.
Университет: Западно-Казахстанский аграрно-технический университет имени Жангир хана.
Специальность / образовательная программа: {data['subject']}
Курс обучения: {data['year'] or 'не указан'}
Пройденные темы: {data['studied']}
Интересующая область/аудитория: {data['audience'] or 'не указана'}
Масштаб работы: {scope_guidance}

Ответь только корректным JSON-объектом такой формы:
{{"topics":[{{"title":"...","why":"...","goal":"...","tasks":["...","...","..."],"result":"..."}}]}}
Каждая тема должна явно опираться на переданные учебные темы, быть конкретной и подходить уровню работы.
Для каждой укажи краткое объяснение связи с материалом, цель, 3-5 задач и ожидаемый практический результат.
Пиши на {output_language} языке. Не обещай, что тема уникальна; формулируй академично и понятно."""
    try:
        if provider == "gemini":
            response_text = generate_with_gemini(prompt, gemini_key)
        else:
            client = OpenAI(api_key=openai_key)
            response = client.responses.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                input=[{"role": "user", "content": prompt}],
            )
            response_text = response.output_text
        parsed = json.loads(response_text)
        topics = parsed.get("topics")
        if not isinstance(topics, list) or not topics:
            raise ValueError("Модель вернула пустой список тем")
        return topics[:data["count"]], "ai"
    except Exception as exc:
        # Keep the app usable even if an external AI service is unavailable.
        app.logger.info("AI unavailable; using built-in examples (%s)", type(exc).__name__)
        return demo_topics(data), "demo"


class GeminiAPIError(Exception):
    def __init__(self, status_code, api_status, message):
        super().__init__(message)
        self.status_code = status_code
        self.api_status = api_status


def generate_with_gemini(prompt, api_key):
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8")).get("error", {})
        except (ValueError, AttributeError):
            error = {}
        raise GeminiAPIError(exc.code, error.get("status", ""), error.get("message", "")) from None
    candidates = payload.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    response_text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not response_text.strip():
        raise ValueError("Gemini вернул пустой ответ")
    return response_text


def generation_error_message(exc):
    """Return actionable, credential-safe messages for API failures."""
    if isinstance(exc, GeminiAPIError):
        if exc.status_code == 429 or exc.api_status == "RESOURCE_EXHAUSTED":
            return "Достигнут бесплатный лимит Gemini API. Подождите сброса лимита или проверьте квоту в Google AI Studio."
        if exc.status_code in {400, 403}:
            return "Gemini API не принял ключ или запрос. Проверьте GEMINI_API_KEY в файле .env."
        return "Gemini API временно недоступен. Попробуйте ещё раз позже."
    code = getattr(exc, "code", None)
    detail = str(exc).lower()
    if code in {"insufficient_quota", "credit_balance_exhausted"} or "no credits remaining" in detail:
        return "На API-балансе закончились кредиты. Проверьте баланс или добавьте кредиты: https://platform.openai.com/settings/organization/billing/"
    if isinstance(exc, AuthenticationError):
        return "OpenAI не принял API-ключ. Проверьте строку OPENAI_API_KEY в файле .env и перезапустите приложение."
    if isinstance(exc, RateLimitError):
        return "Достигнут лимит запросов к API. Подождите немного и попробуйте снова."
    return "Сервис генерации временно недоступен. Проверьте подключение и попробуйте ещё раз."


@app.get("/")
def index():
    return send_from_directory(ROOT / "static", "index.html")


@app.post("/api/generate")
def generate():
    try:
        data = normalize_generation_data(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        topics, mode = generate_topics(data)
        save_generation(data, topics, mode)
        return jsonify(topics=topics, mode=mode)
    except Exception as exc:
        app.logger.warning("Topic generation failed (%s)", type(exc).__name__)
        return jsonify(error=generation_error_message(exc)), 502


@app.post("/api/extract-document")
def extract_document():
    uploaded = request.files.get("document")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Выберите файл Word для загрузки."), 400
    if Path(uploaded.filename).suffix.lower() != ".docx":
        return jsonify(error="Поддерживаются документы Word в формате .docx."), 400
    try:
        text = extract_docx_text(uploaded.read())[:3000]
        if not text:
            return jsonify(error="В документе не найден текст. Добавьте темы или материалы и попробуйте снова."), 400
        return jsonify(text=text, filename=Path(uploaded.filename).name)
    except Exception:
        return jsonify(error="Не удалось прочитать документ. Убедитесь, что это корректный файл .docx."), 400


@app.get("/api/health")
def health():
    try:
        return jsonify(status="ok", database="connected" if database_is_ready() else "not configured")
    except Exception:
        app.logger.exception("Database health check failed")
        return jsonify(status="degraded", database="unavailable"), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
