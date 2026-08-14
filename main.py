from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import httpx
from bs4 import BeautifulSoup
import google.generativeai as genai
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"): 
    SUPABASE_URL = SUPABASE_URL[:-8]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

class ItemRequest(BaseModel):
    project_name: str
    category: str
    url: str
    comment: str = ""
    icon: str = "🏠"

@app.post("/api/items")
async def add_item(req: ItemRequest):
    title, image_url = "タイトル取得中...", ""
    
    # URLがダミーでない場合のみOGPを取得
    if req.url and req.url != "#":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(req.url, follow_redirects=True)
                soup = BeautifulSoup(res.text, 'html.parser')
                title = soup.title.string if soup.title else "タイトルなし"
                og_image = soup.find("meta", property="og:image")
                image_url = og_image["content"] if og_image else ""
        except Exception as e:
            logging.error(f"OGP取得エラー: {e}")
            title = req.url
    else:
        title = req.project_name

    data = {
        "project_name": req.project_name,
        "category": req.category,
        "url": req.url,
        "title": title,
        "image_url": image_url,
        "comment": req.comment,
        "icon": req.icon,
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        response = supabase.table("items").insert(data).execute()
        return response.data
    except Exception as e:
        logging.error(f"DB保存エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/items")
def get_items():
    try:
        return supabase.table("items").select("*").order("updated_at", desc=True).execute().data
    except Exception as e:
        logging.error(f"DB取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))
