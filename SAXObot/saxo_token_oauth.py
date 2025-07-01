#!/usr/bin/env python3
"""
SAXO証券 OAuth 2.0対応トークン取得システム
スプレッドシートから認証情報を読み取り、完全自動化対応
設定ファイル（saxo_settings.json）からも読み込み可能
"""

import aiohttp
import aiofiles
import asyncio
import json
import sys
import os
import base64
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse
import webbrowser
import time

# SAXOlibをインポート
try:
    import SAXOlib
except ImportError:
    print("エラー: SAXOlib.pyが見つかりません")
    sys.exit(1)

# Playwrightの非同期版インポート
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("エラー: Playwrightがインストールされていません")
    print("以下のコマンドでインストールしてください:")
    print("pip install playwright")
    print("playwright install chromium")
    sys.exit(1)

# トークンファイル名
TOKEN_FILE = "saxo_oauth_tokens.json"
SETTINGS_FILE = "saxo_settings.json"

# 設定スプレッドシートURL（デフォルト）
DEFAULT_CONFIG_URL = "設定スプレッドシートのURLをここに入力してください"
#例DEFAULT_CONFIG_URL = "https://docs.google.com/spreadsheets/d/11XWvMsBil-ei111TyCKCPHTDbrQdOsy1BbXM1TI11eQ/edit?usp=sharing"

