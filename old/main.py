import os
from google import genai
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Geminiの初期化
client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
# モデルを選択
CURRENT_MODEL = "gemini-flash-latest"

# Slackアプリの初期化
app = App(token=os.environ["SLACK_BOT_TOKEN"])

# --- 機能：時系列重視の要約 ---
@app.command("/summarize")
def handle_summarize(ack, respond, command):
    # 3秒以内にSlackへ応答を返す（タイムアウト対策）
    ack("検索と要約を開始します。少々お待ちください...")
    
    query = command['text']
    user_token = os.environ["SLACK_USER_TOKEN"]

    try:
        # 1. ユーザー権限で検索
        search_res = app.client.search_messages(
            token=user_token, 
            query=query, 
            sort="timestamp", 
            sort_dir="asc",
            count=20
            )
        matches = search_res.get('messages', {}).get('matches', [])

        if not matches:
            respond("該当する話題が見つかりませんでした。")
            return

        # メッセージ整形部分
        history_data = []
        for m in matches:
            dt = datetime.fromtimestamp(float(m['ts'])).strftime('%Y-%m-%d %H:%M')
            # Slackのパーマリンクを取得
            link = m.get('permalink')
            # <URL|表示名> の形式にすると確実にリンク化されます
            formatted_link = f"<{link}|[元の会話を表示]>" if link else ""
            history_data.append(f"[{dt}] {m['username']}: {m['text']}\n{formatted_link}")

        context = "\n\n".join(history_data)

        # 3. Gemini Pro による時系列要約
        # --- 修正版：Slack専用フォーマット指定プロンプト ---
        # --- 修正版：Slack表示最適化プロンプト ---
        prompt = f"""
        あなたは優秀なDX推進担当です。以下の会話履歴を、時系列に沿って要約してください。
        
        【Slack表示用・絶対禁止ルール】
        1. **（アスタリスク2つ）は禁止。太字は必ず *テキスト* （アスタリスク1つ）で囲んでください。
        2. #（シャープ）による見出しは禁止。見出しは *【見出し名】* のように太字で表現してください。
        3. 表（テーブル記法 |--- |）は禁止。必ず箇条書き（ • ）で書いてください。
        4. HTMLタグ（<br>など）は絶対に入れないでください。
        5. 【リンクに関する絶対ルール】
        - 各要約の末尾にある <https://...|[元の会話を表示]> という文字列は、1文字も変更せず、そのまま出力してください。
        - リンクの前後に余計なスペースや改行を入れないでください。
        
        【要約の構成】
        - 冒頭に全体像を一言で。
        - その後、時系列で「いつ・誰が・何を話し、何が決まったか」を箇条書きにする。
        - 各項目の末尾には必ず <URL|[元の会話を表示]> の形式でリンクを付けてください。
        
        【会話履歴】
        {context}
        """

        # 4. Geminiで生成（新しいSDKの文法）
        response = client_gemini.models.generate_content(
            model=CURRENT_MODEL,
            contents=prompt
        )
        
        # 4. 結果を表示
        # 5. 結果を返す
        respond(text=f"*「{query}」の時系列まとめ:*\n\n{response.text}")

    except Exception as e:
        respond(f"エラーが発生しました: {str(e)}")

# --- 機能：チャンネル構成の表示 ---
@app.command("/list-channels")
def list_channels(ack, respond):
    ack()
    user_token = os.environ["SLACK_USER_TOKEN"]
    try:
        # User Tokenを使用して、ユーザーがアクセス可能なチャンネルを取得
        result = app.client.conversations_list(
            token=user_token,
            types="public_channel,private_channel",
            exclude_archived=True
        )
        
        # あなたが参加している(is_member)チャンネルのみ抽出
        channels = [f"• #{c['name']}" for c in result['channels'] if c.get('is_member')]
        
        if not channels:
            respond("アクセス可能なチャンネルが見つかりませんでした。")
        else:
            respond(f"*あなたがアクセス可能なチャンネル一覧:*\n" + "\n".join(channels))
            
    except Exception as e:
        respond(f"チャンネル取得エラー: {e}")

if __name__ == "__main__":
    # SLACK_APP_TOKEN (xapp-...) を使用して起動
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()