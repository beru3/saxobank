#!/usr/bin/env python3
"""
SAXO証券 非同期対応自動トークン取得システム
トークンが無効な場合、自動的に新しいトークンを取得します（非同期版）
ライブ/シミュレーション環境別のトークン管理対応
"""

import aiohttp
import aiofiles
import json
import sys
import os
import asyncio
from datetime import datetime
from pathlib import Path

# Playwrightの非同期版インポート
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("エラー: Playwrightがインストールされていません")
    print("以下のコマンドでインストールしてください:")
    print("pip install playwright")
    print("playwright install chromium")
    sys.exit(1)

# 認証情報の設定（スプレッドシートから取得できない場合はここに入力）
SAXO_USER_ID = ""
SAXO_PASSWORD = ""

# 設定ファイル名
CONFIG_FILE = "saxo_config.json"


def get_token_filename(is_live=False):
    """
    環境に応じたトークンファイル名を返す
    
    Args:
        is_live (bool): ライブ環境かどうか
        
    Returns:
        str: トークンファイル名
    """
    if is_live:
        return "token_live.txt"
    else:
        return "token_sim.txt"


async def load_config():
    """設定ファイルから認証情報を読み込む（非同期版）"""
    if os.path.exists(CONFIG_FILE):
        try:
            async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = await f.read()
                config = json.loads(content)
                return config.get('user_id', ''), config.get('password', '')
        except Exception as e:
            print(f"設定ファイルの読み込みエラー: {e}")
    return None, None


async def save_config(user_id, password):
    """認証情報を設定ファイルに保存（非同期版）"""
    config = {
        'user_id': user_id,
        'password': password,
        'updated_at': datetime.now().isoformat()
    }
    try:
        async with aiofiles.open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(config, ensure_ascii=False, indent=2))
        print(f"✓ 設定を{CONFIG_FILE}に保存しました")
    except Exception as e:
        print(f"設定ファイルの保存エラー: {e}")


