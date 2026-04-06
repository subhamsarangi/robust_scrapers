import os, requests, time

API_KEY = os.getenv("API_KEY") or "ntn_xxx"  # placeholder, should be set in .env


def format_uuid(id_str):
    id_str = id_str.replace("-", "")
    return (
        f"{id_str[0:8]}-{id_str[8:12]}-{id_str[12:16]}-{id_str[16:20]}-{id_str[20:32]}"
    )


PAGE_ID = format_uuid("33a25c6500be80c09206e8d04223d0ac")
FOLDER = "gems_output"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def create(title, text):
    url = "https://api.notion.com/v1/pages"

    data = {
        "parent": {"page_id": PAGE_ID},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": [],
    }

    # split text into chunks (required)
    chunks = [text[i : i + 1800] for i in range(0, len(text), 1800)]

    for chunk in chunks[:50]:  # safety limit
        data["children"].append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                },
            }
        )

    r = requests.post(url, headers=headers, json=data)

    print(title, r.status_code)
    if r.status_code != 200:
        print(r.text)


for f in os.listdir(FOLDER):
    if f.endswith(".txt"):
        with open(os.path.join(FOLDER, f), encoding="utf-8", errors="ignore") as file:
            create(f[:-4], file.read())
            time.sleep(0.4)
