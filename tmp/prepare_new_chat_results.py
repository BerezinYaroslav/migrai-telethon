"""Prepare the manually reviewed shortlist and precise existing-sheet updates."""

import json
from datetime import date
from pathlib import Path

root = Path("var")
scan = json.loads((root / "new_chats_20260927.json").read_text())
reviews = {
    514067: ("Виза D / въезд / документы", "Готовится к переезду по визе D; уточняет маршрут въезда и подтверждение прибытия в Испанию."),
    513987: ("Учебная виза / запись", "Выбирает способ записи на подачу учебной визы D: самостоятельно или через бота."),
    513947: ("Виза D / запись / сопровождение", "Ищет слот на подачу визы D в Москве и сравнивает самостоятельную запись с помощью бота."),
    513923: ("Национальная виза / ожидание решения", "Подался на национальную визу 04.09 и ищет опыт других заявителей по срокам рассмотрения."),
    513756: ("ВНЖ / работа в IT / риски подачи", "Разработчик в российской IT-компании готовится к подаче на ВНЖ и уточняет риск отказа."),
    513696: ("Виза D / подача из третьей страны", "Уточняет сроки рассмотрения визы D при подаче в Вильнюсе и изъятие паспорта."),
    69398: ("ВНЖ / въезд на отпечатки", "Есть одобрение и запись на отпечатки, но отказ в шенгенской визе; ищет способ въехать для оформления."),
    69376: ("Стартап-виза / подача из РФ", "Проверяет возможность податься на стартап-визу из России."),
    69281: ("Смена ВНЖ / Digital Nomad / ПМЖ", "Сравнивает переход со стартап-маршрута на номада и зачёт срока для ПМЖ."),
    69243: ("Подача в UGE / смена представителя", "Заявка уже рассматривается; уточняет смену представителя и доверенность в процессе подачи."),
    69214: ("Смена ВНЖ / работа", "Ищет опыт перехода со стартап-визы на ВНЖ через работодателя."),
    69213: ("Виза / запись / сопровождение", "Просит контакты помощников для поиска слота на подачу в испанское консульство."),
    128223: ("Digital Nomad / документы / найм", "Готовит подачу на Digital Nomad в найме; уточняет свидетельство E/R1 и срок ВНЖ."),
    128009: ("Digital Nomad / продление / соцстрах", "Готовится к продлению номадского ВНЖ; есть проблема со сроками регистрации в соцстрахе и налоговой."),
    127459: ("Виза D / дозапрос / семья", "После отказа и повторной подачи разбирает дозапросы по жилью и документам семьи."),
    127961: ("Digital Nomad / продление / ожидание", "Подал на продление 25 июля, не получил ответ; уточняет задержку и молчаливое одобрение."),
    212792: ("ВНЖ / финансы / банковский счёт", "Подбирает банковский счёт для подтверждения средств при оформлении ВНЖ и дальнейшего использования в Португалии."),
    212618: ("Переезд / работа / контракт", "Прямо планирует переезд в Португалию и переход на местный трудовой контракт."),
    212473: ("Семейный переезд / опека / документы", "Выбирает порядок переезда ребёнка под попечительством: виза и подача на месте либо предварительное одобрение."),
    212460: ("D2 / бизнес / ВНЖ", "Ищет опыт самостоятельного прохождения маршрута D2 через открытие бизнеса до получения ВНЖ."),
    200656: ("O-1 / собеседование / сопровождение", "Ищет специалиста для подготовки к консульскому собеседованию по O-1."),
    200589: ("Смена визы / консультация", "Нужна помощь адвоката со сменой визы; просит бесплатную консультацию."),
}
source_names = {
    259: "Виза D Испания",
    271: "Стартап виза Испания",
    317: "Испания Migrun",
    389: "Left4Portugal 🇵🇹",
    196: "O1 виза, EB1 EB2 NIW гринкарта",
}
selected = []
seen_users = set()
for chat in scan["chats"]:
    assert chat["status"] == "complete" and chat["messages_seen"] == 200
    count = 0
    for signal in chat["signals"]:
        accepted = signal["message_id"] in reviews
        signal["review"] = "shortlisted" if accepted else "not_shortlisted"
        if not accepted:
            continue
        assert signal["user_id"] not in seen_users
        seen_users.add(signal["user_id"])
        topic, comment = reviews[signal["message_id"]]
        selected.append({**signal, "source": source_names[chat["sheet_row"]],
                         "country": chat["country"], "topic": topic,
                         "comment": f"Сигнал от {signal['message_date'][:10]}. {comment}"})
        count += 1
    chat["shortlisted_candidates"] = count
assert len(selected) == 22
scan["reviewed_candidates"] = selected
(root / "new_chats_20260927.json").write_text(json.dumps(scan, ensure_ascii=False, indent=2))

def value(v):
    return {"numberValue": v} if isinstance(v, (int, float)) else {"stringValue": v}

serial = (date(2026, 9, 27) - date(1899, 12, 30)).days
rows = []
for s in selected:
    values = [f"@{s['username']}" if s["username"] else str(s["user_id"]),
              s["display_name"], "Новый", s["source"], s["link"], s["excerpt"],
              s["topic"], s["score"], s["country"], serial, "Не рассмотрен", s["comment"]]
    cells = [{"userEnteredValue": value(v)} for v in values]
    if s["username"]:
        cells[0]["userEnteredFormat"] = {"textFormat": {"link": {
            "uri": f"https://t.me/{s['username']}"}}}
    cells[4]["userEnteredFormat"] = {"textFormat": {"link": {"uri": s["link"]}}}
    rows.append({"values": cells})
requests = [{"updateCells": {
    "range": {"sheetId": 936451753, "startRowIndex": 20, "endRowIndex": 42,
              "startColumnIndex": 0, "endColumnIndex": 12},
    "rows": rows, "fields": "userEnteredValue,userEnteredFormat.textFormat.link"}}]
for c in scan["chats"]:
    requests.append({"updateCells": {
        "range": {"sheetId": 0, "startRowIndex": c["sheet_row"] - 1,
                  "endRowIndex": c["sheet_row"], "startColumnIndex": 4,
                  "endColumnIndex": 5},
        "rows": [{"values": [{"userEnteredValue": {"stringValue": "Распарсен"},
                   "note": f"27.09.2026: прочитано 200 последних сообщений; отобрано {c['shortlisted_candidates']} потенциальных респондентов. История {c['oldest_message_date'][:10]} — {c['newest_message_date'][:10]}."}]}],
        "fields": "userEnteredValue,note"}})
payload = {"spreadsheet_id": "1Ji1XHh3YzEFNQps7M3n76ePLDCWFpfQfZAieZ130OdI",
           "requests": requests}
(root / "new_chats_sheet_update_20260927.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2))
print(json.dumps(payload, ensure_ascii=False))
