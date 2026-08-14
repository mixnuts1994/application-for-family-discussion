@app.post("/api/extract")
def extract_info(url: str):
    """指定されたURLから製品名、価格、画像をAIとスクレイピングで抽出する"""
    try:
        # User-Agentを一般のブラウザっぽく偽装（ブロック回避のため）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        
        # サイトから403(アクセス拒否)などが返ってきた場合、ここでエラーを発生させる
        res.raise_for_status() 
        
        soup = BeautifulSoup(res.text, 'html.parser')
        page_text = soup.get_text(separator=' ', strip=True)[:1000] 
        
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
        
        try:
            data = parse_gemini_json(response.text)
        except Exception as parse_e:
            # AIが変な回答をしてパースに失敗した場合
            return {
                "result": {"title": "", "price": 0, "image_url": None},
                "error": f"AIの回答形式エラー: {response.text}"
            }
        
        image_url = get_ogp_image(url)
        
        return {
            "result": {
                "title": data.get("title", soup.title.string if soup.title else ""),
                "price": data.get("price", 0),
                "image_url": image_url
            }
        }
    except requests.exceptions.RequestException as req_e:
        print("通信エラー:", req_e)
        return {
            "result": {"title": "", "price": 0, "image_url": None},
            "error": f"サイト側で取得がブロックされました (エラー詳細: {req_e})"
        }
    except Exception as e:
        print("抽出エラー:", e)
        return {
            "result": {"title": "", "price": 0, "image_url": None},
            "error": f"予期せぬエラー: {str(e)}"
        }