async def get_credentials_from_sheets():
    """
    Googleスプレッドシートから認証情報を取得（公開CSVとして）（非同期版）
    SAXOlib.load_config()と同じ方法でCSVを読み込む
    
    Returns:
        tuple: (user_id, password, is_live_mode)
    """
    try:
        # GoogleスプレッドシートのCSVエクスポートURL
        sheet_id = "設定スプレッドシートIDをここに入力"  # 例: "11XWvMsBil-ei111TyCKCPHTDbrQdOsy11bXM8TI32eQ"
        # gidを指定しない（デフォルトシート）
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
        
        print("スプレッドシートから認証情報を取得中...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(csv_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    text = await response.text()
                    
                    # SAXOlib.load_config()と同じ方法でパース
                    from io import StringIO
                    import csv
                    
                    csv_data = StringIO(text)
                    next(csv_data)  # 最初のヘッダー行をスキップ（重要！）
                    reader = csv.reader(csv_data)
                    configdata = [row for row in reader]
                    
                    if len(configdata) >= 1:
                        # configdata[0]が3行目（A3-G3）のデータ
                        row1 = configdata[0]
                        
                        # G3セルからライブモード設定を読み込む
                        is_live_mode = False
                        if len(row1) > 6:
                            g3_value = row1[6].strip()
                            is_live_mode = g3_value.upper() == 'TRUE'
                            print(f"G3セルの値: '{g3_value}' → {'ライブ環境' if is_live_mode else 'シミュレーション環境'}")
                        
                        # モードに応じて認証情報を選択
                        if is_live_mode:
                            # ライブモード: A4, B4（configdata[1]）
                            if len(configdata) >= 2 and len(configdata[1]) >= 2:
                                user_id = configdata[1][0]  # A4
                                password = configdata[1][1]  # B4
                                print("✓ スプレッドシートからライブ環境の認証情報を取得しました")
                            else:
                                print("✗ ライブ環境の認証情報が見つかりません（4行目にA4,B4の値を入力してください）")
                                # エラーとして処理
                                return None, None, None
                        else:
                            # シミュレーションモード: A3, B3（configdata[0]）
                            if len(row1) >= 2:
                                user_id = row1[0]  # A3
                                password = row1[1]  # B3
                                print("✓ スプレッドシートからシミュレーション環境の認証情報を取得しました")
                            else:
                                print("✗ シミュレーション環境の認証情報が見つかりません")
                                return None, None, None
                        
                        return user_id, password, is_live_mode
                    else:
                        print("✗ スプレッドシートにデータがありません")
                        return None, None, None
                    
        print("✗ スプレッドシートからの取得に失敗しました")
        return None, None, None
        
    except Exception as e:
        print(f"✗ スプレッドシートのアクセスエラー: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None


async def get_credentials():
    """
    認証情報を取得（優先順位: スプレッドシート → 設定ファイル → 変数）（非同期版）
    
    Returns:
        tuple: (user_id, password, is_live_mode)
    """
    # 1. スプレッドシートから取得を試みる
    user_id, password, is_live_mode = await get_credentials_from_sheets()
    
    # 2. スプレッドシートから取得できなかった場合、設定ファイルを確認
    if not user_id or not password:
        user_id, password = await load_config()
        if user_id and password:
            print("✓ 設定ファイルから認証情報を読み込みました")
            is_live_mode = False  # 設定ファイルからの場合はデフォルトでシミュレーション
    
    # 3. それでも取得できない場合、変数を使用
    if not user_id or not password:
        if SAXO_USER_ID and SAXO_PASSWORD:
            user_id = SAXO_USER_ID
            password = SAXO_PASSWORD
            is_live_mode = False  # ハードコードの場合はデフォルトでシミュレーション
            print("✓ ハードコードされた認証情報を使用します")
        else:
            # 手動入力を求める（同期的な入力のため、別スレッドで実行）
            print("\n認証情報が見つかりません。")
            loop = asyncio.get_event_loop()
            user_id = await loop.run_in_executor(None, input, "SAXO証券のユーザーID（メールアドレス）を入力: ")
            password = await loop.run_in_executor(None, input, "パスワードを入力: ")
            
            user_id = user_id.strip()
            password = password.strip()
            
            # 手動入力の場合、ライブ/シミュレーションを選択
            mode_choice = await loop.run_in_executor(None, input, "ライブ環境を使用しますか？ (y/n): ")
            is_live_mode = mode_choice.lower() == 'y'
            
            if user_id and password:
                save_choice = await loop.run_in_executor(None, input, "この認証情報を保存しますか？ (y/n): ")
                if save_choice.lower() == 'y':
                    await save_config(user_id, password)
    
    return user_id, password, is_live_mode


# saxo_token_async.pyの修正部分

# get_token_automatically関数を以下のように修正

async def get_token_automatically(user_id, password, is_live=False):
    """
    Playwrightを使用して自動的にトークンを取得（非同期版）
    
    Args:
        user_id (str): ユーザーID
        password (str): パスワード
        is_live (bool): ライブ環境かどうか
    """
    env_text = "ライブ" if is_live else "シミュレーション"
    print(f"\n{env_text}環境の自動トークン取得を開始します...")
    
    try:
        async with async_playwright() as p:
            # ブラウザの起動（デバッグ時はheadless=Falseに変更可能）
            browser = await p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            try:
                # 環境に応じてURLを変更
                if is_live:
                    # ライブ環境の場合
                    # 注意: ライブ環境では24時間トークンは利用できないため、
                    # OAuth認証を使用する必要があります
                    print("警告: ライブ環境では24時間トークンは利用できません。")
                    print("OAuth認証（saxo_token_oauth.py）を使用してください。")
                    return None
                else:
                    # シミュレーション環境のトークンページURL
                    token_url = "https://www.developer.saxo/openapi/token/current"
                    print("1. SAXOシミュレーション環境の開発者ポータルにアクセス中...")
                
                await page.goto(token_url, wait_until="networkidle")
                
                # ページの読み込み待機
                await page.wait_for_timeout(2000)
                
                # ログインが必要かチェック
                if "log in" in page.url.lower() or await page.locator("input[type='email'], input[type='text']").is_visible():
                    print(f"2. {env_text}環境へのログイン処理中...")
                    
                    # メールアドレス/ユーザーID入力
                    email_selectors = ["input[type='text']", "input[name='field_userid']"]
                    for selector in email_selectors:
                        try:
                            email_input = page.locator(selector).first
                            if await email_input.is_visible():
                                await email_input.fill(user_id)
                                print("   - ユーザーID入力完了")
                                break
                        except:
                            continue
                    
                    # パスワード入力
                    password_input = page.locator("input[name='field_password']").first
                    if await password_input.is_visible():
                        await password_input.fill(password)
                        print("   - パスワード入力完了")
                    
                    # ログインボタンクリック
                    login_button_selectors = [
                        "button:has-text('Sign in')", 
                        "button:has-text('Log in')",
                        "button:has-text('Login')",
                        "button:has-text('ログイン')",
                        "input[type='submit']"
                    ]
                    for selector in login_button_selectors:
                        try:
                            login_btn = page.locator(selector).first
                            if await login_btn.is_visible():
                                await login_btn.click()
                                print("   - ログインボタンクリック")
                                break
                        except:
                            continue
                    
                    # ログイン完了待機
                    await page.wait_for_timeout(5000)
                
                print(f"3. {env_text}環境のトークンページを確認中...")
                
                # トークンページへ再度アクセス（リダイレクトされた場合のため）
                if "token" not in page.url:
                    await page.goto(token_url, wait_until="networkidle")
                    await page.wait_for_timeout(3000)
                
                # トークンを探す
                token = None
                
                # 方法1: トークン表示エリアを探す
                token_selectors = [
                    "pre", "code", 
                    "[class*='token']", 
                    "[id*='token']",
                    "textarea",
                    "input[readonly]"
                ]
                
                for selector in token_selectors:
                    try:
                        elements = await page.locator(selector).all()
                        for element in elements:
                            text = (await element.inner_text()).strip()
                            # トークンらしい文字列をチェック（長さと形式）
                            if len(text) > 50 and not " " in text and (text.startswith("ey") or "." in text):
                                token = text
                                print(f"✓ {env_text}環境のトークンを取得しました")
                                break
                    except:
                        continue
                    if token:
                        break
                
                # 方法2: ページ全体からトークンらしい文字列を探す
                if not token:
                    page_content = await page.content()
                    import re
                    # JWT形式のトークンを探す
                    token_pattern = r'ey[A-Za-z0-9\-_]+\.ey[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+'
                    matches = re.findall(token_pattern, page_content)
                    if matches:
                        token = matches[0]
                        print(f"✓ {env_text}環境のトークンをページから抽出しました")
                
                if token:
                    # 環境別のファイル名でトークンを保存
                    token_file = get_token_filename(is_live)
                    async with aiofiles.open(token_file, 'w') as f:
                        await f.write(token)
                    print(f"✓ {env_text}環境のトークンを{token_file}に保存しました")
                    return token
                else:
                    print(f"✗ {env_text}環境のトークンの取得に失敗しました")
                    # デバッグ用：スクリーンショットを保存
                    await page.screenshot(path=f"token_page_debug_{env_text}.png")
                    print(f"  デバッグ用スクリーンショットを保存しました: token_page_debug_{env_text}.png")
                    return None
                    
            finally:
                await browser.close()
                
    except Exception as e:
        print(f"✗ {env_text}環境の自動取得エラー: {e}")
        return None


async def check_token_simple(token, is_live=False):
    """シンプルなトークンチェック（非同期版）"""
    base_url = "https://gateway.saxobank.com/openapi" if is_live else "https://gateway.saxobank.com/sim/openapi"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    print(f"\nSAXO証券 トークンチェック ({'本番' if is_live else 'シミュレーション'}環境)")
    print("=" * 50)
    
    try:
        url = f"{base_url}/port/v1/users/me"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    user_data = await response.json()
                    print("✓ トークンは有効です！")
                    print(f"  - ユーザーID: {user_data.get('UserId', 'N/A')}")
                    print(f"  - クライアントキー: {user_data.get('ClientKey', 'N/A')}")
                    return True
                else:
                    print("✗ トークンが無効または期限切れです")
                    return False
            
    except Exception as e:
        print(f"✗ エラー: {e}")
        return False


async def main():
    """メイン処理（非同期版）"""
    print("SAXO証券 非同期自動トークン取得システム")
    print("=" * 50)
    
    # 認証情報を取得
    user_id, password, is_live_mode = await get_credentials()
    
    if not user_id or not password:
        print("\n認証情報が取得できませんでした。")
        return None, None
    
    # モード表示
    mode_text = "ライブ環境" if is_live_mode else "シミュレーション環境"
    print(f"\n★ {mode_text}で動作します")
    
    # 環境別のトークンファイル名
    token_file = get_token_filename(is_live_mode)
    
    # 既存のトークンをチェック
    token = None
    if os.path.exists(token_file):
        try:
            async with aiofiles.open(token_file, 'r') as f:
                token = (await f.read()).strip()
            print(f"✓ 既存の{mode_text}トークンを{token_file}から読み込みました")
        except:
            pass
    else:
        # 旧形式のtoken.txtがある場合の互換性対応
        old_token_file = "token.txt"
        if os.path.exists(old_token_file) and not is_live_mode:
            try:
                async with aiofiles.open(old_token_file, 'r') as f:
                    token = (await f.read()).strip()
                print(f"✓ 既存のトークンを{old_token_file}から読み込みました（旧形式）")
                # 新しいファイル名にコピー
                async with aiofiles.open(token_file, 'w') as f:
                    await f.write(token)
                print(f"  → {token_file}にコピーしました")
            except:
                pass
    
    # トークンの有効性チェック
    if token:
        if await check_token_simple(token, is_live=is_live_mode):
            print(f"\n既存の{mode_text}トークンは有効です。")
            return token, is_live_mode
        else:
            print(f"\n既存の{mode_text}トークンは無効です。新しいトークンを取得します。")
    else:
        print(f"\n{mode_text}のトークンが見つかりません。新しいトークンを取得します。")
    
    # 自動でトークンを取得（環境を指定）
    new_token = await get_token_automatically(user_id, password, is_live=is_live_mode)
    
    if new_token:
        print(f"\n新しい{mode_text}トークンの確認中...")
        if await check_token_simple(new_token, is_live=is_live_mode):
            print(f"\n✓ 新しい{mode_text}トークンの取得と検証が完了しました！")
            return new_token, is_live_mode
        else:
            print(f"\n✗ 取得した{mode_text}トークンが無効です。手動で取得してください。")
            if is_live_mode:
                print("ライブ環境URL: https://www.developer.saxo/openapi/token/current")
            else:
                print("シミュレーション環境URL: https://www.developer.saxo/openapi/token/current")
            print(f"取得したトークンを {token_file} に保存してください。")
            return None, None
    else:
        print(f"\n✗ {mode_text}の自動取得に失敗しました。")
        print("手動でトークンを取得してください:")
        if is_live_mode:
            print("1. https://www.developer.saxo/openapi/token/current にアクセス（ライブ環境）")
        else:
            print("1. https://www.developer.saxo/openapi/token/current にアクセス（シミュレーション環境）")
        print("2. ログイン")
        print(f"3. 表示されたトークンを{token_file}に保存")
        return None, None


# 他の非同期システムから呼び出すための関数
async def get_valid_token():
    """
    有効なトークンを取得する関数（他の非同期システムから呼び出し用）
    戻り値: (トークン文字列, is_live_mode) のタプル
    """
    return await main()


# 後方互換性のための関数
async def get_valid_token_legacy():
    """
    有効なトークンを取得する関数（後方互換性用）
    戻り値: トークン文字列、または None
    """
    result = await main()
    if result and len(result) == 2:
        return result[0]
    return None


if __name__ == "__main__":
    # スタンドアロンで実行する場合
    asyncio.run(main())