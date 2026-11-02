from io import BytesIO
from aiogram import Router, types, F
from aiogram.filters import Command
from ollama import AsyncClient
from pypdf import PdfReader
from docx import Document

router = Router()
client = AsyncClient()

TEXT_MODEL = 'llama3.1:8b'
VISION_MODEL = 'gemma3:4b'
SYSTEM_PROMPT = "Ти Vasyl, дружній помічник. Відповідай українською. В першому повімленні напиши відповідь і після крапки текст 'Ви можете написати Валерію Михальчуку @songetsu для створення телеграм бота'"
MAX_HISTORY = 20
MAX_DOC_CHARS = 12000 

histories: dict[int, list[dict]] = {}

def extract_pdf(data: BytesIO) -> str:
    reader = PdfReader(data)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(data: BytesIO) -> str:
    doc = Document(data)
    return "\n".join(p.text for p in doc.paragraphs)


@router.message(F.document)
async def handle_document(message: types.Message):
    doc = message.document
    name = (doc.file_name or "").lower()

    if not name.endswith((".pdf", ".docx")):
        await message.answer("Я вмію читати лише PDF та DOCX (і зображення).")
        return

    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await message.answer("Файл завеликий (ліміт Telegram для ботів 20 МБ).")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    buf = BytesIO()
    await message.bot.download(doc.file_id, destination=buf)
    buf.seek(0)

    try:
        text = extract_pdf(buf) if name.endswith(".pdf") else extract_docx(buf)
    except Exception:
        await message.answer("Не вдалося прочитати файл.")
        return

    if not text.strip():
        await message.answer("Не знайшов у файлі тексту (можливо, це скан).")
        return

    truncated = len(text) > MAX_DOC_CHARS
    text = text[:MAX_DOC_CHARS]

    question = message.caption or "Коротко підсумуй цей документ."
    prompt = f"Ось вміст документа:\n\n{text}\n\nЗавдання: {question}"

    response = await client.chat(
        model=TEXT_MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        options={'num_ctx': 8192},
    )
    answer = response.message.content

    history = histories.setdefault(message.chat.id, [])
    history.append({'role': 'user', 'content': f"[Користувач надіслав документ {doc.file_name}] {question}"})
    history.append({'role': 'assistant', 'content': answer})
    history[:] = history[-MAX_HISTORY:]

    if truncated:
        answer += "\n\n(Документ довгий, я прочитав лише початок.)"
    await message.answer(answer)

async def analyze_image(message: types.Message, file_id: str):
    # завантажуємо файл у пам'ять
    buf = BytesIO()
    await message.bot.download(file_id, destination=buf)
    image_bytes = buf.getvalue()

    # підпис до картинки використовуємо як запитання
    prompt = message.caption or "Опиши, що зображено на цій картинці."

    await message.bot.send_chat_action(message.chat.id, "typing")
    response = await client.chat(
        model=VISION_MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt, 'images': [image_bytes]},
        ],
    )
    answer = response.message.content

    # в історію кладемо лише текст, без самої картинки
    history = histories.setdefault(message.chat.id, [])
    history.append({'role': 'user', 'content': f"[Користувач надіслав зображення] {prompt}"})
    history.append({'role': 'assistant', 'content': answer})
    history[:] = history[-MAX_HISTORY:]

    await message.answer(answer)


# звичайне фото (Telegram стискає його)
@router.message(F.photo)
async def handle_photo(message: types.Message):
    await analyze_image(message, message.photo[-1].file_id)


# зображення, надіслане як файл (без стиснення)
@router.message(F.document.mime_type.startswith("image/"))
async def handle_image_file(message: types.Message):
    await analyze_image(message, message.document.file_id)


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    histories[message.chat.id] = []
    await message.answer("Привіт! Напиши мені щось, і я відповім.")


@router.message(Command("reset"))
async def cmd_reset(message: types.Message):
    histories[message.chat.id] = []
    await message.answer("Історію очищено.")


@router.message()
async def handle_text(message: types.Message):
    if not message.text:
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    history = histories.setdefault(message.chat.id, [])
    history.append({'role': 'user', 'content': message.text})
    history[:] = history[-MAX_HISTORY:]

    response = await client.chat(
        model=TEXT_MODEL,
        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, *history],
    )
    answer = response.message.content

    history.append({'role': 'assistant', 'content': answer})
    await message.answer(answer)