class SAXOOAuthClient:
    """SAXO証券OAuth認証クライアント"""
    
    def __init__(self, config_url=None):
        """初期化"""
        self.config_url = config_url or DEFAULT_CONFIG_URL
        self.config = None
        self.oauth_config = {
            "sim": {},
            "live": {}
        }
    
    async def load_config(self):
        """設定を読み込み（スプレッドシートまたは設定ファイル）"""
        # まず設定ファイルから読み込みを試みる
        if os.path.exists(SETTINGS_FILE):
            try:
                async with aiofiles.open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    settings = json.loads(content)
                    print("✅ 設定ファイルから情報を読み込みました")
                    
                    # OAuth設定を構築
                    self.oauth_config = {
                        "sim": {
                            "developer_id": settings.get("developer_account", {}).get("sim", {}).get("developer_id", ""),
                            "developer_password": settings.get("developer_account", {}).get("sim", {}).get("developer_password", ""),
                            "app_key": settings.get("application", {}).get("sim", {}).get("app_key", ""),
                            "app_secret": settings.get("application", {}).get("sim", {}).get("app_secret", ""),
                            "auth_endpoint": settings.get("oauth", {}).get("sim", {}).get("auth_endpoint", "https://sim.logonvalidation.net/authorize"),
                            "token_endpoint": settings.get("oauth", {}).get("sim", {}).get("token_endpoint", "https://sim.logonvalidation.net/token"),
                            "api_base": "https://gateway.saxobank.com/sim/openapi",
                            "redirect_uri": settings.get("oauth", {}).get("sim", {}).get("redirect_uri", "http://localhost"),
                            "use_pkce": True  # シミュレーション環境ではPKCEを使用
                        },
                        "live": {
                            "developer_id": settings.get("developer_account", {}).get("live", {}).get("developer_id", ""),
                            "developer_password": settings.get("developer_account", {}).get("live", {}).get("developer_password", ""),
                            "app_key": settings.get("application", {}).get("live", {}).get("app_key", ""),
                            "app_secret": settings.get("application", {}).get("live", {}).get("app_secret", ""),
                            "auth_endpoint": settings.get("oauth", {}).get("live", {}).get("auth_endpoint", "https://live.logonvalidation.net/authorize"),
                            "token_endpoint": settings.get("oauth", {}).get("live", {}).get("token_endpoint", "https://live.logonvalidation.net/token"),
                            "api_base": "https://gateway.saxobank.com/openapi",
                            "redirect_uri": settings.get("oauth", {}).get("live", {}).get("redirect_uri", "http://localhost:8080/callback"),
                            "use_pkce": False  # ライブ環境ではPKCEを使用しない（400エラー対策）
                        }
                    }
                    
                    # スプレッドシートのURLも取得
                    self.config_url = settings.get("spreadsheets", {}).get("config_url", "") or self.config_url
                    
                    # 環境設定の確認
                    self.is_live_mode = settings.get("trading", {}).get("is_live_mode", False)
                    
                    # 必須項目のチェック
                    env_key = "live" if self.is_live_mode else "sim"
                    env_config = self.oauth_config[env_key]
                    
                    missing_items = []
                    if not env_config['developer_id']:
                        missing_items.append(f"デベロッパーID（{env_key}）")
                    if not env_config['developer_password']:
                        missing_items.append(f"デベロッパーパスワード（{env_key}）")
                    if not env_config['app_key']:
                        missing_items.append(f"App Key（{env_key}）")
                    if not env_config['app_secret']:
                        missing_items.append(f"App Secret（{env_key}）")
                    
                    if missing_items:
                        print(f"\n警告: 以下の認証情報が設定されていません:")
                        for item in missing_items:
                            print(f"  - {item}")
                        print("\nスプレッドシートから読み込みを試みます...")
                        # スプレッドシートから読み込みを試みる
                        await self._load_config_from_spreadsheet()
                    else:
                        # 設定ファイルから十分な情報が得られた
                        self.config = settings
                        return True
                    
            except Exception as e:
                print(f"設定ファイルの読み込みエラー: {e}")
                print("スプレッドシートから読み込みを試みます...")
        
        # スプレッドシートから読み込み
        return await self._load_config_from_spreadsheet()
    
    async def _load_config_from_spreadsheet(self):
        """スプレッドシートから設定を読み込み"""
        print("設定スプレッドシートから認証情報を読み込み中...")
        try:
            self.config = await SAXOlib.load_config(self.config_url)
            
            # OAuth設定を構築
            self.oauth_config = {
                "sim": {
                    "developer_id": self.config.get('developer_id_sim', ''),
                    "developer_password": self.config.get('developer_password_sim', ''),
                    "app_key": self.config.get('app_key_sim', ''),
                    "app_secret": self.config.get('app_secret_sim', ''),
                    "auth_endpoint": "https://sim.logonvalidation.net/authorize",
                    "token_endpoint": "https://sim.logonvalidation.net/token",
                    "api_base": "https://gateway.saxobank.com/sim/openapi",
                    "redirect_uri": "http://localhost",
                    "use_pkce": True  # シミュレーション環境ではPKCEを使用
                },
                "live": {
                    "developer_id": self.config.get('developer_id_live', ''),
                    "developer_password": self.config.get('developer_password_live', ''),
                    "app_key": self.config.get('app_key_live', ''),
                    "app_secret": self.config.get('app_secret_live', ''),
                    # ライブ環境のOAuthエンドポイント（2025年1月確認済み）
                    "auth_endpoint": "https://live.logonvalidation.net/authorize",
                    "token_endpoint": "https://live.logonvalidation.net/token",
                    "api_base": "https://gateway.saxobank.com/openapi",  # /sim/を含まない
                    "redirect_uri": "http://localhost:8080/callback",
                    "use_pkce": False  # ライブ環境ではPKCEを使用しない（400エラー対策）
                }
            }
            
            # 環境設定の確認
            self.is_live_mode = self.config.get('is_live_mode', False)
            
            # 必須項目のチェック
            env_key = "live" if self.is_live_mode else "sim"
            env_config = self.oauth_config[env_key]
            
            missing_items = []
            if not env_config['developer_id']:
                missing_items.append(f"デベロッパーID（{env_key}）")
            if not env_config['developer_password']:
                missing_items.append(f"デベロッパーパスワード（{env_key}）")
            if not env_config['app_key']:
                missing_items.append(f"App Key（{env_key}）")
            if not env_config['app_secret']:
                missing_items.append(f"App Secret（{env_key}）")
            
            if missing_items:
                print(f"\n警告: 以下の認証情報が設定されていません:")
                for item in missing_items:
                    print(f"  - {item}")
                print("\nスプレッドシートの以下のセルを確認してください:")
                if env_key == "sim":
                    print("  B2: デベロッパーID（sim）")
                    print("  B3: デベロッパーパスワード（sim）")
                    print("  B4: App Key（sim）")
                    print("  B5: App Secret（sim）")
                else:
                    print("  B6: デベロッパーID（Live）")
                    print("  B7: デベロッパーパスワード（Live）")
                    print("  B8: App Key（Live）")
                    print("  B9: App Secret（Live）")
                return False
            
            return True
        except Exception as e:
            print(f"スプレッドシートからの読み込みエラー: {e}")
            return False
    
    def get_oauth_config(self, is_live=False):
        """環境に応じたOAuth設定を取得"""
        env_key = "live" if is_live else "sim"
        return self.oauth_config[env_key]
    
    def generate_pkce_challenge(self):
        """PKCE用のcode_verifierとcode_challengeを生成"""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')
        return code_verifier, code_challenge
    
    async def load_tokens(self):
        """保存されたトークンを読み込む"""
        if os.path.exists(TOKEN_FILE):
            try:
                async with aiofiles.open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content)
            except Exception as e:
                print(f"トークンファイル読み込みエラー: {e}")
        return {}
    
    async def save_tokens(self, tokens):
        """トークンを保存"""
        try:
            async with aiofiles.open(TOKEN_FILE, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(tokens, ensure_ascii=False, indent=2))
            print(f"✓ トークンを{TOKEN_FILE}に保存しました")
        except Exception as e:
            print(f"トークンファイル保存エラー: {e}")
    
    async def refresh_access_token(self, refresh_token, is_live=False):
        """リフレッシュトークンを使用してアクセストークンを更新"""
        config = self.get_oauth_config(is_live)
        
        if not refresh_token:
            print("リフレッシュトークンがありません")
            return None
        
        # Basic認証ヘッダーを作成
        credentials = f"{config['app_key']}:{config['app_secret']}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config['token_endpoint'],
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status in [200, 201]:
                        token_data = await response.json()
                        print("✓ トークンの更新に成功しました")
                        return token_data
                    else:
                        error_text = await response.text()
                        print(f"✗ トークン更新エラー: {response.status} - {error_text}")
                        return None
        except Exception as e:
            print(f"✗ トークン更新中のエラー: {e}")
            return None
    
    async def get_authorization_code_with_playwright(self, auth_url, config):
        """
        Playwrightを使用して認証コードを取得する
        """
        authorization_code = None
        auth_code_captured = False
        captcha_detected = False
        
        # Playwrightの初期化
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # ヘッドレスモードをオフに
            context = await browser.new_context()
            page = await context.new_page()
            
            # リクエスト/レスポンスのハンドリングを設定
            async def handle_request(request):
                nonlocal authorization_code, auth_code_captured
                url = request.url
                
                # リダイレクトURLに認証コードが含まれているか確認
                if "localhost" in url and "code=" in url:
                    try:
                        from urllib.parse import urlparse, parse_qs
                        parsed = urlparse(url)
                        params = parse_qs(parsed.query)
                        if 'code' in params:
                            authorization_code = params['code'][0]
                            auth_code_captured = True
                            print(f"\n✓ 認証コードを検出: {authorization_code[:10]}...")
                    except Exception as e:
                        print(f"認証コード解析エラー: {e}")
            
            # ナビゲーションイベントのハンドリング
            async def handle_navigation(frame):
                nonlocal authorization_code, auth_code_captured
                url = frame.url
                
                # リダイレクトURLに認証コードが含まれているか確認
                if "localhost" in url and "code=" in url:
                    try:
                        from urllib.parse import urlparse, parse_qs
                        parsed = urlparse(url)
                        params = parse_qs(parsed.query)
                        if 'code' in params:
                            authorization_code = params['code'][0]
                            auth_code_captured = True
                            print(f"\n✓ 認証コードを検出: {authorization_code[:10]}...")
                    except Exception as e:
                        print(f"認証コード解析エラー: {e}")
            
            # イベントリスナーを設定
            page.on("request", handle_request)
            page.on("framenavigated", handle_navigation)
            
            try:
                # 認証ページに移動
                print("認証ページを開いています...")
                print(f"URL: {auth_url}")
                await page.goto(auth_url)
                print("ログインページが表示されました")
                
                # ログイン情報を入力
                print("ログイン情報を入力してください...")
                # 自動ログインを試みる
                developer_id = config.get('developer_id', '')
                developer_password = config.get('developer_password', '')
                
                if developer_id and developer_password:
                    print("自動ログインを実行中...")
                    
                    # ページが完全に読み込まれるまで待つ（最大5秒）
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception as e:
                        print(f"ページ読み込み待機エラー: {e}")
                    
                    # デバッグ用：現在のページ内容を確認
                    try:
                        await page.screenshot(path="oauth_login_page.png")
                        print("   デバッグ: ログインページのスクリーンショットを保存しました")
                        
                        # ページのHTMLを保存（デバッグ用）
                        html_content = await page.content()
                        with open("login_page_html.txt", "w", encoding="utf-8") as f:
                            f.write(html_content)
                        print("   デバッグ: ログインページのHTMLを保存しました")
                    except Exception as e:
                        print(f"スクリーンショット保存エラー: {e}")
                    
                    # 入力フィールドの検出を改善（より多くのセレクタを試す）
                    username_selectors = [
                        "input[type='text']", 
                        "input[type='email']", 
                        "input[id*='user']", 
                        "input[id*='email']",
                        "input[name*='user']",
                        "input[name*='email']",
                        "input[name*='id']",
                        "input:not([type='password'])",
                        "input.username",
                        "input.email"
                    ]
                    
                    # User ID入力 - 複数のセレクタを試す
                    username_input_found = False
                    for selector in username_selectors:
                        try:
                            # 要素が存在するか確認
                            username_element = await page.wait_for_selector(selector, timeout=1000)
                            if username_element:
                                await username_element.fill('')  # 一度クリア
                                await username_element.type(developer_id, delay=50)  # 少し遅めに入力
                                print(f"   ✓ ユーザーID入力完了 ({selector})")
                                username_input_found = True
                                break
                        except Exception as e:
                            continue
                    
                    # 入力フィールドが見つからなかった場合、JavaScriptで試行
                    if not username_input_found:
                        try:
                            # すべての入力フィールドを検索
                            await page.evaluate(f"""
                                () => {{
                                    const inputs = document.querySelectorAll('input');
                                    for (const input of inputs) {{
                                        if (input.type !== 'password' && 
                                            (input.type === 'text' || 
                                             input.type === 'email' || 
                                             !input.type)) {{
                                            input.value = '{developer_id}';
                                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                            return true;
                                        }}
                                    }}
                                    return false;
                                }}
                            """)
                            print("   ✓ ユーザーID入力完了（JavaScript）")
                        except Exception as e:
                            print(f"   ✗ ユーザーID入力エラー: {e}")
                    
                    # 少し待機（ページの反応を待つ）
                    await page.wait_for_timeout(500)
                    
                    # パスワード入力フィールドの検出を改善
                    password_selectors = [
                        "input[type='password']",
                        "input[id*='pass']",
                        "input[name*='pass']",
                        "input.password"
                    ]
                    
                    # Password入力 - 複数のセレクタを試す
                    password_input_found = False
                    for selector in password_selectors:
                        try:
                            password_element = await page.wait_for_selector(selector, timeout=1000)
                            if password_element:
                                await password_element.fill('')  # 一度クリア
                                await password_element.type(developer_password, delay=50)  # 少し遅めに入力
                                print(f"   ✓ パスワード入力完了 ({selector})")
                                password_input_found = True
                                break
                        except Exception as e:
                            continue
                    
                    # 入力フィールドが見つからなかった場合、JavaScriptで試行
                    if not password_input_found:
                        try:
                            await page.evaluate(f"""
                                () => {{
                                    const inputs = document.querySelectorAll('input[type="password"]');
                                    if (inputs.length > 0) {{
                                        inputs[0].value = '{developer_password}';
                                        inputs[0].dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        inputs[0].dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        return true;
                                    }}
                                    return false;
                                }}
                            """)
                            print("   ✓ パスワード入力完了（JavaScript）")
                        except Exception as e:
                            print(f"   ✗ パスワード入力エラー: {e}")
                    
                    # 少し待機（ページの反応を待つ）
                    await page.wait_for_timeout(500)
                    
                    # 自動ログインボタンクリック（CAPTCHAがない場合のみ）
                    # CAPTCHAの検出
                    try:
                        page_text = await page.content()
                        if "captcha" in page_text.lower() or "CAPTCHA" in page_text:
                            captcha_detected = True
                        else:
                            captcha_detected = False
                    except Exception as e:
                        print(f"CAPTCHA検出エラー: {e}")
                        captcha_detected = False
                    
                    # CAPTCHAが検出された場合
                    if captcha_detected:
                        print("\n⚠️ CAPTCHAが検出されました！")
                        print("========================================")
                        print("  ユーザーID・パスワードは入力済みです")
                        print("  以下の手順で手動操作を行ってください：")
                        print("  1. CAPTCHA画像認証を解決")
                        print("  2. ログインボタンをクリック")
                        print("========================================")
                        print("\n自動処理を一時停止し、手動操作を待機しています...")
                        
                        # スクリーンショットを保存
                        await page.screenshot(path="captcha_screen.png")
                        print("CAPTCHAのスクリーンショットを保存しました: captcha_screen.png")
                        
                        # 手動ログインを待機
                        manual_login_timeout = 300  # 5分
                        print(f"\n手動ログインのために {manual_login_timeout//60} 分間待機します...")
                    else:
                        # CAPTCHAがない場合は自動でログインボタンをクリック
                        print("   ログイン処理を待機中...")
                        
                        # ログインボタンをクリック（改善版）
                        login_clicked = False
                        
                        # より広範なセレクタリスト
                        login_selectors = [
                            "button:has-text('Log in')",
                            "button:has-text('LOGIN')",
                            "button:has-text('Login')",
                            "button:has-text('Sign in')",
                            "button:has-text('SIGN IN')",
                            "button:has-text('Submit')",
                            "button:has-text('SUBMIT')",
                            "input[type='submit']",
                            "button[type='submit']",
                            "button.login-button",
                            "button#login",
                            "input[value='Log in']",
                            "input[value='LOGIN']",
                            "input[value='Sign in']",
                            "input[value='SIGN IN']",
                            "button.btn-primary",
                            "button.primary",
                            "button.submit",
                            "a:has-text('Log in')",
                            "a:has-text('LOGIN')",
                            "a:has-text('Sign in')"
                        ]
                        
                        # 各セレクタを試す（タイムアウトを長めに設定）
                        for selector in login_selectors:
                            try:
                                login_button = await page.wait_for_selector(selector, timeout=500)
                                if login_button:
                                    await login_button.click()
                                    print(f"   ✓ ログインボタンクリック（{selector}）")
                                    login_clicked = True
                                    break
                            except Exception as e:
                                continue
                        
                        # 方法2: JavaScriptでボタンを探して直接クリック
                        if not login_clicked:
                            try:
                                clicked = await page.evaluate("""
                                    () => {
                                        // ボタン要素を探す
                                        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], a.btn, a[role="button"]'));
                                        
                                        // テキストでログインボタンを特定
                                        for (const btn of buttons) {
                                            const text = btn.textContent.toLowerCase() || '';
                                            const value = btn.value ? btn.value.toLowerCase() : '';
                                            
                                            if (text.includes('log') || text.includes('sign') || 
                                                text.includes('submit') || text.includes('continue') ||
                                                value.includes('log') || value.includes('sign') ||
                                                value.includes('submit')) {
                                                btn.click();
                                                return true;
                                            }
                                        }
                                        
                                        // フォームを直接送信
                                        const forms = document.querySelectorAll('form');
                                        if (forms.length > 0) {
                                            forms[0].submit();
                                            return true;
                                        }
                                        
                                        return false;
                                    }
                                """)
                                
                                if clicked:
                                    print("   ✓ ログインボタンクリック（JavaScript）")
                                    login_clicked = True
                            except Exception as e:
                                print(f"   ✗ JavaScriptによるログインボタンクリックエラー: {e}")
                
                # 認証完了を待機
                print("\n認証完了を待機中...")
                print("「このサイトにアクセスできません」エラーが出ても正常です")
                
                # 認証コードを待機
                start_time = time.time()
                timeout = 120  # 2分
                
                while not auth_code_captured and time.time() - start_time < timeout:
                    # 5秒ごとに待機状況を表示
                    elapsed = int(time.time() - start_time)
                    if elapsed % 5 == 0:
                        print(f"待機中... ({elapsed}秒)")
                    
                    # URLをチェック
                    if "localhost" in page.url or "127.0.0.1" in page.url:
                        if "code=" in page.url:
                            from urllib.parse import urlparse, parse_qs
                            parsed = urlparse(page.url)
                            params = parse_qs(parsed.query)
                            if 'code' in params:
                                authorization_code = params['code'][0]
                                auth_code_captured = True
                                print(f"\n✓ 認証コードを検出: {authorization_code[:10]}...")
                                break
                    
                    await asyncio.sleep(1)
                
                if not auth_code_captured:
                    print(f"\n✗ タイムアウト: {timeout}秒以内に認証が完了しませんでした")
            
            except Exception as e:
                print(f"認証プロセスエラー: {e}")
                import traceback
                traceback.print_exc()
            
            finally:
                # ブラウザを閉じる
                await browser.close()
        
        if not authorization_code:
            print("\n認証コードの取得に失敗しました")
        
        return authorization_code
    
    async def get_access_token_oauth(self, is_live=False):
        """OAuth 2.0フローでアクセストークンを取得"""
        config = self.get_oauth_config(is_live)
        env_text = "ライブ" if is_live else "シミュレーション"
        
        print(f"\n{env_text}環境のOAuth 2.0認証を開始します...")
        
        # ライブ環境の場合、設定を確認
        if is_live:
            print("\n=== ライブ環境設定の確認 ===")
            print(f"App Key: {config['app_key'][:10]}..." if config['app_key'] else "App Key: 未設定")
            print(f"App Secret: {'*' * 10}..." if config['app_secret'] else "App Secret: 未設定")
            print(f"Redirect URI: {config['redirect_uri']}")
            print(f"Auth Endpoint: {config['auth_endpoint']}")
            print("========================\n")
            
            if not config['app_key'] or not config['app_secret']:
                print("\n✗ ライブ環境のApp KeyまたはApp Secretが設定されていません")
                print("\n解決方法:")
                print("1. SAXO開発者ポータルでライブ環境のアプリケーションを作成")
                print("2. スプレッドシートのB8, B9に入力")
                print("\n詳細は「SAXO証券 ライブ環境アプリケーション設定ガイド」を参照")
                return None
        
        # 認証URLを構築
        auth_params = {
            "response_type": "code",
            "client_id": config['app_key'],
            "redirect_uri": config['redirect_uri'],
            "state": secrets.token_urlsafe(16)
        }
        
        # PKCEを使用するかどうか
        use_pkce = config.get('use_pkce', True)
        code_verifier = None
        
        if use_pkce:
            # PKCEパラメータを生成
            code_verifier, code_challenge = self.generate_pkce_challenge()
            auth_params["code_challenge"] = code_challenge
            auth_params["code_challenge_method"] = "S256"
            print("PKCEを使用した認証を実行します")
        else:
            print("PKCEを使用しない認証を実行します（ライブ環境）")
        
        auth_url = f"{config['auth_endpoint']}?{urlencode(auth_params)}"
        
        # Playwrightで認証コードを取得
        authorization_code = await self.get_authorization_code_with_playwright(auth_url, config)
        
        if not authorization_code:
            print("\n認証コードの取得に失敗しました")
            
            if is_live:
                print("\n=== ライブ環境のチェックリスト ===")
                print("□ SAXO証券の実際の取引口座を持っていますか？")
                print("□ 開発者ポータルで「Live Apps」タブが表示されますか？")
                print("□ ライブ環境用のアプリケーションを作成しましたか？")
                print("□ アプリケーションのRedirect URLは「http://localhost」ですか？")
                print("□ スプレッドシートのB8, B9に正しいApp Key/Secretが入力されていますか？")
                print("=====================================\n")
            
            return None
        
        # 認証コードをアクセストークンに交換
        token_data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": config['redirect_uri']
        }
        
        # PKCEを使用している場合のみcode_verifierを追加
        if code_verifier:
            token_data["code_verifier"] = code_verifier
        
        # Basic認証ヘッダーを作成
        credentials = f"{config['app_key']}:{config['app_secret']}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config['token_endpoint'],
                    data=token_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status in [200, 201]:
                        tokens = await response.json()
                        print("✓ アクセストークンの取得に成功しました")
                        print(f"  - トークンタイプ: {tokens.get('token_type', 'N/A')}")
                        print(f"  - 有効期限: {tokens.get('expires_in', 'N/A')}秒")
                        print(f"  - リフレッシュトークン有効期限: {tokens.get('refresh_token_expires_in', 'N/A')}秒")
                        
                        # トークン情報を保存
                        tokens['obtained_at'] = datetime.now().isoformat()
                        tokens['is_live'] = is_live
                        
                        # 既存のトークンデータを読み込み
                        all_tokens = await self.load_tokens()
                        env_key = "live" if is_live else "sim"
                        all_tokens[env_key] = tokens
                        
                        # ファイルに保存
                        await self.save_tokens(all_tokens)
                        
                        # 旧形式のトークンファイルにも保存
                        token_file = "token_live.txt" if is_live else "token_sim.txt"
                        try:
                            async with aiofiles.open(token_file, 'w') as f:
                                await f.write(tokens['access_token'])
                            print(f"✓ トークンを{token_file}に保存しました（後方互換性用）")
                        except Exception as e:
                            print(f"警告: 旧形式ファイルへの保存に失敗: {e}")
                        
                        return tokens
                    else:
                        error_text = await response.text()
                        print(f"✗ トークン交換エラー: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            print(f"✗ トークン取得エラー: {e}")
            return None
    
    async def check_token_validity(self, access_token, is_live=False):
        """トークンの有効性を確認"""
        config = self.get_oauth_config(is_live)
        base_url = config['api_base']
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        env_text = "ライブ" if is_live else "シミュレーション"
        print(f"\n{env_text}環境 トークンチェック中...")
        
        try:
            url = f"{base_url}/port/v1/users/me"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        user_data = await response.json()
                        print("✓ トークンは有効です")
                        print(f"  - ユーザーID: {user_data.get('UserId', 'N/A')}")
                        print(f"  - クライアントキー: {user_data.get('ClientKey', 'N/A')}")
                        return True
                    else:
                        print("✗ トークンが無効または期限切れです")
                        return False
        except Exception as e:
            print(f"✗ トークンチェックエラー: {e}")
            return False
    
    async def get_valid_token(self, is_live=None):
        """有効なトークンを取得（必要に応じて更新）"""
        # is_liveが指定されていない場合は、設定から読み取る
        if is_live is None:
            is_live = self.is_live_mode
        
        env_key = "live" if is_live else "sim"
        env_text = "ライブ" if is_live else "シミュレーション"
        
        # 保存されたトークンを読み込み
        all_tokens = await self.load_tokens()
        tokens = all_tokens.get(env_key)
        
        if tokens and 'access_token' in tokens:
            # トークンの有効性を確認
            if await self.check_token_validity(tokens['access_token'], is_live):
                return tokens['access_token'], is_live
            
            # 無効な場合、リフレッシュトークンで更新を試みる
            if 'refresh_token' in tokens:
                print(f"\n{env_text}環境のトークンを更新中...")
                new_tokens = await self.refresh_access_token(tokens['refresh_token'], is_live)
                
                if new_tokens:
                    new_tokens['obtained_at'] = datetime.now().isoformat()
                    new_tokens['is_live'] = is_live
                    all_tokens[env_key] = new_tokens
                    await self.save_tokens(all_tokens)
                    
                    if await self.check_token_validity(new_tokens['access_token'], is_live):
                        return new_tokens['access_token'], is_live
        
        # 新規にOAuth認証を実行
        print(f"\n{env_text}環境の新規認証が必要です")
        tokens = await self.get_access_token_oauth(is_live)
        
        if tokens and await self.check_token_validity(tokens['access_token'], is_live):
            return tokens['access_token'], is_live
        
        return None, None


# グローバルインスタンス（後方互換性のため）
_client = None


async def get_valid_token(is_live=False):
    """
    有効なトークンを取得する関数（後方互換性用）
    戻り値: (トークン文字列, is_live_mode) のタプル
    """
    global _client
    
    if _client is None:
        _client = SAXOOAuthClient()
        if not await _client.load_config():
            return None, None
    
    return await _client.get_valid_token(is_live)


async def main():
    """メイン処理"""
    print("SAXO証券 OAuth 2.0 トークン管理システム")
    print("=" * 50)
    
    # クライアントを初期化
    client = SAXOOAuthClient()
    
    # 設定を読み込み
    if not await client.load_config():
        print("\n設定の読み込みに失敗しました")
        return None, None
    
    # 有効なトークンを取得
    token, env_is_live = await client.get_valid_token()
    
    if token:
        env_text = "ライブ" if env_is_live else "シミュレーション"
        print(f"\n✓ {env_text}環境の有効なトークンを取得しました")
        return token, env_is_live
    else:
        print("\n✗ トークンの取得に失敗しました")
        return None, None


if __name__ == "__main__":
    asyncio.run(main())