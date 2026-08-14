import os
import json
import re
import sqlite3
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List
import google.generativeai as genai

# ==========================================
# 初期設定
# ==========================================
app = FastAPI()

# CORS設定（フロントエンドからの通信を許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境ではフロントエンドのドメインに制限してください
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini APIの設定（環境変数から取得、または直接文字列で指定）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "あなたの_GEMINI_API_KEY_をここに入力")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# データベース設定 (SQLite)
DB_FILE = "database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            category TEXT,
            icon TEXT,
            title TEXT,
            url TEXT,
            price INTEGER,
            image_data TEXT,
            user_ratings TEXT,
            is_decided BOOLEAN,
            comment TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# データモデル (Pydantic)
# ==========================================
class ItemModel(BaseModel):
    project_name: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    price: Optional[int] = 0
    image_data: Optional[str] = None
    user_ratings: Optional[Dict[str, int]] = None
    is_decided: Optional[bool] = False
    comment: Optional[str] = None

class RecommendRequest(BaseModel):
    category: str
    existing_items: List[str]

# ==========================================
# 補助関数
# ==========================================
def parse_gemini_json(response_text: str) -> dict:
    """Geminiの出力からマークダウン記法(```json)を取り除き、辞書型に変換する"""
    cleaned_text = re.sub(r'^```json\s*', '', response_text, flags=re.MULTILINE)
    cleaned_text = re.sub(r'^```\s*$', '', cleaned_text, flags=re.MULTILINE)
    try:
        return json.loads(cleaned_text.strip())
    except json.JSONDecodeError:
        print("JSONのパースに失敗しました:", cleaned_text)
        return {}

def get_ogp_image(url: str) -> Optional[str]:
    """URLからOGP（サムネイル）画像を抽出する"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            return og_img['content']
    except Exception as e:
        print(f"OGP画像抽出エラー: {e}")
    return None

# ==========================================
# APIエンドポイント
# ==========================================
@app.get("/api/items")
def get_items():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM items")
    rows = c.fetchall()
    conn.close()

    items = []
    for r in rows:
        item = dict(r)
        # JSON文字列を辞書に、0/1を真偽値に変換
        item["user_ratings"] = json.loads(item["user_ratings"]) if item["user_ratings"] else {}
        item["is_decided"] = bool(item["is_decided"])
        items.append(item)
    return items

@app.post("/api/items")
def create_item(item: ItemModel):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO items (project_name, category, icon, title, url, price, image_data, user_ratings, is_decided, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        item.project_name, item.category, item.icon, item.title, item.url,
        item.price, item.image_data, json.dumps(item.user_ratings or {}),
        int(item.is_decided or False), item.comment
    ))
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": item_id, "status": "success"}

@app.put("/api/items/{item_id}")
def update_item(item_id: int, item: ItemModel):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # リクエストに含まれている（変更された）フィールドだけを抽出
    update_fields = item.dict(exclude_unset=True)
    if not update_fields:
        return {"status": "no update"}
        
    if "user_ratings" in update_fields:
        update_fields["user_ratings"] = json.dumps(update_fields["user_ratings"])
    if "is_decided" in update_fields:
        update_fields["is_decided"] = int(update_fields["is_decided"])

    # UPDATE文を動的に生成
    set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
    values = list(update_fields.values())
    values.append(item_id)

    c.execute(f"UPDATE items SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return {"id": item_id, "status": "success"}

@app.delete("/api/items/{item_id}")
def delete_item(item_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/extract")
def extract_info(url: str):
    """指定されたURLから製品名、価格、画像をAIとスクレイピングで抽出する"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # サイトのテキストを先頭から抽出（トークン節約のため1000文字程度）
        page_text = soup.get_text(separator=' ', strip=True)[:1000] 
        
        # Geminiに製品名と価格の抽出を依頼
        prompt = f"""
        以下のウェブページのテキストから、製品名と価格（数値のみ）を抽出してください。
        結果は必ず以下の形式のJSONで返してください。それ以外のテキストは含めないでください。
        {{
            "title": "抽出した製品名",
            "price": 1000
        }}
        
        テキスト:
        {page_text}
        """
        response = model.generate_content(prompt)
        data = parse_gemini_json(response.text)
        
        # サムネイル画像の取得
        image_url = get_ogp_image(url)
        
        return {
            "result": {
                # AIが取得できなかった場合は、フォールバックとしてサイトのtitleタグを使用
                "title": data.get("title", soup.title.string if soup.title else ""),
                "price": data.get("price", 0),
                "image_url": image_url
            }
        }
    except Exception as e:
        print("抽出エラー:", e)
        return {"result": {"title": "", "price": 0, "image_url": None}}

@app.post("/api/recommend")
def recommend_items(req: RecommendRequest):
    """現在のカテゴリと既存アイテムをもとに、AIが新たな製品を提案する"""
    prompt = f"""
    あなたは優秀な購買アドバイザーです。
    ユーザーは「{req.category}」というカテゴリで、以下の製品を検討しています。
    検討中の製品: {", ".join(req.existing_items)}
    
    これらを参考に、別のおすすめ製品（類似品、コスパが良いもの、または少しグレードの高いものなど）を3つ提案してください。
    必ず以下のJSON形式で出力してください。
    {{
        "suggestions": [
            {{
                "title": "製品名",
                "url": "参考検索URL（例: [https://www.amazon.co.jp/s?k=製品名](https://www.amazon.co.jp/s?k=製品名)）",
                "price": 予想価格（数値のみ）,
                "comment": "おすすめする理由（短く）"
            }}
        ]
    }}
    """
    try:
        response = model.generate_content(prompt)
        data = parse_gemini_json(response.text)
        
        if "suggestions" not in data:
            return {"suggestions": []}
        return data
        
    except Exception as e:
        print("レコメンドエラー:", e)
        return {"suggestions": []}

# ==========================================
# サーバー起動 (ローカル実行用)
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # ターミナルから `python main.py` で起動する場合
    uvicorn.run(app, host="0.0.0.0", port=8000)
