import os
from google import genai
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Geminiの初期化
client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
CURRENT_MODEL = "models/gemini-flash-lite-latest"

# Slackアプリの初期化
app = App(token=os.environ["SLACK_BOT_TOKEN"])

# --- 追加：共通の表示ルール定義 ---
SLACK_FORMAT_RULES = """
【Slack表示用・絶対禁止ルール】
1. **（アスタリスク2つ）は禁止。太字は必ず *テキスト* （アスタリスク1つ）で囲む。
2. #（シャープ）による見出しは禁止。見出しは *【見出し名】* のように太字で表現する。
3. 表（テーブル記法）は禁止。必ず箇条書き（ • ）で書くこと。
4. HTMLタグは絶対に入れない。
5. リンクの書式 <https://...|[テキスト]> は絶対に変更しない。
"""

def get_channel_context(user_token, channel_id, limit=100):
    """実行されたチャンネルの直近100件のログを確実に取得する"""
    try:
        res = app.client.conversations_history(
            token=user_token,
            channel=channel_id,
            limit=limit
        )
        messages = res.get('messages', [])
        
        history_data = []
        for m in reversed(messages):
            if 'text' in m and m.get('subtype') is None:
                dt = datetime.fromtimestamp(float(m['ts'])).strftime('%m/%d %H:%M')
                # ユーザーIDを名前に変換するのは大変なので、一旦そのままか User と表記
                user_name = m.get('user', 'User')
                history_data.append(f"• [{dt}] {user_name}: {m['text']}")
        
        return "\n\n".join(history_data)
    except Exception as e:
        print(f"Error fetching history: {e}")
        return ""

# --- 強化版：インテリジェンス要約 (/summarize) ---
@app.command("/summarize")
def handle_summarize(ack, respond, command):
    user_input = command['text']
    channel_id = command['channel_id']
    ack(f"「{user_input}」に関するログを詳しく探しています...")
    user_token = os.environ["SLACK_USER_TOKEN"]

    # 1. 履歴を直接取得（検索の遅延に影響されない）
    context_text = get_channel_context(user_token, channel_id, limit=100)

    if not context_text:
        respond("ログの取得に失敗したか、メッセージが見つかりませんでした。")
        return

    prompt = f"""
    あなたは優秀な記録係です。以下の【会話ログ】を時系列で要約してください。
    【会話ログ】は現在のチャンネルのものに限定されています。
    {SLACK_FORMAT_RULES}
    
    【指示】: {user_input}
    【会話ログ】:
    {context_text}
    """
    
    response = client_gemini.models.generate_content(model=CURRENT_MODEL, contents=prompt)
    respond(text=f"*直近のチャンネル要約:*\n\n{response.text}")

# --- 強化版：自由分析 (/ask) ---
@app.command("/ask")
def handle_ask_command(ack, respond, command):
    user_instruction = command['text']
    channel_id = command['channel_id']
    ack(f"📝 「{user_instruction}」を分析中...")
    user_token = os.environ["SLACK_USER_TOKEN"]

    try:
        # 1. 検索ではなく「履歴」を取得するように変更（これでキムチ鍋も拾えます）
        context_text = get_channel_context(user_token, channel_id, limit=100)

        if not context_text:
            respond("ログが見つかりませんでした。")
            return

        # 2. 回答の「センス」を磨くプロンプト
        final_prompt = f"""
        あなたは「社内ナレッジの鑑定士」です。提供された【会話ログ】のみを根拠にして、ユーザーの【指示】に答えてください。
        {SLACK_FORMAT_RULES}
        
        【重要】
        提供された会話ログは、すべて現在のチャンネル（{channel_id}）内のものです。
        これ以外の情報は一切考慮せず、このログの中にある事実のみを回答してください。
        ログに関連する内容がない場合は「その話題は見当たりませんでした」と答えてください。

        【指示】: {user_instruction}
        【会話ログ】:
        {context_text}
        """

        response = client_gemini.models.generate_content(model=CURRENT_MODEL, contents=final_prompt)
        respond(f"✅ *分析結果:*\n\n{response.text}")

    except Exception as e:
        respond(f"エラー: {str(e)}")

# --- 機能：チャンネル構成の表示 ---
@app.command("/list-channels")
def list_channels(ack, respond):
    ack()
    user_token = os.environ["SLACK_USER_TOKEN"]
    try:
        result = app.client.conversations_list(
            token=user_token,
            types="public_channel,private_channel",
            exclude_archived=True
        )
        channels = [f"• #{c['name']}" for c in result['channels'] if c.get('is_member')]
        
        if not channels:
            respond("アクセス可能なチャンネルが見つかりませんでした。")
        else:
            respond(f"*アクセス可能なチャンネル一覧:*\n" + "\n".join(channels))
    except Exception as e:
        respond(f"チャンネル取得エラー: {e}")

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()