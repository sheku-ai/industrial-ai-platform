from __future__ import annotations

SUPPORTED_ASSISTANT_LOCALES = {
    "en", "zh-CN", "hi", "es", "ar", "fr", "bn", "pt", "ru", "ur",
    "ja", "de", "ko", "it", "nl", "pl", "tr", "id", "th", "vi",
}
RTL_ASSISTANT_LOCALES = {"ar", "ur"}

NO_EVIDENCE_MESSAGES = {
    "en": "There is not enough evidence in the knowledge base to answer this question.",
    "zh-CN": "知识库中没有足够的证据来回答此问题。",
    "hi": "इस प्रश्न का उत्तर देने के लिए ज्ञान आधार में पर्याप्त प्रमाण उपलब्ध नहीं हैं।",
    "es": "No hay evidencia suficiente en la base de conocimiento para responder esta pregunta.",
    "ar": "لا توجد أدلة كافية في قاعدة المعرفة للإجابة عن هذا السؤال.",
    "fr": "La base de connaissances ne contient pas suffisamment de preuves pour répondre à cette question.",
    "bn": "এই প্রশ্নের উত্তর দেওয়ার জন্য জ্ঞানভান্ডারে পর্যাপ্ত প্রমাণ নেই।",
    "pt": "Não há evidências suficientes na base de conhecimento para responder a esta pergunta.",
    "ru": "В базе знаний недостаточно подтверждений, чтобы ответить на этот вопрос.",
    "ur": "اس سوال کا جواب دینے کے لیے علمی ذخیرے میں کافی شواہد موجود نہیں ہیں۔",
    "ja": "この質問に回答するための十分な証拠がナレッジベースにありません。",
    "de": "Die Wissensdatenbank enthält nicht genügend Nachweise, um diese Frage zu beantworten.",
    "ko": "이 질문에 답할 수 있는 충분한 근거가 지식 베이스에 없습니다.",
    "it": "La base di conoscenza non contiene evidenze sufficienti per rispondere a questa domanda.",
    "nl": "De kennisbank bevat onvoldoende bewijs om deze vraag te beantwoorden.",
    "pl": "W bazie wiedzy nie ma wystarczających dowodów, aby odpowiedzieć na to pytanie.",
    "tr": "Bilgi tabanında bu soruyu yanıtlamak için yeterli kanıt yok.",
    "id": "Basis pengetahuan tidak memiliki bukti yang cukup untuk menjawab pertanyaan ini.",
    "th": "ฐานความรู้มีหลักฐานไม่เพียงพอที่จะตอบคำถามนี้",
    "vi": "Cơ sở tri thức không có đủ bằng chứng để trả lời câu hỏi này.",
}

GROUNDED_RESPONSE_TEMPLATES = {
    "en": "The available governed evidence indicates the following:\n\n{evidence}\n\nThis response is limited to the retrieved content and cited sources.",
    "zh-CN": "现有的受治理证据表明：\n\n{evidence}\n\n此回答仅限于检索到的内容和引用的来源。",
    "hi": "उपलब्ध शासित प्रमाण निम्न संकेत देते हैं:\n\n{evidence}\n\nयह उत्तर केवल प्राप्त सामग्री और उद्धृत स्रोतों तक सीमित है।",
    "es": "La evidencia gobernada disponible indica lo siguiente:\n\n{evidence}\n\nEsta respuesta se limita al contenido recuperado y a las fuentes citadas.",
    "ar": "تشير الأدلة المحكومة المتاحة إلى ما يلي:\n\n{evidence}\n\nتقتصر هذه الإجابة على المحتوى المسترجع والمصادر المذكورة.",
    "fr": "Les preuves gouvernées disponibles indiquent ce qui suit :\n\n{evidence}\n\nCette réponse se limite au contenu récupéré et aux sources citées.",
    "bn": "উপলভ্য নিয়ন্ত্রিত প্রমাণ থেকে নিম্নলিখিত তথ্য পাওয়া যায়:\n\n{evidence}\n\nএই উত্তরটি কেবল পুনরুদ্ধার করা বিষয়বস্তু ও উদ্ধৃত উৎসের মধ্যে সীমাবদ্ধ।",
    "pt": "As evidências governadas disponíveis indicam o seguinte:\n\n{evidence}\n\nEsta resposta se limita ao conteúdo recuperado e às fontes citadas.",
    "ru": "Доступные управляемые доказательства указывают на следующее:\n\n{evidence}\n\nОтвет ограничен найденным содержимым и указанными источниками.",
    "ur": "دستیاب زیرِ انتظام شواہد درج ذیل کی نشاندہی کرتے ہیں:\n\n{evidence}\n\nیہ جواب صرف بازیافت شدہ مواد اور حوالہ دیے گئے ذرائع تک محدود ہے۔",
    "ja": "利用可能な管理対象の証拠は次の内容を示しています。\n\n{evidence}\n\nこの回答は取得した内容と引用元に限定されています。",
    "de": "Die verfügbaren verwalteten Nachweise ergeben Folgendes:\n\n{evidence}\n\nDiese Antwort ist auf die abgerufenen Inhalte und zitierten Quellen beschränkt.",
    "ko": "사용 가능한 관리형 근거는 다음을 나타냅니다.\n\n{evidence}\n\n이 답변은 검색된 콘텐츠와 인용된 출처로 제한됩니다.",
    "it": "Le evidenze governate disponibili indicano quanto segue:\n\n{evidence}\n\nLa risposta è limitata ai contenuti recuperati e alle fonti citate.",
    "nl": "Het beschikbare beheerde bewijs geeft het volgende aan:\n\n{evidence}\n\nDit antwoord is beperkt tot de opgehaalde inhoud en geciteerde bronnen.",
    "pl": "Dostępne nadzorowane dowody wskazują, co następuje:\n\n{evidence}\n\nOdpowiedź ogranicza się do pobranej treści i cytowanych źródeł.",
    "tr": "Mevcut yönetişimli kanıtlar şunları göstermektedir:\n\n{evidence}\n\nBu yanıt yalnızca getirilen içerik ve belirtilen kaynaklarla sınırlıdır.",
    "id": "Bukti bertata kelola yang tersedia menunjukkan hal berikut:\n\n{evidence}\n\nJawaban ini terbatas pada konten yang diambil dan sumber yang dikutip.",
    "th": "หลักฐานที่อยู่ภายใต้การกำกับดูแลระบุว่า:\n\n{evidence}\n\nคำตอบนี้จำกัดอยู่ที่เนื้อหาที่ค้นคืนและแหล่งข้อมูลที่อ้างอิง",
    "vi": "Bằng chứng được quản trị hiện có cho thấy:\n\n{evidence}\n\nCâu trả lời này chỉ dựa trên nội dung đã truy xuất và các nguồn được trích dẫn.",
}


def resolve_assistant_locale(value: object) -> str:
    candidate = str(value or "").strip().replace("_", "-")
    if candidate in SUPPORTED_ASSISTANT_LOCALES:
        return candidate
    base = candidate.split("-", 1)[0].lower()
    return base if base in SUPPORTED_ASSISTANT_LOCALES else "en"


def no_evidence_message(locale: object) -> str:
    return NO_EVIDENCE_MESSAGES[resolve_assistant_locale(locale)]


def grounded_response(locale: object, evidence: list[str]) -> str:
    template = GROUNDED_RESPONSE_TEMPLATES[resolve_assistant_locale(locale)]
    return template.format(evidence="\n".join(evidence))


__all__ = ["grounded_response", "no_evidence_message", "resolve_assistant_locale"]
