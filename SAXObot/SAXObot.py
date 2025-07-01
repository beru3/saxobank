#!/usr/bin/env python3
"""
SAXO証券 FXBot - 完全版
GMOcoinbot2の機能をSAXO API対応で実装
"""

VERSION = "2025.06.10.002"  # JSONファイル設定対応版

import asyncio
import sys
import os
import logging
import traceback
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import json
import uuid
import requests
import SAXOlib
# OAuth認証モジュールの条件付きインポート
try:
    from saxo_token_oauth import get_valid_token as get_oauth_token
    USE_OAUTH = True
    print("OAuth認証モジュールを使用します")
except ImportError:
    print("OAuth認証モジュールが見つかりません。従来の認証を使用します。")
    from saxo_token_async import get_valid_token
    USE_OAUTH = False

from saxo_openapi import API
import saxo_openapi.endpoints.trading as tr
import saxo_openapi.endpoints.portfolio as pf
import saxo_openapi.endpoints.referencedata as rd
import saxo_openapi.endpoints.rootservices as rs
import saxo_openapi.contrib.session as session
# 個別のエンドポイントをインポート
try:
    import saxo_openapi.endpoints.portfolio.accounts as accounts
    import saxo_openapi.endpoints.portfolio.positions as positions
except ImportError:
    pass

# 設定ファイルパス
SETTINGS_FILE = "saxo_settings.json"

class SaxoBot:
    """SAXO証券FXBotクラス"""
    
    # よく使われる通貨ペアのUICキャッシュ（API呼び出しを減らすため）
    _uic_cache = {}
    
    def __init__(self, token, is_live=False, discord_key=None):
        """
        初期化
        
        Args:
            token (str or tuple): SAXO証券のアクセストークン（文字列またはタプル）
            is_live (bool): ライブ環境かどうか（デフォルト: False = シミュレーション）
            discord_key (str): Discord Webhook URL（オプション）
        """
        # トークンがタプルの場合は最初の要素（アクセストークン）を使用
        if isinstance(token, tuple) and len(token) > 0:
            self.access_token = token[0]
            # リフレッシュトークンがあれば保存
            self.refresh_token = token[1] if len(token) > 1 else None
        else:
            self.access_token = token
            self.refresh_token = None
            
        self.is_live = is_live
        self.discord_key = discord_key
        self._token_refresh_count = 0  # トークン再取得の回数を記録
        self._max_token_refresh = 3  # 最大再取得回数
        
        # トークン有効期限管理用の変数を追加
        self.token_expires_at = None
        self.refresh_token_expires_at = None
        self._token_refresh_task = None  # バックグラウンドタスク用
        self._last_refresh_check = datetime.now()  # 最後のチェック時刻
        
        # トークン情報を読み込む
        self._load_token_info()
        
        # APIクライアントを初期化
        self._initialize_client()
        
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.account_key = None
        self.client_key = None
        self.account_info = None
    
    def _initialize_client(self):
        """APIクライアントの初期化（トークン更新時にも使用）"""
        # ライブ/シミュレーションに応じてエンドポイントを設定
        if self.is_live:
            # ライブ環境のエンドポイント（確認済み）
            self.base_url = "https://gateway.saxobank.com/openapi"
            print("★ SaxoBot: ライブ環境で初期化されました")
            print(f"  - REST API: {self.base_url}")
            print(f"  - 認証: https://live.logonvalidation.net")
            
            # saxo-openapi ライブラリの環境設定（改善版）
            try:
                # 方法1: 環境パラメータを使用
                self.client = API(access_token=self.access_token, environment='live')
                logging.info("ライブ環境用APIクライアント初期化（environment='live'）")
            except Exception as e1:
                try:
                    # 方法2: 通常の初期化後にURLを変更
                    self.client = API(access_token=self.access_token)
                    
                    # APIのベースURLを直接変更する方法を探す
                    if hasattr(self.client, 'api_url'):
                        self.client.api_url = self.base_url
                    
                    # saxo-openapiの内部構造に応じて調整
                    if hasattr(self.client, '_api_url'):
                        self.client._api_url = self.base_url
                    
                    # リクエスト時のベースURLを変更
                    if hasattr(self.client, '_session'):
                        # セッションのベースURLを変更（存在する場合）
                        pass
                    
                    # saxo_openapiの環境設定を確認
                    if hasattr(self.client, 'environment'):
                        self.client.environment = 'live'
                    
                    logging.info("ライブ環境用APIクライアント初期化（URL手動設定）")
                    
                except Exception as e2:
                    print(f"警告: APIクライアント初期化エラー: {e1}, {e2}")
                    # 最終手段：通常の初期化
                    self.client = API(access_token=self.access_token)
                    logging.warning("通常のAPIクライアント初期化（ライブ環境URL設定失敗）")
            
            # デバッグ：設定確認
            print(f"  - アクセストークン: {self.access_token[:20]}...{self.access_token[-10:]}")
            
            # ライブ環境の場合、カスタムリクエストメソッドを追加
            self._setup_live_environment()
            
        else:
            # シミュレーション環境のエンドポイント
            self.base_url = "https://gateway.saxobank.com/sim/openapi"
            print("★ SaxoBot: シミュレーション環境で初期化されました")
            print(f"  - REST API: {self.base_url}")
            print(f"  - 認証: https://sim.logonvalidation.net")
            
            # シミュレーション環境（デフォルト）
            self.client = API(access_token=self.access_token)
            print(f"  - アクセストークン: {self.access_token[:20]}...{self.access_token[-10:]}")
    
    def _load_token_info(self):
        """保存されたトークン情報から有効期限を読み込む"""
        try:
            # OAuth認証で保存されたトークンファイルを読み込む
            token_file = "saxo_oauth_tokens.json"
            if os.path.exists(token_file):
                with open(token_file, 'r', encoding='utf-8') as f:
                    tokens_data = json.loads(f.read())
                    
                env_key = "live" if self.is_live else "sim"
                token_info = tokens_data.get(env_key, {})
                
                if token_info:
                    # 取得時刻と有効期限から実際の期限を計算
                    if 'obtained_at' in token_info:
                        obtained_at = datetime.fromisoformat(token_info.get('obtained_at'))
                        expires_in = token_info.get('expires_in', 1200)  # デフォルト20分
                        refresh_expires_in = token_info.get('refresh_token_expires_in', 3600)  # デフォルト1時間
                        
                        self.token_expires_at = obtained_at + timedelta(seconds=expires_in)
                        self.refresh_token_expires_at = obtained_at + timedelta(seconds=refresh_expires_in)
                    
                    # 明示的な有効期限が保存されている場合はそれを使用
                    if 'access_token_expires_at' in token_info:
                        self.token_expires_at = datetime.fromisoformat(token_info['access_token_expires_at'])
                    if 'refresh_token_expires_at' in token_info:
                        self.refresh_token_expires_at = datetime.fromisoformat(token_info['refresh_token_expires_at'])
                    
                    self.refresh_token = token_info.get('refresh_token')
                    
                    print(f"トークン情報を読み込みました:")
                    if self.token_expires_at:
                        print(f"  アクセストークン有効期限: {self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    if self.refresh_token_expires_at:
                        print(f"  リフレッシュトークン有効期限: {self.refresh_token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    
        except Exception as e:
            logging.warning(f"トークン情報の読み込みエラー: {e}")
    
    async def start_token_refresh_task(self):
        """バックグラウンドでトークンを自動リフレッシュするタスクを開始"""
        if self._token_refresh_task is None or self._token_refresh_task.done():
            self._token_refresh_task = asyncio.create_task(self._auto_refresh_token_loop())
            print("✓ トークン自動リフレッシュタスクを開始しました")
            logging.info("トークン自動リフレッシュタスクを開始")
    
    async def stop_token_refresh_task(self):
        """トークン自動リフレッシュタスクを停止"""
        if self._token_refresh_task and not self._token_refresh_task.done():
            self._token_refresh_task.cancel()
            try:
                await self._token_refresh_task
            except asyncio.CancelledError:
                pass
            print("トークン自動リフレッシュタスクを停止しました")
            logging.info("トークン自動リフレッシュタスクを停止")
    
    async def _auto_refresh_token_loop(self):
        """トークンを自動的にリフレッシュするループ"""
        while True:
            try:
                # 次のチェックまでの待機時間を計算
                if self.token_expires_at:
                    now = datetime.now()
                    # トークン期限の5分前にリフレッシュ
                    refresh_time = self.token_expires_at - timedelta(minutes=5)
                    wait_seconds = (refresh_time - now).total_seconds()
                    
                    # 残り時間を表示
                    remaining_minutes = (self.token_expires_at - now).total_seconds() / 60
                    logging.info(f"トークン残り有効時間: {remaining_minutes:.1f}分")
                    
                    if wait_seconds <= 0:
                        # すでにリフレッシュ時刻を過ぎている
                        print(f"\n⏰ トークンの有効期限が近づいています（残り{remaining_minutes:.1f}分）")
                        await self._refresh_token_if_needed()
                        wait_seconds = 60  # 次回チェックまで1分待機
                    else:
                        # 最大10分待機（長時間待機を避ける）
                        wait_seconds = min(wait_seconds, 600)
                        print(f"次回トークンチェックまで {wait_seconds/60:.1f} 分待機")
                    
                    await asyncio.sleep(wait_seconds)
                else:
                    # トークン期限が不明な場合は5分ごとにチェック
                    await asyncio.sleep(300)
                    
            except asyncio.CancelledError:
                logging.info("トークン自動リフレッシュタスクがキャンセルされました")
                break
            except Exception as e:
                logging.error(f"トークン自動リフレッシュエラー: {e}")
                await asyncio.sleep(60)  # エラー時は1分後に再試行
    
    async def _refresh_token_if_needed(self):
        """必要に応じてトークンをリフレッシュ（改良版）"""
        try:
            now = datetime.now()
            
            # リフレッシュトークンの有効期限チェック
            if self.refresh_token_expires_at and now >= self.refresh_token_expires_at:
                print("⚠️ リフレッシュトークンの有効期限が切れています。新規認証が必要です。")
                
                # Discord通知
                if self.discord_key:
                    await SAXOlib.send_discord_message(
                        self.discord_key,
                        f"⚠️ {'ライブ' if self.is_live else 'シミュレーション'}環境のリフレッシュトークンが期限切れです。\n"
                        f"手動で新規認証を行ってください。")
                return False
            
            # アクセストークンの有効期限チェック（5分前にリフレッシュ）
            should_refresh = False
            if self.token_expires_at:
                remaining_minutes = (self.token_expires_at - now).total_seconds() / 60
                should_refresh = remaining_minutes <= 5
                print(f"アクセストークン残り時間: {remaining_minutes:.1f}分")
            else:
                # 有効期限が不明な場合は、最後のチェックから15分経過していたらリフレッシュ
                minutes_since_last_check = (now - self._last_refresh_check).total_seconds() / 60
                should_refresh = minutes_since_last_check >= 15
            
            if should_refresh:
                print("🔄 アクセストークンを自動リフレッシュします...")
                logging.info("アクセストークンの自動リフレッシュを開始")
                
                if USE_OAUTH and self.refresh_token:
                    # OAuth認証モジュールを使用してリフレッシュ
                    from saxo_token_oauth import SAXOOAuthClient
                    
                    client = SAXOOAuthClient()
                    await client.load_config()
                    
                    # リフレッシュトークンで更新
                    new_tokens = await client.refresh_access_token(self.refresh_token, self.is_live)
                    
                    if new_tokens:
                        # 新しいトークン情報を更新
                        self.access_token = new_tokens['access_token']
                        self.refresh_token = new_tokens.get('refresh_token', self.refresh_token)
                        
                        # 有効期限を更新
                        obtained_at = datetime.now()
                        expires_in = new_tokens.get('expires_in', 1200)
                        refresh_expires_in = new_tokens.get('refresh_token_expires_in', 3600)
                        
                        self.token_expires_at = obtained_at + timedelta(seconds=expires_in)
                        self.refresh_token_expires_at = obtained_at + timedelta(seconds=refresh_expires_in)
                        self._last_refresh_check = obtained_at
                        
                        # APIクライアントを再初期化
                        self._initialize_client()
                        
                        print(f"✅ トークンを自動リフレッシュしました")
                        print(f"  新しい有効期限: {self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
                        logging.info(f"トークン自動リフレッシュ成功。新しい有効期限: {self.token_expires_at}")
                        
                        # アカウント情報を再取得
                        if self.account_key:
                            await self.get_account_info()
                        
                        # Discord通知　1時間毎にくるので停止
                        #if self.discord_key:
                        #    await SAXOlib.send_discord_message(
                        #        self.discord_key,
                        #        f"✅ {'ライブ' if self.is_live else 'シミュレーション'}環境のトークンを自動リフレッシュしました\n"
                        #        f"有効期限: {self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
                        
                        return True
                    else:
                        print("❌ トークンのリフレッシュに失敗しました")
                        logging.error("トークンの自動リフレッシュに失敗")
                        
                        # 失敗時はrefresh_tokenメソッドを呼び出す（従来の処理）
                        return await self.refresh_token(self.discord_key)
                else:
                    print("リフレッシュトークンが利用できません。従来の方法で更新を試みます...")
                    return await self.refresh_token(self.discord_key)
                    
        except Exception as e:
            logging.error(f"トークンリフレッシュエラー: {e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            return False
    
    async def get_token_status(self):
        """現在のトークン状態を取得"""
        now = datetime.now()
        status = {
            "access_token_valid": True,
            "refresh_token_valid": True,
            "access_token_remaining": None,
            "refresh_token_remaining": None,
            "needs_refresh": False,
            "needs_reauth": False
        }
        
        if self.token_expires_at:
            remaining = (self.token_expires_at - now).total_seconds()
            status["access_token_remaining"] = remaining
            status["access_token_valid"] = remaining > 0
            status["needs_refresh"] = remaining < 300  # 5分未満
        
        if self.refresh_token_expires_at:
            remaining = (self.refresh_token_expires_at - now).total_seconds()
            status["refresh_token_remaining"] = remaining
            status["refresh_token_valid"] = remaining > 0
            status["needs_reauth"] = remaining <= 0
        
        return status
    
    async def refresh_token(self, discord_key=None):
        """トークンを再取得してAPIクライアントを再初期化"""
        try:
            print("\n=== トークンの自動更新を開始 ===")
            logging.info("トークンの自動更新を開始")
            
            self._token_refresh_count += 1
            if self._token_refresh_count > self._max_token_refresh:
                print(f"✗ トークン再取得の上限（{self._max_token_refresh}回）に達しました")
                logging.error("トークン再取得の上限に達しました")
                
                if discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key,
                        f"⚠️ トークン再取得の上限（{self._max_token_refresh}回）に達しました。手動でトークンを更新してください。")
                
                return False
            
            print(f"トークン再取得試行 {self._token_refresh_count}/{self._max_token_refresh}")
            
            # Discord通知
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key,
                    f"🔄 トークンの自動更新を開始します（{self._token_refresh_count}/{self._max_token_refresh}）")
            
            # OAuth認証またはレガシー認証でトークンを再取得
            if USE_OAUTH:
                print("OAuth認証でトークンを再取得中...")
                token_result = await get_oauth_token(self.is_live)
                
                if isinstance(token_result, tuple) and token_result[0]:
                    new_token = token_result[0]
                    # 環境が一致しているか確認
                    actual_is_live = token_result[1] if len(token_result) > 1 else self.is_live
                    
                    if actual_is_live != self.is_live:
                        print(f"⚠️ 警告: 取得したトークンの環境が異なります")
                        print(f"  期待: {'ライブ' if self.is_live else 'シミュレーション'}")
                        print(f"  実際: {'ライブ' if actual_is_live else 'シミュレーション'}")
                    
                    self.access_token = new_token
                    print("✓ 新しいトークンを取得しました")
                else:
                    print("✗ OAuth認証でのトークン取得に失敗しました")
                    return False
            else:
                print("従来の認証方法でトークンを再取得中...")
                from saxo_token_async import get_valid_token
                token_result = await get_valid_token(self.is_live)
                
                if isinstance(token_result, tuple) and token_result[0]:
                    self.access_token = token_result[0]
                    print("✓ 新しいトークンを取得しました")
                elif token_result:
                    self.access_token = token_result
                    print("✓ 新しいトークンを取得しました")
                else:
                    print("✗ トークンの取得に失敗しました")
                    return False
            
            # APIクライアントを再初期化
            print("APIクライアントを再初期化中...")
            self._initialize_client()
            
            # 新しいトークンでテスト
            if await self.test_connection():
                print("✓ トークンの更新が完了しました")
                logging.info("トークンの更新が完了しました")
                
                # Discord通知
                if discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key,
                        "✅ トークンの自動更新が完了しました。取引を継続します。")
                
                # アカウント情報を再取得
                if self.account_key:
                    print("アカウント情報を再取得中...")
                    await self.get_account_info()
                
                return True
            else:
                print("✗ 新しいトークンでの接続テストに失敗しました")
                
                if discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key,
                        "❌ トークンの自動更新に失敗しました。手動での対応が必要です。")
                
                return False
                
        except Exception as e:
            logging.error(f"トークン再取得エラー: {e}")
            print(f"✗ トークン再取得エラー: {e}")
            
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key,
                    f"❌ トークン再取得エラー: {str(e)}")
            
            return False
    
    async def _request_with_retry(self, request_func, *args, **kwargs):
        """認証エラー時に自動的にトークンを再取得してリトライ"""
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                # リクエストを実行
                result = await request_func(*args, **kwargs)
                return result
                
            except Exception as e:
                error_str = str(e)
                
                # 401エラーまたは認証エラーをチェック
                if ("401" in error_str or "Unauthorized" in error_str or 
                    "Invalid token" in error_str or "Token expired" in error_str):
                    
                    if attempt < max_retries - 1:
                        print(f"\n⚠️ 認証エラーを検出しました。トークンを自動更新します...")
                        logging.warning(f"認証エラー検出: {error_str}")
                        
                        # トークンを再取得（Discord通知付き）
                        if await self.refresh_token(self.discord_key):
                            print("トークン更新成功。リトライします...")
                            continue
                        else:
                            print("トークン更新失敗。処理を中断します。")
                            raise e
                    else:
                        print("リトライ上限に達しました。")
                        raise e
                else:
                    # 認証エラー以外はそのまま例外を投げる
                    raise e
        
        return None
        
    def _setup_live_environment(self):
        """ライブ環境用のカスタマイズを設定"""
        # 元のリクエストメソッドを保存
        if hasattr(self.client, 'request'):
            self._original_request = self.client.request
            
            # カスタムリクエストメソッドを定義
            def custom_request(endpoint):
                # エンドポイントのURLを確認・修正
                if hasattr(endpoint, '_expected_api_url'):
                    # シミュレーション環境のURLをライブ環境に置き換え
                    if '/sim/' in endpoint._expected_api_url:
                        endpoint._expected_api_url = endpoint._expected_api_url.replace('/sim/', '/')
                
                # ライブ環境の場合、エンドポイントURLを強制的に変更
                if hasattr(endpoint, 'expected_api_url'):
                    endpoint.expected_api_url = self.base_url
                
                # saxo-openapiの内部URLも変更を試みる
                if hasattr(endpoint, '_api_url'):
                    endpoint._api_url = self.base_url
                
                # 元のリクエストメソッドを呼び出し
                return self._original_request(endpoint)
            
            # リクエストメソッドを置き換え
            self.client.request = custom_request
            print("  - ライブ環境用カスタムリクエストメソッド設定完了")
        
    async def test_connection(self):
        """API接続のテスト（非同期版）"""
        try:
            loop = asyncio.get_event_loop()
            
            # まず手動でテスト（デバッグ用）
            print("\n=== API接続テスト（詳細） ===")
            import requests
            
            # テスト用URL
            test_url = f"{self.base_url}/port/v1/diagnostics/get"
            alt_test_url = f"{self.base_url}/port/v1/users/me"
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            print(f"テストURL 1: {test_url}")
            print(f"テストURL 2: {alt_test_url}")
            print(f"トークン（先頭20文字）: {self.access_token[:20]}...")
            print(f"環境: {'ライブ' if self.is_live else 'シミュレーション'}")
            
            # diagnostics/get を試す
            try:
                response = requests.get(test_url, headers=headers, timeout=10)
                print(f"Diagnostics レスポンス: {response.status_code}")
                
                if response.status_code == 401:
                    print("✗ 認証エラー（401）: トークンが無効です")
                    print("  - トークンの有効期限が切れている可能性があります")
                    print("  - または、環境（ライブ/シミュレーション）が一致していません")
                    
                    # レスポンスの詳細を表示
                    try:
                        error_detail = response.json()
                        print(f"  - エラー詳細: {error_detail}")
                    except:
                        print(f"  - エラーテキスト: {response.text}")
                        
            except Exception as e:
                print(f"Diagnostics エラー: {e}")
            
            # users/me を試す
            try:
                response = requests.get(alt_test_url, headers=headers, timeout=10)
                print(f"Users/Me レスポンス: {response.status_code}")
                
                if response.status_code == 200:
                    user_info = response.json()
                    print("✓ API接続成功")
                    print(f"  - ユーザーID: {user_info.get('UserId', 'N/A')}")
                    print(f"  - クライアントキー: {user_info.get('ClientKey', 'N/A')}")
                    return True
                elif response.status_code == 401:
                    print("✗ 認証エラー（401）")
                    return False
                    
            except Exception as e:
                print(f"Users/Me エラー: {e}")
            
            print("========================\n")
            
            # saxo-openapiライブラリを使用したテスト
            def sync_test():
                try:
                    r = rs.diagnostics.Get()
                    self.client.request(r)
                    return r.status_code
                except Exception as api_error:
                    # エラーの詳細を確認
                    if hasattr(api_error, 'response'):
                        return api_error.response.status_code
                    else:
                        raise api_error
            
            status_code = await loop.run_in_executor(self.executor, sync_test)
            
            if status_code == 200:
                logging.info("✓ API接続テスト成功")
                print("✓ API接続テスト成功（saxo-openapi）")
                return True
            else:
                logging.error(f"✗ API接続テスト失敗: ステータスコード {status_code}")
                print(f"✗ API接続テスト失敗: ステータスコード {status_code}")
                return False
                
        except Exception as e:
            logging.error(f"✗ API接続エラー: {e}")
            print(f"✗ API接続エラー: {e}")
            
            # エラーメッセージから401を検出
            if "401" in str(e) or "Unauthorized" in str(e):
                print("\n認証エラーの可能性が高いです:")
                print("1. トークンの有効期限を確認してください")
                print("2. ライブ/シミュレーション環境の設定が正しいか確認してください")
                print("3. 新しいトークンを取得してください")
                
            return False
    
    async def get_account_info(self):
        """アカウント情報を取得（非同期版・トークン自動更新対応）"""
        async def _get_account_info_impl():
            loop = asyncio.get_event_loop()
            
            # ユーザー情報を取得
            def sync_get_user():
                r = rs.user.User()
                return self.client.request(r)
            
            user_info = await loop.run_in_executor(self.executor, sync_get_user)
            if user_info:
                self.client_key = user_info.get('ClientKey')
            
            # アカウント情報を取得
            def sync_get_account():
                r = pf.accounts.AccountsMe()
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_get_account)
            
            if response and 'Data' in response and len(response['Data']) > 0:
                # 複数アカウントがある場合の処理
                if len(response['Data']) > 1:
                    print(f"\n複数のアカウントが見つかりました（{len(response['Data'])}個）:")
                    
                    fx_account = None
                    for idx, account in enumerate(response['Data']):
                        acc_id = account.get('AccountId', '')
                        acc_type = account.get('AccountType', '')
                        acc_sub_type = account.get('AccountSubType', '')
                        currency = account.get('Currency', '')
                        active = account.get('Active', False)
                        
                        print(f"  {idx+1}. {acc_id}")
                        print(f"     タイプ: {acc_type} / {acc_sub_type}")
                        print(f"     通貨: {currency}, アクティブ: {active}")
                        
                        # FX取引用アカウントを探す（アカウントIDに'/S'が含まれる、またはAccountSubTypeがCurrencyの場合）
                        if ('/S' in acc_id or acc_sub_type == 'Currency') and active:
                            fx_account = account
                            print(f"     → FX取引用アカウントとして選択")
                    
                    # FX用アカウントが見つかった場合はそれを使用
                    if fx_account:
                        account = fx_account
                    else:
                        # 見つからない場合は最初のアクティブなアカウントを使用
                        for acc in response['Data']:
                            if acc.get('Active', False):
                                account = acc
                                break
                        else:
                            account = response['Data'][0]  # どれもアクティブでない場合は最初のアカウント
                else:
                    account = response['Data'][0]
                
                self.account_key = account.get('AccountKey')
                self.account_info = account  # アカウント情報を保存
                
                # アカウント詳細情報を表示
                acc_id = account.get('AccountId', '')
                acc_type = account.get('AccountType', '')
                acc_sub_type = account.get('AccountSubType', '')
                currency = account.get('Currency', '')
                
                logging.info(f"アカウント情報取得成功: {acc_id}")
                print(f"\n✓ アカウント情報取得成功:")
                print(f"  ID: {acc_id}")
                print(f"  タイプ: {acc_type} / {acc_sub_type}")
                print(f"  基準通貨: {currency}")
                print(f"  AccountKey: {self.account_key[:20]}...")
                
                return account
            
            return None
        
        try:
            # 認証エラー時の自動リトライ付きで実行
            return await self._request_with_retry(_get_account_info_impl)
        except Exception as e:
            logging.error(f"アカウント情報取得エラー: {e}")
            print(f"✗ アカウント情報取得エラー: {e}")
            return None
    
    async def get_balance(self):
        """口座残高を取得（ライブ/シミュレーション環境対応版・トークン自動更新対応）"""
        async def _get_balance_impl():
            loop = asyncio.get_event_loop()
            
            # アカウント情報が取得できていない場合は先に取得
            if not self.account_key:
                await self.get_account_info()
            
            if not self.account_key:
                logging.error("アカウント情報が取得できません")
                # エラーでもライブ環境かどうかで処理を分ける
                if self.is_live:
                    print("✗ ライブ環境：アカウント情報が取得できないため、残高を確認できません")
                    return {
                        'CashBalance': 0,
                        'Currency': 'JPY',
                        'TotalValue': 0,
                        'Error': 'アカウント情報なし'
                    }
                else:
                    # シミュレーション環境のデフォルト値を返す
                    return {
                        'CashBalance': 1000000,
                        'Currency': 'JPY',
                        'TotalValue': 1000000
                    }
            
            # ライブ環境の場合は実際のAPIから残高を取得
            if self.is_live:
                print(f"ライブ環境の残高取得を開始... (AccountKey: {self.account_key})")
                logging.info(f"ライブ環境の残高取得開始 - AccountKey: {self.account_key}, ClientKey: {self.client_key}")
                
                # 方法1: saxo-openapiライブラリのAccountBalancesMeを最優先で使用
                try:
                    print("  方法1: saxo-openapi AccountBalancesMe()で残高取得...")
                    
                    def sync_get_balances_me():
                        # Balanceエンドポイントのインポート
                        from saxo_openapi.endpoints.portfolio import balances
                        r = balances.AccountBalancesMe()
                        response = self.client.request(r)
                        
                        # レスポンスが戻り値でない場合、r.responseを使用
                        if response is None and hasattr(r, 'response'):
                            response = r.response
                        
                        return response
                    
                    balances_response = await loop.run_in_executor(self.executor, sync_get_balances_me)
                    
                    if balances_response:
                        logging.info(f"AccountBalancesMe レスポンス: {json.dumps(balances_response, indent=2)}")
                        
                        # 単一アカウントの場合（直接フィールドがある）
                        if 'MarginAvailableForTrading' in balances_response:
                            # MarginAvailableForTradingを優先的に使用
                            margin_available = balances_response.get('MarginAvailableForTrading', 0)
                            cash_balance = balances_response.get('CashBalance', margin_available)
                            currency = balances_response.get('Currency', 'JPY')
                            total_value = balances_response.get('TotalValue', margin_available)
                            collateral = balances_response.get('CollateralAvailable', margin_available)
                            
                            print(f"✓ ライブ環境の残高（AccountBalancesMe）:")
                            print(f"  MarginAvailableForTrading: {margin_available:,.2f} {currency}")
                            print(f"  CashBalance: {cash_balance:,.2f}")
                            print(f"  TotalValue: {total_value:,.2f}")
                            print(f"  CollateralAvailable: {collateral:,.2f}")
                            
                            logging.info(f"ライブ環境の残高取得成功（AccountBalancesMe）: MarginAvailable={margin_available} {currency}")
                            
                            return {
                                'CashBalance': float(margin_available),  # MarginAvailableForTradingを使用
                                'Currency': currency,
                                'TotalValue': float(total_value),
                                'CollateralAvailable': float(collateral),
                                'MarginAvailableForTrading': float(margin_available)
                            }
                        
                        # 複数アカウントの場合（Dataフィールドがある）
                        elif 'Data' in balances_response:
                            print(f"  複数アカウント検出: {len(balances_response['Data'])}件")
                            
                            # FX用アカウント（S付き）を探す
                            for acc in balances_response['Data']:
                                acc_id = acc.get('AccountId', '')
                                acc_key = acc.get('AccountKey', '')
                                
                                # FX用アカウントかチェック
                                if acc_key == self.account_key or '/S' in acc_id:
                                    margin_available = acc.get('MarginAvailableForTrading', 0)
                                    cash_balance = acc.get('CashBalance', margin_available)
                                    currency = acc.get('Currency', 'JPY')
                                    total_value = acc.get('TotalValue', margin_available)
                                    collateral = acc.get('CollateralAvailable', margin_available)
                                    
                                    if margin_available != 0:
                                        print(f"✓ ライブ環境の残高（FXアカウント）:")
                                        print(f"  AccountId: {acc_id}")
                                        print(f"  MarginAvailableForTrading: {margin_available:,.2f} {currency}")
                                        print(f"  CashBalance: {cash_balance:,.2f}")
                                        print(f"  TotalValue: {total_value:,.2f}")
                                        
                                        return {
                                            'CashBalance': float(margin_available),  # MarginAvailableForTradingを使用
                                            'Currency': currency,
                                            'TotalValue': float(total_value),
                                            'CollateralAvailable': float(collateral),
                                            'MarginAvailableForTrading': float(margin_available)
                                        }
                
                except Exception as lib_error:
                    print(f"  ✗ AccountBalancesMeエラー: {lib_error}")
                    logging.error(f"AccountBalancesMeエラー: {lib_error}")
                    # 認証エラーの場合は例外を再発生させてリトライ機構に任せる
                    if "401" in str(lib_error) or "Unauthorized" in str(lib_error):
                        raise lib_error
                
                # すべて失敗した場合
                print("\n⚠️ ライブ環境の残高取得に失敗しました")
                print("⚠️ 実際の残高を確認できません。オートロット機能は正しく動作しません。")
                
                # ユーザー要望により、LIVE環境でも残高が0の場合は100万円を設定
                print("⚠️ 口座残高が0円のため、デフォルト値の100万円を使用します")
                return {
                    'CashBalance': 1000000,
                    'Currency': 'JPY',
                    'TotalValue': 1000000,
                    'Warning': 'ライブ環境の実際の残高を取得できないため、デフォルト値を使用'
                }
            
            # シミュレーション環境の場合
            else:
                print("シミュレーション環境：デフォルト残高を使用")
                
                # シミュレーション環境でもAccountBalancesMeを試す（オプション）
                try:
                    def sync_get_balances_me():
                        from saxo_openapi.endpoints.portfolio import balances
                        r = balances.AccountBalancesMe()
                        response = self.client.request(r)
                        if response is None and hasattr(r, 'response'):
                            response = r.response
                        return response
                    
                    balances_response = await loop.run_in_executor(self.executor, sync_get_balances_me)
                    
                    if balances_response and 'MarginAvailableForTrading' in balances_response:
                        margin_available = balances_response.get('MarginAvailableForTrading', 0)
                        cash_balance = balances_response.get('CashBalance', margin_available)
                        currency = balances_response.get('Currency', 'JPY')
                        total_value = balances_response.get('TotalValue', margin_available)
                        
                        print(f"シミュレーション環境の残高（API）:")
                        print(f"  MarginAvailableForTrading: {margin_available:,.2f} {currency}")
                        print(f"  CashBalance: {cash_balance:,.2f}")
                        
                        return {
                            'CashBalance': float(margin_available),  # MarginAvailableForTradingを使用
                            'Currency': currency,
                            'TotalValue': float(total_value),
                            'MarginAvailableForTrading': float(margin_available)
                        }
                except:
                    pass
                
                # シミュレーション環境のデフォルト残高
                default_balance = 1000000  # 100万円
                
                return {
                    'CashBalance': default_balance,
                    'Currency': 'JPY',
                    'TotalValue': default_balance
                }
        
        try:
            # 認証エラー時の自動リトライ付きで実行
            return await self._request_with_retry(_get_balance_impl)
        except Exception as e:
            logging.error(f"残高取得エラー: {e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            
            # エラー時の処理
            if self.is_live:
                # ライブ環境でも100万円のデフォルト値を使用
                print(f"✗ ライブ環境の残高取得で予期しないエラー: {e}")
                print("⚠️ 口座残高が取得できないため、デフォルト値の100万円を使用します")
                return {
                    'CashBalance': 1000000,
                    'Currency': 'JPY',
                    'TotalValue': 1000000,
                    'Warning': str(e)
                }
            else:
                # シミュレーション環境ではデフォルト値を返す
                print("シミュレーション環境：エラーのためデフォルト残高を使用")
                return {
                    'CashBalance': 1000000,
                    'Currency': 'JPY',
                    'TotalValue': 1000000
                }
    
    async def get_instrument_details(self, ticker):
        """
        通貨ペアの詳細情報を取得（UIC動的取得機能付き・トークン自動更新対応）
        
        Args:
            ticker (str): 通貨ペア（例: "USD_JPY"）
            
        Returns:
            dict: 商品情報（Uic, Symbol, Description等）
        """
        # キャッシュをチェック
        if ticker in self._uic_cache:
            logging.info(f"UICキャッシュヒット: {ticker} = {self._uic_cache[ticker]}")
            return self._uic_cache[ticker]
        
        async def _get_instrument_details_impl():
            loop = asyncio.get_event_loop()
            
            def sync_search():
                # FX用のキーワードを生成（USD_JPY → USDJPY）
                keywords = ticker.replace("_", "")
                
                # API呼び出しパラメータ
                params = {
                    "Keywords": keywords,
                    "AssetTypes": "FxSpot",  # FXスポットに限定
                    "IncludeNonTradable": False  # 取引可能な商品のみ
                }
                
                # より詳細な検索条件を追加
                r = rd.instruments.Instruments(params=params)
                response = self.client.request(r)
                
                # デバッグ用ログ
                logging.info(f"Instrument search for {keywords}: {json.dumps(response, indent=2)}")
                
                return response
            
            response = await loop.run_in_executor(self.executor, sync_search)
            
            if response and 'Data' in response and len(response['Data']) > 0:
                # 複数の結果がある場合は、最も適合するものを選択
                best_match = None
                for instrument in response['Data']:
                    symbol = instrument.get('Symbol', '')
                    # 完全一致を優先
                    if symbol == ticker.replace("_", ""):
                        best_match = instrument
                        break
                    # 部分一致も考慮
                    elif ticker.replace("_", "") in symbol and not best_match:
                        best_match = instrument
                
                if not best_match:
                    best_match = response['Data'][0]  # 最初の結果を使用
                
                result = {
                    'Uic': best_match.get('Identifier'),
                    'Symbol': best_match.get('Symbol'),
                    'Description': best_match.get('Description'),
                    'CurrencyCode': best_match.get('CurrencyCode'),
                    'AssetType': best_match.get('AssetType')
                }
                
                # キャッシュに保存
                self._uic_cache[ticker] = result
                
                logging.info(f"UIC resolved for {ticker}: {result['Uic']} ({result['Description']})")
                return result
            
            # 見つからない場合は、別の検索方法を試す
            logging.warning(f"通貨ペア {ticker} が見つかりません。別の検索を試みます。")
            
            # 通貨ペアを分解して検索（USD_JPY → USD/JPY）
            if "_" in ticker:
                base_currency = ticker.split("_")[0]
                quote_currency = ticker.split("_")[1]
                alt_keywords = f"{base_currency}/{quote_currency}"
                
                def sync_alt_search():
                    params = {
                        "Keywords": alt_keywords,
                        "AssetTypes": "FxSpot"
                    }
                    r = rd.instruments.Instruments(params=params)
                    return self.client.request(r)
                
                alt_response = await loop.run_in_executor(self.executor, sync_alt_search)
                
                if alt_response and 'Data' in alt_response and len(alt_response['Data']) > 0:
                    instrument = alt_response['Data'][0]
                    result = {
                        'Uic': instrument.get('Identifier'),
                        'Symbol': instrument.get('Symbol'),
                        'Description': instrument.get('Description'),
                        'CurrencyCode': instrument.get('CurrencyCode'),
                        'AssetType': instrument.get('AssetType')
                    }
                    self._uic_cache[ticker] = result
                    return result
            
            return None
        
        try:
            # 認証エラー時の自動リトライ付きで実行
            return await self._request_with_retry(_get_instrument_details_impl)
        except Exception as e:
            logging.error(f"商品検索エラー: {e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            return None
    
    async def get_price(self, ticker):
        """現在価格を取得（トークン自動更新対応）"""
        async def _get_price_impl():
            instrument_info = await self.get_instrument_details(ticker)
            if not instrument_info:
                return None
            
            loop = asyncio.get_event_loop()
            
            def sync_get_price():
                params = {
                    "Uic": instrument_info['Uic'],
                    "AssetType": "FxSpot"
                }
                # ライブ環境の場合、追加のパラメータが必要な場合がある
                if self.is_live:
                    params["FieldGroups"] = ["Quote", "PriceInfo", "PriceInfoDetails"]
                
                r = tr.infoprices.InfoPrice(params=params)
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_get_price)
            return response
        
        try:
            # 認証エラー時の自動リトライ付きで実行
            return await self._request_with_retry(_get_price_impl)
        except Exception as e:
            logging.error(f"価格取得エラー: {e}")
            return None
    
    async def place_market_order(self, ticker, direction, size):
        """成行注文を発注"""
        try:
            instrument_info = await self.get_instrument_details(ticker)
            if not instrument_info:
                logging.error(f"通貨ペア {ticker} が見つかりません")
                return None
            
            uic = instrument_info['Uic']
            
            # ライブ環境の場合は追加の確認
            if self.is_live:
                logging.info(f"ライブ環境の成行注文: ticker={ticker}, uic={uic}, size={size}, direction={direction}")
                print(f"ライブ環境の成行注文: ticker={ticker}, uic={uic}, size={size}, direction={direction}")
            
            # 注文データの構築
            order_data = {
                "Uic": uic,
                "AssetType": "FxSpot",
                "Amount": size,
                "BuySell": direction.capitalize(),  # "Buy" または "Sell"
                "OrderType": "Market",
                "AccountKey": self.account_key,
                "ManualOrder": True,  # SAXOプラットフォームで必須
                "OrderDuration": {
                    "DurationType": "DayOrder"  # 成行注文では必須
                }
            }
            
            # ライブ環境の場合、追加のフィールドが必要な可能性
            if self.is_live:
                # クライアントキーも追加（必要な場合）
                if self.client_key:
                    order_data["ClientKey"] = self.client_key
                # ExternalReference（オプション）
                import uuid
                order_data["ExternalReference"] = str(uuid.uuid4())[:20]
            
            logging.info(f"注文データ: {json.dumps(order_data, indent=2)}")
            
            loop = asyncio.get_event_loop()
            
            def sync_place_order():
                r = tr.orders.Order(data=order_data)
                # リクエスト送信前のデバッグ
                logging.info(f"API Request - Method: POST, Endpoint: {r.ENDPOINT}")
                
                try:
                    response = self.client.request(r)
                    # レスポンスが直接返されない場合の処理
                    if response is None and hasattr(r, 'response'):
                        response = r.response
                    return response
                except Exception as api_error:
                    logging.error(f"API呼び出しエラー: {api_error}")
                    logging.error(f"エラー詳細: {traceback.format_exc()}")
                    # エラーレスポンスを確認
                    if hasattr(r, 'response'):
                        logging.error(f"APIレスポンス: {r.response}")
                    raise api_error
            
            response = await loop.run_in_executor(self.executor, sync_place_order)
            
            # レスポンスの詳細ログ
            logging.info(f"注文レスポンス（生データ）: {response}")
            
            if response:
                # エラーチェック
                if isinstance(response, dict) and 'ErrorInfo' in response:
                    error_info = response['ErrorInfo']
                    logging.error(f"注文エラー情報: {error_info}")
                    print(f"注文エラー詳細: {error_info}")
                    return response  # エラー情報も含めて返す
                
                logging.info(f"成行注文発注成功: {response}")
                return response
            else:
                logging.error("APIレスポンスがありません")
                return None
            
        except Exception as e:
            logging.error(f"成行注文発注エラー: {e}")
            logging.error(f"エラー詳細: {traceback.format_exc()}")
            print(f"成行注文発注エラー: {e}")
            
            # エラー詳細を返す
            return {"ErrorInfo": {"ErrorCode": "INTERNAL_ERROR", "Message": str(e)}}
    
    async def place_stop_order(self, ticker, direction, size, stop_price):
        """逆指値注文を発注"""
        try:
            instrument_info = await self.get_instrument_details(ticker)
            if not instrument_info:
                return None
            
            uic = instrument_info['Uic']
            
            # 注文データの構築
            order_data = {
                "Uic": uic,
                "AssetType": "FxSpot",
                "Amount": size,
                "BuySell": direction.capitalize(),
                "OrderType": "Stop",
                "OrderPrice": stop_price,
                "AccountKey": self.account_key,
                "ManualOrder": True,  # SAXOプラットフォームで必須
                "OrderDuration": {
                    "DurationType": "GoodTillCancel"  # 逆指値注文ではGTCを使用
                }
            }
            
            loop = asyncio.get_event_loop()
            
            def sync_place_order():
                r = tr.orders.Order(data=order_data)
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_place_order)
            return response
            
        except Exception as e:
            logging.error(f"逆指値注文発注エラー: {e}")
            return None
    
    async def place_limit_order(self, ticker, direction, size, limit_price):
        """指値注文を発注（将来の実装用）"""
        try:
            instrument_info = await self.get_instrument_details(ticker)
            if not instrument_info:
                return None
            
            uic = instrument_info['Uic']
            
            # 注文データの構築
            order_data = {
                "Uic": uic,
                "AssetType": "FxSpot",
                "Amount": size,
                "BuySell": direction.capitalize(),
                "OrderType": "Limit",
                "OrderPrice": limit_price,
                "AccountKey": self.account_key,
                "ManualOrder": True,  # SAXOプラットフォームで必須
                "OrderDuration": {
                    "DurationType": "GoodTillCancel"  # 指値注文ではGTCを使用
                }
            }
            
            loop = asyncio.get_event_loop()
            
            def sync_place_order():
                r = tr.orders.Order(data=order_data)
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_place_order)
            return response
            
        except Exception as e:
            logging.error(f"指値注文発注エラー: {e}")
            return None
        
    async def get_positions(self, ticker=None):
        """ポジション情報を取得（部分約定対応版）"""
        try:
            loop = asyncio.get_event_loop()
            
            def sync_get_positions():
                params = {'ClientKey': self.client_key}
                # FieldGroupsは指定しない（全情報を取得するため）
                r = pf.positions.PositionsMe(params=params)
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_get_positions)
            
            if response and ticker and 'Data' in response:
                # 特定の通貨ペアのポジションのみ抽出
                filtered_positions = []
                
                # ティッカーを SAXO形式に変換（USD_JPY → USDJPY）
                saxo_ticker = ticker.replace("_", "")
                
                # 該当通貨ペアのUICを取得
                instrument_info = await self.get_instrument_details(ticker)
                expected_uic = instrument_info['Uic'] if instrument_info else None
                
                # 同じ注文IDから生成されたポジションをグループ化
                positions_by_order = {}
                
                for idx, pos in enumerate(response['Data']):
                    # ポジション情報の構造を詳細にチェック
                    pos_base = pos.get('PositionBase', {})
                    
                    # SourceOrderIdで関連ポジションをグループ化
                    source_order_id = pos_base.get('SourceOrderId', '')
                    
                    # 最初のポジションの構造をログ出力（デバッグ用）
                    if idx == 0 and len(filtered_positions) == 0:
                        logging.info(f"ポジション構造の詳細: {json.dumps(pos, indent=2)}")
                        # 時間関連のフィールドを探す
                        logging.info("時間関連フィールドの探索:")
                        for key in pos_base.keys():
                            if 'time' in key.lower() or 'date' in key.lower():
                                logging.info(f"  {key}: {pos_base.get(key)}")
                        # トップレベルでも探す
                        for key in pos.keys():
                            if 'time' in key.lower() or 'date' in key.lower():
                                logging.info(f"  (top) {key}: {pos.get(key)}")
                    
                    # NetPositionIdから通貨ペアを判定
                    net_position_id = pos.get('NetPositionId', '')
                    
                    # AssetTypeとUicから判定
                    asset_type = pos_base.get('AssetType', '')
                    uic = pos_base.get('Uic', '')
                    
                    # 通貨ペアの判定（複数の方法で試行）
                    matched = False
                    
                    # 1. NetPositionIdで判定（例: "EURJPY__FxSpot"）
                    if net_position_id and saxo_ticker in net_position_id:
                        matched = True
                        logging.info(f"NetPositionIdで一致: {net_position_id}")
                    
                    # 2. UICで判定（動的に取得したUICと比較）
                    if expected_uic and str(uic) == str(expected_uic):
                        matched = True
                        logging.info(f"UICで一致: {ticker} = Uic {uic}")
                    
                    # FxSpotタイプのポジションのみ対象
                    if asset_type == "FxSpot" and matched:
                        filtered_positions.append(pos)
                        
                        # 注文IDでグループ化
                        if source_order_id:
                            if source_order_id not in positions_by_order:
                                positions_by_order[source_order_id] = []
                            positions_by_order[source_order_id].append(pos)
                
                # 部分約定の情報をログ出力
                for order_id, positions in positions_by_order.items():
                    if len(positions) > 1:
                        total_amount = sum(abs(p['PositionBase']['Amount']) for p in positions)
                        logging.info(f"部分約定検出: OrderID={order_id}, ポジション数={len(positions)}, 合計数量={total_amount}")
                        for p in positions:
                            pb = p['PositionBase']
                            logging.info(f"  - PositionID={p['PositionId']}, Amount={pb['Amount']}, OpenPrice={pb['OpenPrice']}")
                        
                response['Data'] = filtered_positions
            
            return response
            
        except Exception as e:
            logging.error(f"ポジション取得エラー: {e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            return None
    
    async def get_orders(self, ticker=None):
        """未約定注文を取得（改善版）"""
        try:
            loop = asyncio.get_event_loop()
            
            def sync_get_orders():
                # AccountKeyも含めてパラメータを設定
                params = {
                    'AccountKey': self.account_key,  # AccountKeyを追加
                    'ClientKey': self.client_key,
                    'Status': 'Working'  # 未約定注文のみ
                }
                
                # 注文一覧を取得するエンドポイント
                r = tr.orders.Orders(params=params)
                response = self.client.request(r)
                
                # レスポンスが直接返されない場合の処理
                if response is None and hasattr(r, 'response'):
                    response = r.response
                
                return response
            
            response = await loop.run_in_executor(self.executor, sync_get_orders)
            
            # デバッグ：取得した全注文を表示
            if response and 'Data' in response:
                logging.info(f"取得した未約定注文数: {len(response['Data'])}")
                print(f"  取得した未約定注文数: {len(response['Data'])}")
                
                for idx, order in enumerate(response['Data']):
                    logging.info(f"  注文{idx+1}: OrderId={order.get('OrderId')}, "
                               f"Type={order.get('OrderType')}, "
                               f"Uic={order.get('Uic')}, "
                               f"Price={order.get('OrderPrice')}, "
                               f"Amount={order.get('Amount')}, "
                               f"BuySell={order.get('BuySell')}")
            
            if response and ticker and 'Data' in response:
                # 特定の通貨ペアの注文のみ抽出
                filtered_orders = []
                
                # 該当通貨ペアのUICを取得
                instrument_info = await self.get_instrument_details(ticker)
                expected_uic = instrument_info['Uic'] if instrument_info else None
                
                logging.info(f"フィルタリング: ticker={ticker}, expected_uic={expected_uic}")
                
                for order in response['Data']:
                    uic = order.get('Uic', '')
                    order_type = order.get('OrderType', '')
                    
                    # UICで判定（文字列として比較）
                    if expected_uic and str(uic) == str(expected_uic):
                        filtered_orders.append(order)
                        print(f"    → {ticker}の未約定注文: OrderId={order.get('OrderId')}, "
                              f"Type={order_type}, Price={order.get('OrderPrice')}")
                        logging.info(f"未約定注文検出: OrderId={order.get('OrderId')}, "
                                   f"Type={order_type}, Price={order.get('OrderPrice')}")
                
                response['Data'] = filtered_orders
                
                if len(filtered_orders) == 0:
                    print(f"  {ticker}の未約定注文はありません")
            elif not ticker and response and 'Data' in response:
                # tickerが指定されていない場合は全注文を返す
                print(f"  全アカウントの未約定注文: {len(response.get('Data', []))}件")
                for order in response.get('Data', []):
                    print(f"    - OrderId: {order.get('OrderId')}, "
                          f"Type: {order.get('OrderType')}, "
                          f"Uic: {order.get('Uic')}, "
                          f"Price: {order.get('OrderPrice')}")
            
            return response
            
        except Exception as e:
            logging.error(f"注文取得エラー: {e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            # エラーでも空のレスポンスを返す
            return {'Data': []}
    
    async def cancel_order(self, order_id):
        """注文をキャンセル（改善版）"""
        try:
            loop = asyncio.get_event_loop()
            
            logging.info(f"注文キャンセル開始: OrderId={order_id}")
            
            def sync_cancel_order():
                # キャンセルデータ（AccountKeyのみで十分な場合が多い）
                cancel_data = {
                    "AccountKey": self.account_key
                }
                
                # 注文キャンセルのエンドポイント
                # SAXOのAPIではDELETEメソッドでキャンセル
                from saxo_openapi.endpoints.trading import orders
                
                # 方法1: CancelOrderエンドポイントを使用
                try:
                    r = orders.CancelOrder(OrderId=order_id, params=cancel_data)
                    response = self.client.request(r)
                    
                    # レスポンスが直接返されない場合の処理
                    if response is None and hasattr(r, 'response'):
                        response = r.response
                    
                    return response
                except Exception as e1:
                    logging.error(f"CancelOrderエンドポイントエラー: {e1}")
                    
                    # 方法2: 手動でDELETEリクエストを送信
                    try:
                        # 手動でAPIリクエストを構築
                        import requests
                        url = f"{self.base_url}/trade/v2/orders/{order_id}"
                        headers = {
                            'Authorization': f'Bearer {self.access_token}',
                            'Accept': 'application/json',
                            'Content-Type': 'application/json'
                        }
                        response = requests.delete(url, headers=headers, params=cancel_data, timeout=30)
                        
                        if response.status_code in [200, 201, 202, 204]:
                            return True
                        else:
                            try:
                                return response.json()
                            except:
                                return None
                    except Exception as e2:
                        logging.error(f"手動DELETEリクエストエラー: {e2}")
                        raise e1  # 元のエラーを再発生
            
            response = await loop.run_in_executor(self.executor, sync_cancel_order)
            
            # レスポンスの処理
            if response is not None:
                # SAXOのキャンセル成功時は空のレスポンスまたは202/204ステータス
                if isinstance(response, dict) and 'ErrorInfo' in response:
                    # エラーの場合
                    error_info = response['ErrorInfo']
                    logging.error(f"注文キャンセルエラー: {error_info}")
                    return None
                else:
                    # 成功の場合（空のレスポンスまたは成功ステータス）
                    logging.info(f"注文キャンセル成功: OrderId={order_id}")
                    return True
            else:
                # レスポンスがない場合も成功とみなす（DELETEの場合）
                logging.info(f"注文キャンセル成功（レスポンスなし）: OrderId={order_id}")
                return True
                
        except Exception as e:
            logging.error(f"注文キャンセルエラー: OrderId={order_id}, Error={e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            return None
    
    async def preload_uic_cache(self, tickers):
        """
        よく使用する通貨ペアのUICを事前にキャッシュに読み込む
        
        Args:
            tickers (list): 通貨ペアのリスト
        """
        print("UICキャッシュを事前読み込み中...")
        for ticker in tickers:
            try:
                info = await self.get_instrument_details(ticker)
                if info:
                    print(f"  {ticker}: UIC {info['Uic']} - {info['Description']}")
            except Exception as e:
                logging.error(f"UICキャッシュ読み込みエラー ({ticker}): {e}")
    
    def manual_api_request(self, method, endpoint, data=None, params=None):
        """手動でAPIリクエストを送信（DELETE対応版）"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers, params=params, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            # レスポンスの処理
            if response.status_code in [200, 201, 202, 204]:
                # 204 No Contentの場合は空のレスポンス
                if response.status_code == 204:
                    return True
                    
                # JSONレスポンスがある場合
                try:
                    return response.json()
                except:
                    # JSONでない場合は成功とみなす
                    return True
            else:
                error_data = {
                    'status_code': response.status_code,
                    'error': response.text
                }
                
                # エラーレスポンスをJSONとして解析
                try:
                    error_json = response.json()
                    if 'ErrorInfo' in error_json:
                        return error_json  # ErrorInfoを含むレスポンスを返す
                except:
                    pass
                
                logging.error(f"API Error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logging.error(f"Manual API request error: {e}")
            return None
    
    async def check_trading_permissions(self):
        """取引可能な商品タイプを確認"""
        try:
            loop = asyncio.get_event_loop()
            
            print("\n=== 取引権限の確認 ===")
            
            # アカウントの取引可能商品を確認
            def sync_get_account_details():
                # アカウント詳細を取得
                r = pf.accounts.AccountDetails(AccountKey=self.account_key)
                return self.client.request(r)
            
            account_details = await loop.run_in_executor(self.executor, sync_get_account_details)
            
            if account_details:
                # 取引可能な商品タイプを表示
                legal_asset_types = account_details.get('LegalAssetTypes', [])
                print(f"取引可能な商品タイプ: {legal_asset_types}")
                
                # FxSpotが含まれているか確認
                if 'FxSpot' not in legal_asset_types:
                    print("⚠️ このアカウントはFXスポット取引に対応していません")
                    print("\n対処法:")
                    print("1. SAXO証券のサポートに連絡してFX取引を有効化")
                    print("2. 別のFX対応アカウントを使用")
                    return False
                else:
                    print("✓ FXスポット取引が可能です")
                    
                # アカウントタイプを表示
                account_type = self.account_info.get('AccountType', 'Unknown')
                account_sub_type = self.account_info.get('AccountSubType', 'Unknown')
                print(f"アカウントタイプ: {account_type} / {account_sub_type}")
                
                # 通貨情報
                currency = self.account_info.get('Currency', 'Unknown')
                print(f"基準通貨: {currency}")
                
                return True
                
        except Exception as e:
            logging.error(f"取引権限確認エラー: {e}")
            print(f"取引権限確認エラー: {e}")
            
            # エラーでも続行（警告のみ）
            print("\n⚠️ 取引権限の確認に失敗しました")
            print("取引を続行しますが、エラーが発生する可能性があります")
            return True
    
    async def get_allowed_instruments(self):
        """取引可能な通貨ペア一覧を取得"""
        try:
            loop = asyncio.get_event_loop()
            
            print("\n取引可能な通貨ペアを確認中...")
            
            def sync_search_instruments():
                # FXスポットで取引可能な商品を検索
                params = {
                    "AssetTypes": "FxSpot",
                    "IncludeNonTradable": False,
                    "AccountKey": self.account_key  # アカウント固有の商品を取得
                }
                r = rd.instruments.Instruments(params=params)
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_search_instruments)
            
            if response and 'Data' in response:
                instruments = response['Data']
                print(f"\n取引可能な通貨ペア数: {len(instruments)}")
                
                # 主要通貨ペアを表示
                major_pairs = ['USDJPY', 'EURUSD', 'GBPUSD', 'EURJPY', 'GBPJPY']
                print("\n主要通貨ペアの状態:")
                
                for pair in major_pairs:
                    found = False
                    for inst in instruments:
                        if inst.get('Symbol', '').upper() == pair:
                            found = True
                            uic = inst.get('Identifier')
                            print(f"  {pair}: ✓ 取引可能 (UIC: {uic})")
                            break
                    
                    if not found:
                        print(f"  {pair}: ✗ 取引不可")
                
                return instruments
            
            return []
            
        except Exception as e:
            logging.error(f"取引可能商品の確認エラー: {e}")
            print(f"取引可能商品の確認エラー: {e}")
            return []
                
    async def close_position(self, position_id, amount):
        """ポジションを決済（反対売買で実装）"""
        try:
            loop = asyncio.get_event_loop()
            
            # まず対象ポジションの情報を取得
            positions = await self.get_positions()
            target_position = None
            
            for pos in positions.get('Data', []):
                if pos.get('PositionId') == position_id:
                    target_position = pos
                    break
            
            if not target_position:
                logging.error(f"ポジションID {position_id} が見つかりません")
                return None
            
            pos_base = target_position.get('PositionBase', {})
            uic = pos_base.get('Uic')
            current_amount = pos_base.get('Amount', 0)
            
            # 反対方向を決定（買いポジションなら売り、売りポジションなら買い）
            if current_amount > 0:
                close_direction = "Sell"
            else:
                close_direction = "Buy"
            
            logging.info(f"ポジション決済: ID={position_id}, Amount={amount}, Direction={close_direction}")
            
            # 反対売買の成行注文データ
            close_order_data = {
                "Uic": uic,
                "AssetType": "FxSpot",
                "Amount": abs(amount),
                "BuySell": close_direction,
                "OrderType": "Market",
                "AccountKey": self.account_key,
                "ManualOrder": True,
                "OrderDuration": {
                    "DurationType": "DayOrder"
                },
                # RelatedPositionIdを指定することで、このポジションの決済であることを明示
                "RelatedPositionId": position_id
            }
            
            def sync_close_order():
                r = tr.orders.Order(data=close_order_data)
                return self.client.request(r)
            
            response = await loop.run_in_executor(self.executor, sync_close_order)
            
            if response and not response.get('ErrorInfo'):
                logging.info(f"決済注文成功: {response}")
                return response
            else:
                logging.error(f"決済注文失敗: {response}")
                return None
                
        except Exception as e:
            logging.error(f"ポジション決済エラー: {e}")
            logging.error(f"詳細: {traceback.format_exc()}")
            return None
    
    async def debug_api_request(self):
        """APIリクエストのデバッグ情報を表示"""
        print("\n=== API設定デバッグ情報 ===")
        print(f"環境: {'ライブ' if self.is_live else 'シミュレーション'}")
        print(f"ベースURL: {self.base_url}")
        print(f"アカウントキー: {self.account_key}")
        print(f"クライアントキー: {self.client_key}")
        
        # APIクライアントの内部設定を確認
        if hasattr(self.client, 'api_url'):
            print(f"client.api_url: {self.client.api_url}")
        if hasattr(self.client, '_api_url'):
            print(f"client._api_url: {self.client._api_url}")
        
        # 手動でAPIエンドポイントをテスト
        try:
            import requests
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
            
            # ユーザー情報エンドポイントをテスト
            test_url = f"{self.base_url}/port/v1/users/me"
            print(f"\nテストURL: {test_url}")
            
            response = requests.get(test_url, headers=headers, timeout=10)
            print(f"ステータスコード: {response.status_code}")
            
            if response.status_code == 200:
                print("✓ API接続成功")
            else:
                print(f"✗ APIエラー: {response.text}")
                
        except Exception as e:
            print(f"✗ テストエラー: {e}")
        
        print("========================\n")
    
    async def place_market_order_debug(self, ticker, direction, size):
        """成行注文を発注（デバッグ版）"""
        # まずAPI設定をデバッグ
        await self.debug_api_request()
        
        # 通常の注文処理を実行
        return await self.place_market_order(ticker, direction, size)
    
    async def get_closed_positions(self, since_time=None):
        """
        決済済みポジションを取得
        
        Args:
            since_time (datetime): この時刻以降の決済を取得（オプション）
            
        Returns:
            dict: 決済済みポジション情報
        """
        try:
            loop = asyncio.get_event_loop()
            
            def sync_get_closed_positions():
                params = {
                    'ClientKey': self.client_key,
                    # より多くのフィールドを取得するように修正
                    'FieldGroups': [
                        'ClosedPosition', 
                        'ClosedPositionDetails', 
                        'DisplayAndFormat',
                        'ExchangeInfo'  # 追加：約定価格情報を含む可能性
                    ]
                }
                
                # 時刻指定がある場合
                if since_time:
                    params['FromDateTime'] = since_time.strftime('%Y-%m-%dT%H:%M:%S')
                
                # ClosedPositionsエンドポイントを使用
                from saxo_openapi.endpoints.portfolio import closedpositions
                r = closedpositions.ClosedPositionsMe(params=params)
                response = self.client.request(r)
                
                if response is None and hasattr(r, 'response'):
                    response = r.response
                
                # デバッグ用：最初の決済ポジションの構造を確認
                if response and 'Data' in response and len(response['Data']) > 0:
                    logging.info(f"決済ポジション数: {len(response['Data'])}")
                    
                    # 全ての決済ポジションの内容を確認（デバッグ用）
                    for idx, pos in enumerate(response['Data']):
                        logging.info(f"決済ポジション[{idx}] 全体構造:")
                        logging.info(f"  トップレベルキー: {list(pos.keys())}")
                        
                        # ClosedPositionフィールドがある場合
                        if 'ClosedPosition' in pos:
                            closed_pos = pos['ClosedPosition']
                            logging.info(f"  ClosedPositionキー: {list(closed_pos.keys())}")
                            logging.info(f"  Uic: {closed_pos.get('Uic')}")
                            logging.info(f"  Amount: {closed_pos.get('Amount')}")
                            logging.info(f"  AssetType: {closed_pos.get('AssetType')}")
                            logging.info(f"  OpenPrice: {closed_pos.get('OpenPrice')}")
                            logging.info(f"  ClosingPrice: {closed_pos.get('ClosingPrice')}")
                            logging.info(f"  ExecutionTimeClose: {closed_pos.get('ExecutionTimeClose')}")
                            logging.info(f"  ClosedProfitLossInBaseCurrency: {closed_pos.get('ClosedProfitLossInBaseCurrency')}")
                            
                            # OpeningPositionIdとClosingPositionIdを探す
                            logging.info(f"  OpeningPositionId: {closed_pos.get('OpeningPositionId', 'フィールドなし')}")
                            logging.info(f"  ClosingPositionId: {closed_pos.get('ClosingPositionId', 'フィールドなし')}")
                            
                            # SourceOrderIdを探す
                            logging.info(f"  SourceOrderId: {closed_pos.get('SourceOrderId', 'フィールドなし')}")
                            
                            # その他のIDフィールドを探す
                            for key in closed_pos.keys():
                                if 'id' in key.lower() or 'position' in key.lower() or 'order' in key.lower():
                                    logging.info(f"  {key}: {closed_pos.get(key)}")
                        
                        # NetPositionIdやClosedPositionUniqueIdなど他のフィールドも確認
                        if 'NetPositionId' in pos:
                            logging.info(f"  NetPositionId: {pos['NetPositionId']}")
                        if 'ClosedPositionUniqueId' in pos:
                            logging.info(f"  ClosedPositionUniqueId: {pos['ClosedPositionUniqueId']}")
                        
                        # 最初の3件だけ詳細表示
                        if idx >= 2:
                            break
                    
                return response
            
            response = await loop.run_in_executor(self.executor, sync_get_closed_positions)
            return response
            
        except Exception as e:
            logging.error(f"決済済みポジション取得エラー: {e}")
            return None
    
    async def get_recent_closed_position(self, ticker, order_id=None, position_id=None):
        """
        最新の決済済みポジションを取得（特定の通貨ペア）
        
        Args:
            ticker (str): 通貨ペア
            order_id (str): 元の注文ID（オプション）
            position_id (str): ポジションID（オプション）
            
        Returns:
            dict: 決済情報
        """
        logging.info(f"get_recent_closed_position開始: ticker={ticker}, order_id={order_id}, position_id={position_id}")
        
        try:
            # 最初は過去1時間、取得できない場合は過去3時間まで拡大
            time_ranges = [
                timedelta(hours=1),
                timedelta(hours=3),
                timedelta(hours=6)
            ]
            
            for time_delta in time_ranges:
                since_time = datetime.now() - time_delta
                logging.info(f"決済履歴を検索: 過去{time_delta.total_seconds()/3600:.0f}時間")
                
                closed_positions = await self.get_closed_positions(since_time)
                
                if not closed_positions:
                    logging.warning("決済ポジションのレスポンスがありません")
                    continue
                    
                if 'Data' not in closed_positions:
                    logging.warning(f"決済ポジションにDataフィールドがありません: {closed_positions.keys()}")
                    continue
                    
                if len(closed_positions['Data']) == 0:
                    logging.warning("決済ポジションが0件です")
                    continue
                
                # データが見つかったらブレーク
                if len(closed_positions['Data']) > 0:
                    break
            else:
                # すべての時間範囲で見つからなかった
                logging.warning("どの時間範囲でも決済ポジションが見つかりませんでした")
                return None
            
            # 該当通貨ペアのUICを取得
            instrument_info = await self.get_instrument_details(ticker)
            expected_uic = instrument_info['Uic'] if instrument_info else None
            
            logging.info(f"決済ポジション検索: ticker={ticker}, expected_uic={expected_uic}, order_id={order_id}, position_id={position_id}")
            logging.info(f"決済ポジション数: {len(closed_positions['Data'])}")
            
            # 最新の該当ポジションを探す
            for idx, pos in enumerate(closed_positions['Data']):
                # SAXO APIの決済ポジションは構造が異なる
                # ClosedPositionフィールドの中にデータがある
                if 'ClosedPosition' in pos:
                    closed_pos = pos['ClosedPosition']
                    pos_uic = closed_pos.get('Uic')
                    pos_order_id = closed_pos.get('OpeningPositionId')
                    pos_closing_id = closed_pos.get('ClosingPositionId')
                else:
                    # 念のため直下も確認（旧形式対応）
                    closed_pos = pos
                    pos_uic = pos.get('Uic')
                    pos_order_id = pos.get('OpeningPositionId')
                    pos_closing_id = pos.get('ClosingPositionId')
                
                logging.info(f"決済ポジション{idx}: Uic={pos_uic}, OpeningPositionId={pos_order_id}, ClosingPositionId={pos_closing_id}")
                
                # UICで判定
                if expected_uic and str(pos_uic) == str(expected_uic):
                    # さらに詳細な条件でフィルタリング
                    matched = False
                    
                    # PositionIDでのマッチング（複数のフィールドを確認）
                    if position_id:
                        # OpeningPositionIdで確認
                        if str(closed_pos.get('OpeningPositionId', '')) == str(position_id):
                            matched = True
                            logging.info(f"OpeningPositionIDで一致: {position_id}")
                        # ClosingPositionIdで確認
                        elif str(closed_pos.get('ClosingPositionId', '')) == str(position_id):
                            matched = True
                            logging.info(f"ClosingPositionIDで一致: {position_id}")
                        # ClosedPositionUniqueIdで確認（SAXO固有のID）
                        elif 'ClosedPositionUniqueId' in pos and str(pos.get('ClosedPositionUniqueId', '')) == str(position_id):
                            matched = True
                            logging.info(f"ClosedPositionUniqueIDで一致: {position_id}")
                        # ClosedPositionの中のIDフィールドをすべて確認
                        else:
                            for key in closed_pos.keys():
                                if ('id' in key.lower() or 'position' in key.lower()) and str(closed_pos.get(key, '')) == str(position_id):
                                    matched = True
                                    logging.info(f"{key}で一致: {position_id}")
                                    break
                    # OrderIDでのマッチング（SourceOrderIdとOpeningPositionIdを確認）
                    if not matched and order_id:
                        # SAXOのAPIではSourceOrderIdがOpeningPositionIdに対応することがある
                        if str(closed_pos.get('OpeningPositionId', '')) == str(order_id):
                            matched = True
                            logging.info(f"OrderID(OpeningPositionId)で一致: {order_id}")
                        elif 'SourceOrderId' in closed_pos and str(closed_pos.get('SourceOrderId', '')) == str(order_id):
                            matched = True
                            logging.info(f"SourceOrderIDで一致: {order_id}")
                    
                    # 条件指定がない場合は最新のものを使用
                    if not matched and not position_id and not order_id:
                        matched = True
                        logging.info("条件指定なし、最新の決済を使用")
                    
                    if matched:
                        # ClosedPositionの構造を修正
                        result = {
                            'ClosedPosition': closed_pos,  # closed_posを使用
                            'ClosedPositionId': closed_pos.get('ClosingPositionId'),
                            'ProfitLoss': closed_pos.get('ClosedProfitLoss', 0),
                            'ProfitLossInBaseCurrency': closed_pos.get('ClosedProfitLossInBaseCurrency', 0)
                        }
                        
                        # ExecutionPriceフィールドを設定（ClosingPriceから）
                        if 'ClosingPrice' in closed_pos:
                            closed_pos['ExecutionPrice'] = closed_pos['ClosingPrice']
                        
                        logging.info(f"決済ポジション詳細: ClosingPrice={closed_pos.get('ClosingPrice')}, ProfitLoss={result['ProfitLossInBaseCurrency']}")
                        
                        return result
            
            logging.warning(f"該当する決済ポジションが見つかりません: ticker={ticker}, uic={expected_uic}")
            return None
            
        except Exception as e:
            logging.error(f"最新決済ポジション取得エラー: {e}")
            import traceback
            logging.error(f"詳細: {traceback.format_exc()}")
            return None


# 設定ファイルから情報を読み込む関数
def load_settings():
    """
    設定ファイルからボット設定を読み込む
    
    Returns:
        dict: 設定情報
    """
    if not os.path.exists(SETTINGS_FILE):
        print(f"エラー: 設定ファイル {SETTINGS_FILE} が見つかりません")
        print("setup_saxo.pyを実行して設定を行ってください")
        sys.exit(1)
    
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        print(f"✓ 設定ファイル {SETTINGS_FILE} を読み込みました")
        return settings
    except Exception as e:
        print(f"設定ファイル読み込みエラー: {e}")
        sys.exit(1)

async def process_entrypoint(entrypoint, config, bot, trade_results):
    """各エントリーポイントを処理する（GMOcoinbot2.py互換）"""
    # 逆指値注文のOrderIDを記録する変数を追加
    sl_order_id = None
    # 元の注文IDとポジションIDも記録
    main_order_id = None
    main_position_id = None
    main_order_price = None
    main_volume = None
    
    try:
        # エントリー時刻10秒前まで待機（時刻が過ぎている場合はスキップ）
        try:
            await SAXOlib.wait_until(entrypoint["entry_time"], 10, raise_exception=False)
        except ValueError as e:
            print(f"⚠️ エントリー時刻を超過しています: {entrypoint['entry_time'].strftime('%H:%M:%S')} - {str(e)}")
            logging.warning(f"エントリー時刻超過: {entrypoint['entry_time'].strftime('%H:%M:%S')} - {str(e)}")
            return  # このエントリーポイントをスキップ
        
        print(f"** エントリー開始: {entrypoint['entry_time'].strftime('%H:%M:%S')}-{entrypoint['exit_time'].strftime('%H:%M:%S')}({entrypoint['ticker']} {entrypoint['direction']} size{entrypoint['amount']} 指値{entrypoint['LimitRate']} 逆指値{entrypoint['StopRate']} {entrypoint['memo']})")
        logging.info(f"** EntryPoint: {entrypoint['entry_time'].strftime('%H:%M:%S')}-{entrypoint['exit_time'].strftime('%H:%M:%S')}({entrypoint['ticker']} {entrypoint['direction']} size{entrypoint['amount']} 指値{entrypoint['LimitRate']} 逆指値{entrypoint['StopRate']} {entrypoint['memo']})")
        
        # エントリー前の既存ポジションチェック
        try:
            positions = await bot.get_positions(entrypoint['ticker'])
            if positions and positions.get('Data'):
                position_count = len(positions['Data'])
                if position_count > 0:
                    logging.warning(f"{entrypoint['ticker']}のポジションが既に{position_count}個存在します")
                    print(f"警告: {entrypoint['ticker']}のポジションが既に{position_count}個存在します")
                    
                    # 部分約定の可能性をチェック
                    total_amount = sum(abs(p['PositionBase']['Amount']) for p in positions['Data'])
                    print(f"  合計数量: {total_amount}")
        except Exception as e:
            logging.error(f"ポジションチェックエラー: {e}")
        
        # Discord Webhook URLを取得
        discord_key = config.get("notification", {}).get("discord_webhook_url", "")
        
        # トレンド情報取得（SAXOではUSDJPYのトレンドで判断）
        trend_direction, trend_info = await SAXOlib.trend_get("USD_JPY")
        if trend_direction == 1:
            if entrypoint['direction'].upper() == 'BUY':
                trend_message = f"{entrypoint['ticker']}は上昇トレンドをフォロー ({trend_info})"
                if discord_key:
                    await SAXOlib.send_discord_message(discord_key, trend_message)
                print("上昇トレンドフォロー")
            else:
                trend_message = f"{entrypoint['ticker']}は上昇トレンドと逆行 ({trend_info})"
                if discord_key:
                    await SAXOlib.send_discord_message(discord_key, trend_message)
                print("上昇トレンド逆行")
        elif trend_direction == -1:
            if entrypoint['direction'].upper() == 'SELL':
                trend_message = f"{entrypoint['ticker']}は下降トレンドをフォロー ({trend_info})"
                if discord_key:
                    await SAXOlib.send_discord_message(discord_key, trend_message)
                print("下降トレンドフォロー")
            else:
                trend_message = f"{entrypoint['ticker']}は下降トレンドと逆行 ({trend_info})"
                if discord_key:
                    await SAXOlib.send_discord_message(discord_key, trend_message)
                print("下降トレンド逆行")
        else:
            trend_message = f"{entrypoint['ticker']}はレンジ ({trend_info})"
            if discord_key:
                await SAXOlib.send_discord_message(discord_key, trend_message)
            print("レンジ")
        
        # トレンド情報をメモに追加
        if 'memo' in entrypoint:
            entrypoint['memo'] = f"{entrypoint['memo']} | {trend_message}"
        else:
            entrypoint['memo'] = trend_message
        
        # 現在価格を取得（この時点でUICも取得される）
        price_info = await bot.get_price(entrypoint['ticker'])
        if not price_info:
            print(f"{entrypoint['ticker']}の価格情報が取得できませんでした。注文処理終了")
            
            # UICが取得できなかった可能性があるため、詳細を確認
            instrument_info = await bot.get_instrument_details(entrypoint['ticker'])
            if not instrument_info:
                print(f"  → 通貨ペア情報が見つかりません。シンボルを確認してください。")
            else:
                print(f"  → UIC: {instrument_info['Uic']}, Symbol: {instrument_info['Symbol']}")
            
            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, f"{entrypoint['ticker']}の価格情報が取得できませんでした。注文処理終了")
            return
        
        quote = price_info.get('Quote', {})
        bid = quote.get('Bid')
        ask = quote.get('Ask')
        
        # 資産残高取得
        balance_info = await bot.get_balance()
        balance = balance_info.get('CashBalance', 1000000)  # デフォルト100万円
        margin_available = balance_info.get('MarginAvailableForTrading', balance)
        
        # 残高取得エラーまたは0の場合の警告
        if balance_info.get('Error') or balance_info.get('Warning'):
            print(f"⚠️ 残高取得に問題があります: {balance_info.get('Error', balance_info.get('Warning'))}")
            if config['autolot'].upper() == 'TRUE':
                print("⚠️ オートロット機能が正しく動作しない可能性があります")
                if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key, 
                        f"⚠️ 残高取得エラー。オートロット計算が正確でない可能性があります。")
        
        if balance == 0 and config['autolot'].upper() == 'TRUE':
            print("⚠️ 残高が0円です。オートロット計算ができません。")
            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, 
                    f"⚠️ 残高が0円のため、オートロット計算ができません。")
            # 固定ロットを使用
            print(f"  → 固定ロット {entrypoint['amount']} を使用します")
            volume = entrypoint['amount']
        else:
            print(f"取引可能残高: {balance:,.2f} (MarginAvailable: {margin_available:,.2f})")
        
        # 自動ロット計算
        volume = entrypoint['amount']
        if config['autolot'].upper() == 'TRUE' and balance > 0:
            # SAXO証券ではUICによって通貨ペアを判定
            if entrypoint['ticker'][-3:] == "USD":
                # USD建ての通貨ペア
                usdjpy_price = await bot.get_price("USDJPY")
                if usdjpy_price:
                    usdjpy_quote = usdjpy_price.get('Quote', {})
                    if entrypoint['direction'].upper() == "BUY":
                        # 通貨単位で計算
                        raw_volume = int((balance * float(config['leverage'])) / (ask * usdjpy_quote.get('Ask', 100)))
                        # ロット単位に変換（1ロット = 100,000通貨単位）
                        lot_size = raw_volume / 100000
                        # 小数点第2位までで四捨五入
                        lot_size = round(lot_size, 2)
                        # 最小ロットサイズを0.01ロット（1,000通貨単位）とする
                        if lot_size < 0.01:
                            lot_size = 0.01
                        # 通貨単位に戻す
                        volume = int(lot_size * 100000)
                        print(f"USD建て自動ロット: {lot_size}ロット ({volume}通貨単位)")
                    else:
                        # 通貨単位で計算
                        raw_volume = int((balance * float(config['leverage'])) / (bid * usdjpy_quote.get('Bid', 100)))
                        # ロット単位に変換
                        lot_size = raw_volume / 100000
                        # 小数点第2位までで四捨五入
                        lot_size = round(lot_size, 2)
                        # 最小ロットサイズを0.01ロット（1,000通貨単位）とする
                        if lot_size < 0.01:
                            lot_size = 0.01
                        # 通貨単位に戻す
                        volume = int(lot_size * 100000)
                        print(f"USD建て自動ロット: {lot_size}ロット ({volume}通貨単位)")
            else:
                # JPY建ての通貨ペア
                if entrypoint['direction'].upper() == "BUY":
                    # 通貨単位で計算
                    raw_volume = int((balance * float(config['leverage'])) / ask)
                    # ロット単位に変換
                    lot_size = raw_volume / 100000
                    # 小数点第2位までで四捨五入
                    lot_size = round(lot_size, 2)
                    # 最小ロットサイズを0.01ロット（1,000通貨単位）とする
                    if lot_size < 0.01:
                        lot_size = 0.01
                    # 通貨単位に戻す
                    volume = int(lot_size * 100000)
                    print(f"JPY建て自動ロット: {lot_size}ロット ({volume}通貨単位)")
                else:
                    # 通貨単位で計算
                    raw_volume = int((balance * float(config['leverage'])) / bid)
                    # ロット単位に変換
                    lot_size = raw_volume / 100000
                    # 小数点第2位までで四捨五入
                    lot_size = round(lot_size, 2)
                    # 最小ロットサイズを0.01ロット（1,000通貨単位）とする
                    if lot_size < 0.01:
                        lot_size = 0.01
                    # 通貨単位に戻す
                    volume = int(lot_size * 100000)
                    print(f"JPY建て自動ロット: {lot_size}ロット ({volume}通貨単位)")
            
            # ロット数が0または異常に小さい場合の警告
            if volume < 1000:
                print(f"⚠️ 計算されたロット数が小さすぎます: {volume}")
                print(f"  → 最小ロット 1000 (0.01ロット) を使用します")
                volume = 1000
        
        # 実際に使用するvolume値を記録
        main_volume = volume if config['autolot'].upper() == 'TRUE' else entrypoint['amount']
        
        # スプレッド計算
        if bid and ask:
            # pips計算のための倍率
            if entrypoint['ticker'][-3:] != "JPY":
                multiply = 10000
            else:
                multiply = 100
                
            spread = round((abs(float(bid) - float(ask)) * multiply), 3)
            print(f"{entrypoint['ticker']} - Bid: {bid}, Ask: {ask} Spread: {spread}")
            
            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, f"{entrypoint['ticker']} - Bid: {bid}, Ask: {ask} Spread: {spread}")
            
            # スプレッドチェック
            splimit = 5  # 注文しないスプレッドをpipsで設定
            if splimit > 0 and spread >= splimit:
                print(f"スプレッドが{splimit}以上なので注文見送り")
                if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key, f"スプレッドが{splimit}以上なので注文見送り")
                return
        
        # エントリー時刻まで待機
        await SAXOlib.wait_until(entrypoint["entry_time"])
        
        # 成行注文
        print(f"\n注文送信中... 数量: {main_volume}")
        order_result = await bot.place_market_order(
            entrypoint['ticker'],
            entrypoint['direction'],
            main_volume
        )
        
        # 注文結果の詳細ログ
        logging.info(f"注文結果: {order_result}")
        
        # エラーチェックの改善
        if not order_result:
            print("注文エラー: レスポンスなし")
            print("詳細はログファイルを確認してください")
            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, "注文エラー: レスポンスなし\n詳細はログを確認してください")
            return
        
        # ErrorInfoがある場合のエラー処理
        if isinstance(order_result, dict) and 'ErrorInfo' in order_result:
            error_info = order_result['ErrorInfo']
            error_code = error_info.get('ErrorCode', 'Unknown')
            error_msg = error_info.get('Message', 'Unknown error')
            
            print(f"注文エラー: {error_code} - {error_msg}")
            
            # よくあるエラーの説明を追加
            if error_code == "InsufficientMargin":
                print("  → 証拠金不足です。注文数量を減らしてください。")
            elif error_code == "InvalidOrderSize":
                print(f"  → 無効な注文数量です。最小単位を確認してください。")
            elif error_code == "MarketClosed":
                print("  → マーケットがクローズしています。")
            elif error_code == "InvalidAccountKey":
                print("  → アカウントキーが無効です。認証を確認してください。")
            elif error_code == "InstrumentNotAllowed":
                print("  → このアカウントではFX取引が許可されていません。")
                print("  → 解決方法:")
                print("    1. SAXO証券のアカウント設定でFX取引を有効化")
                print("    2. FX取引が可能な別のアカウントを使用")
                print("    3. アカウントタイプがFX取引に対応しているか確認")
                
                # ライブ環境の場合は追加の確認
                if bot.is_live:
                    print("\n  → 取引権限を再確認します...")
                    await bot.check_trading_permissions()
                    
            elif error_code == "INTERNAL_ERROR":
                print("  → 内部エラーが発生しました。API接続を確認してください。")
            
            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, f"注文エラー: {error_code}\n{error_msg}")
            return
        
        # OrderIDを取得して表示
        main_order_id = order_result.get('OrderId')
        print(f"注文OK - OrderID: {main_order_id}")
        
        # ポジション確認の待機時間を延長
        print("約定待機中...")
        await asyncio.sleep(5)  # 2秒から5秒に延長
        
        # ポジション確認を複数回試行
        positions = None
        for retry in range(3):  # 最大3回試行
            positions = await bot.get_positions(entrypoint['ticker'])
            
            if positions:
                logging.info(f"ポジション取得結果 (試行{retry+1}): {positions}")
                
            if positions and positions.get('Data') and len(positions['Data']) > 0:
                break
                
            if retry < 2:  # 最後の試行でなければ待機
                print(f"ポジション確認中... (試行{retry+1}/3)")
                await asyncio.sleep(3)
        
        if not positions or not positions.get('Data'):
            # ポジションが見つからない場合、全ポジションを確認
            print("特定通貨ペアのポジションが見つかりません。全ポジションを確認中...")
            all_positions = await bot.get_positions()  # tickerを指定しない
            
            if all_positions and all_positions.get('Data'):
                logging.info(f"全ポジション: {json.dumps(all_positions, indent=2)}")
                print(f"全ポジション数: {len(all_positions['Data'])}")
                
                # 各ポジションの詳細を表示
                for pos in all_positions['Data']:
                    pos_base = pos.get('PositionBase', {})
                    net_position_id = pos.get('NetPositionId', '')
                    uic = pos_base.get('Uic', 'Unknown')
                    asset_type = pos_base.get('AssetType', 'Unknown')
                    amount = pos_base.get('Amount', 0)
                    source_order_id = pos_base.get('SourceOrderId', '')
                    
                    print(f"  - NetPositionId: {net_position_id}, Uic: {uic}, AssetType: {asset_type}, Amount: {amount}")
                    print(f"    SourceOrderId: {source_order_id}")
                    
                    # 注文IDが一致するかチェック
                    if source_order_id == main_order_id:
                        print(f"    → ★ これは今回の注文（OrderID: {main_order_id}）のポジションです！")
                        # ポジションが見つかったので、手動でデータを設定
                        positions = {'Data': [pos]}
                        break
                    
                    # NetPositionIdでティッカーを判定
                    ticker_saxo = entrypoint['ticker'].replace("_", "")
                    if ticker_saxo in net_position_id and asset_type == "FxSpot":
                        print(f"    → 通貨ペア {entrypoint['ticker']} の可能性があります")
            
            # それでもポジションが見つからない場合
            if not positions or not positions.get('Data'):
                print("注文は送信されましたが、ポジションの確認ができませんでした。")
                if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key, 
                        f"注文は送信されましたが（OrderID: {main_order_id}）、ポジションの確認ができませんでした。手動で確認してください。")
                return
        
        # ここからは通常のポジション処理
        position = positions['Data'][0]
        position_base = position.get('PositionBase', {})
        main_order_price = position_base.get('OpenPrice', 0)
        main_position_id = position.get('PositionId')  # PositionIdは直下にある

        # 決済ポジション検索用にSourceOrderIdも記録（グローバル変数として定義）
        main_source_order_id = position_base.get('SourceOrderId', main_order_id)  # これが決済履歴で使用される

        # 発注時間を取得（APIレスポンスに含まれる場合）
        execution_time_open = position_base.get('ExecutionTimeOpen') or position.get('OpenTime')
        
        # 発注時間の処理
        if execution_time_open:
            try:
                # SAXOのタイムスタンプはUTC（例: "2025-06-10T06:23:00Z"）
                open_datetime = datetime.fromisoformat(execution_time_open.replace('Z', '+00:00'))
                # 日本時間に変換（UTC+9）
                from datetime import timezone
                jst = timezone(timedelta(hours=9))
                open_datetime_jst = open_datetime.replace(tzinfo=timezone.utc).astimezone(jst)
                open_time_str = open_datetime_jst.strftime('%H:%M:%S')
                print(f"発注時刻: {open_time_str} (JST)")
            except Exception as e:
                print(f"発注時刻の変換エラー: {e}")
                open_time_str = None
        else:
            open_time_str = None
            print("発注時刻: 取得できません")

        print(f"約定レート: {main_order_price}")
        print(f"ポジションID: {main_position_id}")
        print(f"ソース注文ID: {main_source_order_id}")
        
        # 逆指値注文
        sl_price = 0
        if entrypoint['StopRate'] != 0:
            # pips計算のための倍率
            if entrypoint['ticker'][-3:] != "JPY":
                gmultiply = 100000
            else:
                gmultiply = 1000
                
            if entrypoint['direction'].upper() == "BUY":
                sl_price = round(main_order_price - (entrypoint['StopRate'] / gmultiply), 5)
                sl_direction = "SELL"
            else:
                sl_price = round(main_order_price + (entrypoint['StopRate'] / gmultiply), 5)
                sl_direction = "BUY"
                
            print(f"逆指値注文準備: SLレート={sl_price}, 方向={sl_direction}, StopRate={entrypoint['StopRate']}points")
            logging.info(f"逆指値注文準備: SLレート={sl_price}, 方向={sl_direction}")
            
            # 逆指値注文を発注
            sl_result = await bot.place_stop_order(
                entrypoint['ticker'],
                sl_direction,
                main_volume,
                sl_price
            )
            
            # 結果を必ずログ出力
            if sl_result:
                if sl_result.get('ErrorInfo'):
                    print(f"逆指値注文ERROR: {sl_result['ErrorInfo']}")
                    logging.error(f"逆指値注文エラー: {sl_result}")
                    if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key, f"逆指値注文エラー: {sl_result['ErrorInfo']}")
                else:
                    # 成功時 - OrderIDを記録
                    sl_order_id = sl_result.get('OrderId', 'Unknown')
                    print(f"逆指値注文OK: OrderId={sl_order_id}, SL={sl_price}")
                    logging.info(f"逆指値注文成功: OrderId={sl_order_id}, SL={sl_price}")
            else:
                print("逆指値注文ERROR: レスポンスなし")
                logging.error("逆指値注文エラー: レスポンスなし")
        
        # 通知（発注時間を含めるように修正）
        if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
            if config['autolot'].upper() == 'TRUE':
                message = f"建玉 {entrypoint['ticker']} {entrypoint['direction']} {entrypoint['entry_time'].strftime('%H:%M:%S')}-{entrypoint['exit_time'].strftime('%H:%M:%S')}\n"
                message += f"OrderID: {main_order_id}\n"
                if open_time_str:
                    message += f"発注時刻: {open_time_str}\n"
                message += f"size(AutoLot){main_volume} Leverage {config['leverage']} price{main_order_price}"
            else:
                message = f"建玉 {entrypoint['ticker']} {entrypoint['direction']} {entrypoint['entry_time'].strftime('%H:%M:%S')}-{entrypoint['exit_time'].strftime('%H:%M:%S')}\n"
                message += f"OrderID: {main_order_id}\n"
                if open_time_str:
                    message += f"発注時刻: {open_time_str}\n"
                message += f"size{entrypoint['amount']} price{main_order_price}"
            
            if sl_price != 0:
                message += f" sl_price{sl_price}"
            message += f"\nmemo{entrypoint['memo']}"
            
            await SAXOlib.send_discord_message(discord_key, message)
        
        # 判定時刻まで待機
        await SAXOlib.wait_until(entrypoint["exit_time"], 15)

        # ポジション確認
        positions = await bot.get_positions(entrypoint['ticker'])
        if not positions or not positions.get('Data'):
            print("ポジション無し。TPorSLで決済されています。")
            print(f"決済前の情報: OrderID={main_order_id}, PositionID={main_position_id}, SourceOrderID={main_source_order_id if 'main_source_order_id' in locals() else 'N/A'}")
            print(f"SL注文: OrderID={sl_order_id if 'sl_order_id' in locals() else 'N/A'}, SL価格={sl_price if 'sl_price' in locals() else 'N/A'}")
            
            # SL決済時の詳細情報を取得
            print("決済履歴を確認中...")
            
            # 決済がAPIに反映されるまで少し待機
            await asyncio.sleep(5)  # 5秒待機に延長
            
            # SourceOrderIdとPositionIdの両方で検索を試みる
            closed_position = await bot.get_recent_closed_position(
                entrypoint['ticker'], 
                order_id=main_source_order_id if 'main_source_order_id' in locals() else main_order_id,
                position_id=main_position_id
            )
            
            # 一度目で取得できない場合は再試行
            retry_count = 0
            while not closed_position and retry_count < 5:  # 最大5回に増加
                retry_count += 1
                print(f"決済履歴が見つかりません。再試行中... ({retry_count}/5)")
                await asyncio.sleep(5)  # 5秒待機に延長
                
                # 時間範囲を広げて再検索
                closed_position = await bot.get_recent_closed_position(
                    entrypoint['ticker'], 
                    order_id=main_source_order_id if 'main_source_order_id' in locals() else main_order_id,
                    position_id=main_position_id
                )
            
            # それでも見つからない場合は、条件なしで最新の決済を取得
            if not closed_position:
                print("条件を緩めて最新の決済を検索中...")
                closed_position = await bot.get_recent_closed_position(
                    entrypoint['ticker'], 
                    order_id=None,
                    position_id=None
                )
                
                # 最新の決済が見つかった場合、それが今回の決済かどうか確認
                if closed_position:
                    closed_pos_details = closed_position.get('ClosedPosition', {})
                    close_time_str = closed_pos_details.get('ExecutionTimeClose', '')
                    
                    # 決済時刻が最近（5分以内）かチェック
                    if close_time_str:
                        try:
                            # SAXOのタイムスタンプはUTC
                            close_time = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
                            # 現在時刻もUTCに変換
                            from datetime import timezone
                            now_utc = datetime.now(timezone.utc)
                            time_diff = (now_utc - close_time).total_seconds()
                            if time_diff < 300:  # 5分以内
                                print(f"最新の決済を使用します（{time_diff:.0f}秒前）")
                            else:
                                print(f"最新の決済は古すぎます（{time_diff/60:.1f}分前）")
                                closed_position = None
                        except Exception as e:
                            print(f"時刻計算エラー: {e}")
                            # エラーの場合は最新の決済を使用
                            pass
            
            if closed_position:
                # 決済情報から実際の約定価格を取得
                closed_pos_details = closed_position.get('ClosedPosition', {})
                close_price = closed_pos_details.get('ExecutionPrice') or closed_pos_details.get('ClosingPrice', 0)
                close_time = closed_pos_details.get('ExecutionTimeClose') or closed_pos_details.get('CloseTime')
                
                # 実現損益がAPIから取得できる場合
                profit_loss = closed_position.get('ProfitLoss', 0)
                profit_loss_in_base_currency = closed_position.get('ProfitLossInBaseCurrency', profit_loss)
                
                # close_priceが0の場合、SL価格を使用
                if close_price == 0 or close_price is None:
                    print(f"決済価格が取得できないため、SL価格を使用: {sl_price}")
                    close_price = sl_price
                    
                    # それでもclose_priceが0の場合はエラー
                    if close_price == 0:
                        print("警告: SL価格も取得できません")
                        # デフォルトで逆指値設定から計算
                        if entrypoint['StopRate'] != 0:
                            if entrypoint['ticker'][-3:] != "JPY":
                                gmultiply = 100000
                            else:
                                gmultiply = 1000
                            
                            if entrypoint['direction'].upper() == "BUY":
                                close_price = main_order_price - (entrypoint['StopRate'] / gmultiply)
                            else:
                                close_price = main_order_price + (entrypoint['StopRate'] / gmultiply)
                            print(f"StopRate設定から決済価格を推定: {close_price}")
                
                # pips計算
                if entrypoint['ticker'][-3:] != "JPY":
                    multiply = 10000
                else:
                    multiply = 100
                
                if entrypoint['direction'].upper() == "BUY":
                    pips = (close_price - main_order_price) * multiply
                else:
                    pips = (main_order_price - close_price) * multiply
                
                # 異常な値のチェック
                if abs(pips) > 1000:
                    print(f"警告: 異常なpips値を検出 ({pips:.3f}pips)")
                    print(f"  開始価格: {main_order_price}")
                    print(f"  決済価格: {close_price}")
                    print(f"  差分: {abs(close_price - main_order_price)}")
                    
                    # SL設定から実際のpipsを再計算
                    if entrypoint['StopRate'] != 0:
                        # StopRateはpips単位（例：10 = 1.0pips）
                        actual_pips = -abs(entrypoint['StopRate'] / 10.0)  # SLなので必ず負の値
                        print(f"StopRate設定から再計算: {actual_pips:.1f}pips")
                        pips = actual_pips
                
                # もしAPIから損益が取得できない場合は計算
                if profit_loss_in_base_currency == 0 and pips != 0:
                    if entrypoint['ticker'][-3:] == "JPY":
                        profit_loss_in_base_currency = pips * main_volume / multiply
                    else:
                        # USD建ての場合はUSDJPYレートで換算
                        usdjpy_price = await bot.get_price("USD_JPY")
                        if usdjpy_price:
                            usdjpy_mid = (usdjpy_price['Quote']['Bid'] + usdjpy_price['Quote']['Ask']) / 2
                            profit_loss_in_base_currency = pips * main_volume / multiply * usdjpy_mid
                
                # 決済時刻の処理
                if close_time:
                    try:
                        close_datetime = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                        # 日本時間に変換（UTC+9）
                        from datetime import timezone
                        jst = timezone(timedelta(hours=9))
                        close_datetime_jst = close_datetime.replace(tzinfo=timezone.utc).astimezone(jst)
                        close_time_str = close_datetime_jst.strftime('%H:%M:%S')
                    except:
                        close_time_str = datetime.now().strftime('%H:%M:%S')
                else:
                    close_time_str = datetime.now().strftime('%H:%M:%S')
                
                print(f"SL決済詳細: {pips:.1f}pips, 損益{profit_loss_in_base_currency:.0f}円")
                print(f"決済価格: {close_price}")
                print(f"決済時刻: {close_time_str}")
                
                # 取引結果を記録
                trade_results.append({
                    'ticker': entrypoint['ticker'],
                    'direction': entrypoint['direction'],
                    'memo': entrypoint['memo'],
                    'pips': pips,
                    'profit_loss': profit_loss_in_base_currency,
                    'close_type': 'SL',
                    'close_time': close_time_str,
                    'open_price': main_order_price,
                    'close_price': close_price,
                    'entry_time': entrypoint['entry_time'].strftime('%H:%M'),
                    'exit_time': entrypoint['exit_time'].strftime('%H:%M')
                })
                
                if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key,
                        f"SLで決済されました\n"
                        f"決済 {entrypoint['ticker']} {entrypoint['direction']} {entrypoint['entry_time'].strftime('%H:%M')}-{entrypoint['exit_time'].strftime('%H:%M')}\n"
                        f"{pips:.1f}pips 損益{profit_loss_in_base_currency:.0f}円\n"
                        f"決済時刻: {close_time_str}\n"
                        f"entPrice{main_order_price} closePrice{close_price}\n"
                        f"memo {entrypoint['memo']}")
            else:
                # 決済履歴が取得できない場合（従来の処理）
                print("決済履歴が取得できませんでした")
                
                # SL価格から推定値を計算
                if sl_price > 0:
                    # pips計算
                    if entrypoint['ticker'][-3:] != "JPY":
                        multiply = 10000
                    else:
                        multiply = 100
                    
                    if entrypoint['direction'].upper() == "BUY":
                        estimated_pips = (sl_price - main_order_price) * multiply
                    else:
                        estimated_pips = (main_order_price - sl_price) * multiply
                    
                    # 損益計算（推定）
                    if entrypoint['ticker'][-3:] == "JPY":
                        estimated_profit_loss = estimated_pips * main_volume / multiply
                    else:
                        # USD建ての場合はUSDJPYレートで換算
                        usdjpy_price = await bot.get_price("USD_JPY")
                        if usdjpy_price:
                            usdjpy_mid = (usdjpy_price['Quote']['Bid'] + usdjpy_price['Quote']['Ask']) / 2
                            estimated_profit_loss = estimated_pips * main_volume / multiply * usdjpy_mid
                        else:
                            estimated_profit_loss = 0
                    
                    print(f"SL決済（推定）: {estimated_pips:.1f}pips, 損益{estimated_profit_loss:.0f}円")
                    
                    if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key,
                            f"SLで決済されています（推定）。\n"
                            f"決済 {entrypoint['ticker']} {entrypoint['direction']} {entrypoint['entry_time'].strftime('%H:%M')}-{entrypoint['exit_time'].strftime('%H:%M')}\n"
                            f"{estimated_pips:.1f}pips 損益{estimated_profit_loss:.0f}円（推定）\n"
                            f"entPrice{main_order_price} SLPrice{sl_price}\n"
                            f"memo {entrypoint['memo']}")
                else:
                    if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key,
                            f"SLで決済されています。\n決済 {entrypoint['ticker']} {entrypoint['direction']} {entrypoint['entry_time']}-{entrypoint['exit_time']}\nmemo {entrypoint['memo']}")
            return
        
        # 判定時刻まで待機
        await SAXOlib.wait_until(entrypoint["exit_time"])
        
        # 決済前に再度ポジションを確認
        print("\n決済前のポジション確認...")
        positions = await bot.get_positions(entrypoint['ticker'])
        
        if not positions or not positions.get('Data'):
            print("ポジションが見つかりません。既に決済されている可能性があります。")
            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                await SAXOlib.send_discord_message(
                    discord_key,
                    f"ポジションが見つかりません。既に決済されています。\n{entrypoint['ticker']} {entrypoint['entry_time']}-{entrypoint['exit_time']}")
            return
        
        # 【重要】決済前に未約定注文（逆指値注文）をキャンセル
        print("\n決済前の未約定注文確認...")
        
        # 方法1: 通貨ペアの全ての未約定注文を取得
        orders = await bot.get_orders(entrypoint['ticker'])
        
        cancelled_orders = []  # キャンセル済み注文のリスト
        
        if orders and orders.get('Data'):
            print(f"未約定注文が{len(orders['Data'])}件見つかりました")
            
            for order in orders['Data']:
                order_id_to_cancel = order.get('OrderId')
                order_type = order.get('OrderType')
                order_price = order.get('OrderPrice')
                
                print(f"  - OrderId: {order_id_to_cancel}, Type: {order_type}, Price: {order_price}")
                
                # 逆指値注文の場合はキャンセル
                if order_type == 'Stop' or order_type == 'StopLimit':
                    print(f"  → 逆指値注文をキャンセルします")
                    cancel_result = await bot.cancel_order(order_id_to_cancel)
                    
                    if cancel_result:
                        print(f"  → キャンセル成功")
                        logging.info(f"逆指値注文キャンセル成功: OrderId={order_id_to_cancel}")
                        cancelled_orders.append(order_id_to_cancel)
                    else:
                        print(f"  → キャンセル失敗")
                        logging.error(f"逆指値注文キャンセル失敗: OrderId={order_id_to_cancel}")
        else:
            print("API経由では未約定注文が検出されませんでした")
            
            # 方法2: 記録していた逆指値注文IDを直接キャンセル
            if sl_order_id and sl_order_id not in cancelled_orders:
                print(f"\n記録されている逆指値注文ID（{sl_order_id}）を直接キャンセルします")
                try:
                    cancel_result = await bot.cancel_order(sl_order_id)
                    if cancel_result:
                        print(f"  → 逆指値注文（OrderId: {sl_order_id}）のキャンセル成功")
                        logging.info(f"逆指値注文キャンセル成功（直接）: OrderId={sl_order_id}")
                    else:
                        print(f"  → 逆指値注文（OrderId: {sl_order_id}）のキャンセル失敗")
                        logging.error(f"逆指値注文キャンセル失敗（直接）: OrderId={sl_order_id}")
                except Exception as e:
                    print(f"  → キャンセルエラー: {e}")
                    logging.error(f"逆指値注文キャンセルエラー: {e}")
            
            # 方法3: 全アカウントの未約定注文を確認（デバッグ用）
            print("\n全アカウントの未約定注文を確認中...")
            all_orders = await bot.get_orders()  # tickerを指定しない
            
            if all_orders and all_orders.get('Data'):
                print(f"  全体で{len(all_orders['Data'])}件の未約定注文があります")
                
                # 該当通貨ペアのUICを取得
                instrument_info = await bot.get_instrument_details(entrypoint['ticker'])
                expected_uic = instrument_info['Uic'] if instrument_info else None
                
                for order in all_orders['Data']:
                    uic = order.get('Uic')
                    order_id = order.get('OrderId')
                    order_type = order.get('OrderType')
                    
                    # 該当する逆指値注文を探す
                    if (str(uic) == str(expected_uic) and 
                        (order_type == 'Stop' or order_type == 'StopLimit') and
                        order_id not in cancelled_orders):
                        
                        print(f"  → 未キャンセルの逆指値注文を発見: OrderId={order_id}")
                        cancel_result = await bot.cancel_order(order_id)
                        
                        if cancel_result:
                            print(f"    → キャンセル成功")
                        else:
                            print(f"    → キャンセル失敗")
        
        # 全決済注文
        print(f"\n決済開始（ポジション数: {len(positions['Data'])}）")
        
        # 成功/失敗カウンタを追加
        success_count = 0
        failed_count = 0
        total_pips = 0
        total_profit_loss = 0
        
        # 決済したポジションの情報を記録
        closed_positions_info = []
        
        for i, pos in enumerate(positions['Data']):
            try:
                pos_base = pos['PositionBase']
                pos_id = pos['PositionId']  # PositionIdは直下にある
                pos_amount = abs(pos_base['Amount'])
                open_price = pos_base.get('OpenPrice', 0)
                
                print(f"  ポジション{i+1}: ID={pos_id}, Amount={pos_amount}, OpenPrice={open_price}")
                
                # ポジションの存在確認（既に決済されていないか）
                current_positions = await bot.get_positions(entrypoint['ticker'])
                position_still_exists = False
                
                if current_positions and current_positions.get('Data'):
                    for current_pos in current_positions['Data']:
                        if current_pos.get('PositionId') == pos_id:
                            position_still_exists = True
                            break
                
                if not position_still_exists:
                    print(f"  → ポジション{pos_id}は既に決済されています（スキップ）")
                    continue
                
                close_result = await bot.close_position(pos_id, pos_amount)
                
                if close_result and close_result.get('OrderId'):
                    print(f"  → 決済注文発注成功: OrderId={close_result['OrderId']}")
                    success_count += 1
                    
                    # 決済情報を記録（後で履歴を取得するため）
                    closed_positions_info.append({
                        'position_id': pos_id,
                        'close_order_id': close_result['OrderId'],
                        'open_price': open_price,
                        'amount': pos_amount,
                        'direction': "BUY" if pos_base['Amount'] > 0 else "SELL"
                    })
                else:
                    print(f"  → 決済注文失敗")
                    failed_count += 1
                    if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key,
                            f"決済注文失敗: ポジションID {pos_id}")
                        
            except Exception as e:
                print(f"  → 決済処理エラー: {e}")
                failed_count += 1
                logging.error(f"決済処理エラー (PositionID={pos_id}): {e}")
        
        # 決済結果サマリー
        print(f"\n決済処理完了: 成功={success_count}, 失敗={failed_count}")
        
        # 決済が成功した場合は、実際の約定情報を取得
        if success_count > 0:
            print("\n決済約定情報を取得中...")
            
            # 決済がAPIに反映されるまで待機
            await asyncio.sleep(5)
            
            # 各決済の実際の約定情報を取得
            for closed_info in closed_positions_info:
                try:
                    # 決済履歴を取得
                    closed_position = await bot.get_recent_closed_position(
                        entrypoint['ticker'],
                        order_id=closed_info['close_order_id'],
                        position_id=closed_info['position_id']
                    )
                    
                    # 取得できない場合は再試行
                    retry_count = 0
                    while not closed_position and retry_count < 3:
                        retry_count += 1
                        print(f"  決済履歴が見つかりません。再試行中... ({retry_count}/3)")
                        await asyncio.sleep(3)
                        
                        closed_position = await bot.get_recent_closed_position(
                            entrypoint['ticker'],
                            order_id=closed_info['close_order_id'],
                            position_id=closed_info['position_id']
                        )
                    
                    if closed_position:
                        # 決済情報から実際の約定価格を取得
                        closed_pos_details = closed_position.get('ClosedPosition', {})
                        close_price = closed_pos_details.get('ExecutionPrice') or closed_pos_details.get('ClosingPrice', 0)
                        close_time = closed_pos_details.get('ExecutionTimeClose') or closed_pos_details.get('CloseTime')
                        
                        # 実現損益
                        profit_loss = closed_position.get('ProfitLoss', 0)
                        profit_loss_in_base_currency = closed_position.get('ProfitLossInBaseCurrency', profit_loss)
                        
                        # pips計算
                        if entrypoint['ticker'][-3:] != "JPY":
                            multiply = 10000
                        else:
                            multiply = 100
                        
                        if closed_info['direction'] == "BUY":
                            pips = (close_price - closed_info['open_price']) * multiply
                        else:
                            pips = (closed_info['open_price'] - close_price) * multiply
                        
                        # 決済時刻の処理
                        if close_time:
                            try:
                                close_datetime = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                                # 日本時間に変換（UTC+9）
                                from datetime import timezone
                                jst = timezone(timedelta(hours=9))
                                close_datetime_jst = close_datetime.replace(tzinfo=timezone.utc).astimezone(jst)
                                close_time_str = close_datetime_jst.strftime('%H:%M:%S')
                            except:
                                close_time_str = datetime.now().strftime('%H:%M:%S')
                        else:
                            close_time_str = datetime.now().strftime('%H:%M:%S')
                        
                        total_pips += pips
                        total_profit_loss += profit_loss_in_base_currency
                        
                        print(f"  決済詳細: {pips:.3f}pips, 損益{profit_loss_in_base_currency:.0f}円")
                        print(f"  決済価格: {close_price}, 決済時刻: {close_time_str}")
                        
                        if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                            await SAXOlib.send_discord_message(
                                discord_key,
                                f"決済 {entrypoint['ticker']} {closed_info['direction']} {entrypoint['entry_time'].strftime('%H:%M')}-{entrypoint['exit_time'].strftime('%H:%M')}\n"
                                f"{pips:.3f}pips 損益{profit_loss_in_base_currency:.0f}円\n"
                                f"決済時刻: {close_time_str}\n"
                                f"entPrice{closed_info['open_price']} closePrice{close_price}\n"
                                f"memo {entrypoint['memo']}")
                    else:
                        # 決済履歴が取得できない場合は概算値を使用（フォールバック）
                        print(f"  決済履歴が取得できませんでした。概算値を使用します。")
                        
                        # 現在価格で決済価格を推定
                        current_price = await bot.get_price(entrypoint['ticker'])
                        if current_price:
                            current_quote = current_price.get('Quote', {})
                            if closed_info['direction'] == "BUY":
                                close_price = current_quote.get('Bid', closed_info['open_price'])
                                pips = (close_price - closed_info['open_price']) * multiply
                            else:
                                close_price = current_quote.get('Ask', closed_info['open_price'])
                                pips = (closed_info['open_price'] - close_price) * multiply
                            
                            # 損益計算（概算）
                            if entrypoint['ticker'][-3:] == "JPY":
                                loss_gain = pips * closed_info['amount'] / multiply
                            else:
                                # USD建ての場合はUSDJPYレートで換算
                                usdjpy_price = await bot.get_price("USD_JPY")
                                if usdjpy_price:
                                    usdjpy_mid = (usdjpy_price['Quote']['Bid'] + usdjpy_price['Quote']['Ask']) / 2
                                    loss_gain = pips * closed_info['amount'] / multiply * usdjpy_mid
                                else:
                                    loss_gain = 0
                            
                            total_pips += pips
                            total_profit_loss += loss_gain
                            
                            print(f"  → 決済完了: {pips:.3f}pips, 損益{loss_gain:.0f}円（概算）")
                            
                            if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
                                await SAXOlib.send_discord_message(
                                    discord_key,
                                    f"決済 {entrypoint['ticker']} {closed_info['direction']} {entrypoint['entry_time'].strftime('%H:%M')}-{entrypoint['exit_time'].strftime('%H:%M')}\n"
                                    f"{pips:.3f}pips 損益{loss_gain:.0f}円（概算）\n"
                                    f"entPrice{closed_info['open_price']} closePrice{close_price}\n"
                                    f"memo {entrypoint['memo']}")
                
                except Exception as e:
                    print(f"  決済情報取得エラー: {e}")
                    logging.error(f"決済情報取得エラー: {e}")
            
            # 取引結果を記録
            trade_results.append({
                'ticker': entrypoint['ticker'],
                'direction': entrypoint['direction'],
                'memo': entrypoint['memo'],
                'pips': total_pips / success_count if success_count > 0 else 0,  # 平均pips
                'profit_loss': total_profit_loss,
                'close_type': 'EXIT',
                'close_time': datetime.now().strftime('%H:%M:%S'),
                'entry_time': entrypoint['entry_time'].strftime('%H:%M'),
                'exit_time': entrypoint['exit_time'].strftime('%H:%M')
            })
        
        print("決済処理完了")
        logging.info('  +エントリー完了')
        
    except Exception as e:
        # エラーを出力
        logging.error('***** 例外が発生しました *****')
        logging.error(f"例外の型：{type(e)}")
        logging.error(f"メッセージ：{str(e)}")
        logging.error("トレースバック:")
        logging.error(traceback.format_exc())
        
        if entrypoint['line_notify'].upper() == 'TRUE' and discord_key:
            await SAXOlib.send_discord_message(
                discord_key,
                f"例外の型：{type(e)}")
        
        print(f"例外発生(取引時):{str(e)}")
        print(f"詳細はログを参照してください")

# 日次サマリーをDiscordに送信する関数
async def send_daily_summary(trade_results, discord_key):
    """
    取引結果の日次サマリーをDiscordに送信する
    
    Parameters:
    - trade_results (list): 取引結果のリスト
    - discord_key (str): Discord Webhook URL
    """
    if not discord_key or not trade_results:
        return
        
    # 日付を取得
    today = datetime.now().strftime('%Y-%m-%d')
    
    # サマリーメッセージを作成
    summary = f"📈 {today} 取引サマリー\n\n"
    
    total_pips = 0
    total_profit = 0
    win_count = 0
    lose_count = 0
    
    # 各取引の結果を集計
    for i, trade in enumerate(trade_results):
        # pips値と損益を集計
        pips = trade.get('pips', 0)
        profit = trade.get('profit_loss', 0)
        
        # 勝敗をカウント
        if pips > 0:
            win_count += 1
        elif pips < 0:
            lose_count += 1
            
        total_pips += pips
        total_profit += profit
        
        # 取引詳細を追加
        entry_time = trade.get('entry_time', '??:??')
        exit_time = trade.get('exit_time', '??:??')
        close_time = trade.get('close_time', '??:??')
        
        summary += f"{i+1}. {trade['ticker']} {trade['direction']} "
        summary += f"({entry_time}-{exit_time}) 決済時刻:{close_time}\n"
        summary += f"   {pips:.1f}pips {profit:.0f}円 - {trade['memo']}\n"
        
        # トレンド情報を追加（メモに含まれている場合）
        if "トレンド" in trade['memo']:
            summary += f"   {trade['memo']}\n"
    
    # 勝率計算
    total_trades = win_count + lose_count
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    
    # サマリー統計を追加
    summary += f"\n📊 統計:\n"
    summary += f"取引数: {total_trades} (勝: {win_count}, 負: {lose_count})\n"
    summary += f"勝率: {win_rate:.1f}%\n"
    summary += f"合計: {total_pips:.1f}pips {total_profit:.0f}円"
    
    # Discordに送信
    await SAXOlib.send_discord_message(discord_key, summary)
    print("日次サマリーをDiscordに送信しました")

async def run():
    """
    メインの実行関数
    """
    print(f"\n===== SAXO証券 FXBot v{VERSION} =====")
    
    # 現在の日時と曜日を表示
    now = datetime.now()
    weekday_jp = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][now.weekday()]
    print(f"現在日時: {now.strftime('%Y-%m-%d %H:%M:%S')} ({weekday_jp})")
    
    # 設定ファイルから情報を読み込む
    settings = load_settings()
    
    # 環境設定
    is_live_mode = settings.get("trading", {}).get("is_live_mode", False)
    env_text = "ライブ" if is_live_mode else "シミュレーション"
    print(f"実行環境: {env_text}")
    
    # Discord通知設定
    discord_key = settings.get("notification", {}).get("discord_webhook_url", "")
    if discord_key:
        print("Discord通知: 有効")
    else:
        print("Discord通知: 無効")
    
    # エンドレスモード設定
    endless_mode = False
    if len(sys.argv) > 1 and sys.argv[1].upper() == "ON":
        endless_mode = True
        print("実行モード: エンドレス（連続実行）")
    else:
        print("実行モード: 単発実行")
    
    # OAuth認証を使用してトークンを取得
    try:
        if USE_OAUTH:
            token = await get_oauth_token(is_live_mode)
        else:
            token = await get_valid_token()
            
        if not token:
            print("トークンの取得に失敗しました。終了します。")
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, 
                    f"⚠️ SAXOボット起動失敗: トークン取得エラー"
                )
            return
            
    except Exception as e:
        print(f"トークン取得エラー: {e}")
        traceback.print_exc()
        if discord_key:
            await SAXOlib.send_discord_message(
                discord_key, 
                f"⚠️ SAXOボット起動失敗: {str(e)}"
            )
        return
    
    # ボットの初期化
    bot = SaxoBot(token, is_live=is_live_mode, discord_key=discord_key)
    
    # トークン自動更新タスクを開始
    await bot.start_token_refresh_task()
    
    try:
        # 接続テスト
        if not await bot.test_connection():
            print("SAXO APIへの接続に失敗しました。終了します。")
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, 
                    f"⚠️ SAXOボット起動失敗: API接続エラー"
                )
            return
        
        # アカウント情報の取得
        account_info = await bot.get_account_info()
        if not account_info:
            print("アカウント情報の取得に失敗しました。終了します。")
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, 
                    f"⚠️ SAXOボット起動失敗: アカウント情報取得エラー"
                )
            return
        
        # 残高の取得
        balance = await bot.get_balance()
        if balance:
            # 残高表示を見やすくするためにカンマ区切りを追加
            formatted_balance = f"{balance['TotalValue']:,.2f}"
            # 実行環境（デモ/ライブ）を表示に追加
            env_text = "デモ口座" if not settings.get("trading", {}).get("is_live_mode", False) else "ライブ口座"
            print(f"口座残高: {balance['Currency']} {formatted_balance} （{env_text}）")
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, 
                    f"✅ SAXOボット起動成功（{env_text}）\n口座残高: {balance['Currency']} {formatted_balance}\n実行日: {now.strftime('%Y-%m-%d')} ({weekday_jp})"
                )
        
        while True:
            try:
                # エントリーポイントの読み込み
                entrypoints_url = settings.get("spreadsheets", {}).get("entrypoints_url", "")
                if not entrypoints_url:
                    print("エントリーポイントスプレッドシートのURLが設定されていません。")
                    if discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key, 
                            f"⚠️ SAXOボットエラー: エントリーポイントURLが未設定"
                        )
                    break
                
                print(f"\nエントリーポイントを読み込み中: {entrypoints_url}")
                print(f"現在の曜日({weekday_jp})に対応するエントリーポイントを検索します...")
                entrypoints = await SAXOlib.load_entrypoints_from_public_google_sheet(entrypoints_url)
                
                if not entrypoints:
                    print("エントリーポイントが見つかりませんでした。")
                    if discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key, 
                            f"⚠️ SAXOボット: {weekday_jp}のエントリーポイントなし"
                        )
                    
                    # エンドレスモードでない場合は終了
                    if not endless_mode:
                        break
                    
                    # エンドレスモードの場合は1時間待機して再試行
                    print("1時間後に再試行します...")
                    await asyncio.sleep(3600)
                    continue
                
                print(f"読み込んだエントリーポイント数: {len(entrypoints)}")
                
                # エントリーポイント情報を表示
                print("\n今日のエントリーポイント:")
                for i, ep in enumerate(entrypoints):
                    entry_time = ep["entry_time"].strftime("%H:%M")
                    exit_time = ep["exit_time"].strftime("%H:%M")
                    print(f"{i+1}. {ep['ticker']} {entry_time}-{exit_time} {ep['direction']}")
                
                # エントリーポイント情報をDiscordに通知
                if discord_key:
                    # Discordメッセージを作成
                    discord_message = f"📊 今日のエントリーポイント ({len(entrypoints)}件):\n"
                    for i, ep in enumerate(entrypoints):
                        entry_time = ep["entry_time"].strftime("%H:%M")
                        exit_time = ep["exit_time"].strftime("%H:%M")
                        discord_message += f"{i+1}. {ep['ticker']} {entry_time}-{exit_time} {ep['direction']}\n"
                    
                    # Discordに送信
                    await SAXOlib.send_discord_message(discord_key, discord_message)
                
                # 取引設定
                lot_size = settings.get("trading", {}).get("lot_size", 0.1)
                leverage = settings.get("trading", {}).get("leverage", 1)
                autolot = settings.get("trading", {}).get("autolot", False)
                
                # 取引結果を記録するリスト
                trade_results = []
                
                # 現在時刻を取得
                current_time = datetime.now()
                
                # 現在時刻以降のエントリーポイントのみを処理
                future_entrypoints = []
                for entrypoint in entrypoints:
                    if entrypoint["entry_time"] > current_time:
                        future_entrypoints.append(entrypoint)
                    else:
                        print(f"⏰ スキップ: {entrypoint['entry_time'].strftime('%H:%M:%S')} {entrypoint['ticker']} {entrypoint['direction']} (時刻超過)")
                
                if not future_entrypoints:
                    print("⚠️ 処理可能なエントリーポイントがありません（すべて時刻超過）")
                    if discord_key:
                        await SAXOlib.send_discord_message(
                            discord_key, 
                            f"⚠️ すべてのエントリーポイントが時刻超過のため処理を終了します"
                        )
                    break
                
                print(f"処理対象エントリーポイント数: {len(future_entrypoints)}")
                
                # 各エントリーポイントを処理
                for entrypoint in future_entrypoints:
                    # ロットサイズの設定（エントリーポイントに指定がなければ設定ファイルの値を使用）
                    if entrypoint.get("amount", 0) <= 0:
                        entrypoint["amount"] = lot_size
                    
                    # エントリーポイントを処理
                    await process_entrypoint(entrypoint, settings, bot, trade_results)
                
                # すべての取引が完了した後に日次サマリーを送信
                if discord_key and trade_results:
                    await send_daily_summary(trade_results, discord_key)
                
                # エンドレスモードでない場合は終了
                if not endless_mode:
                    break
                
                # エンドレスモードの場合は1時間待機して再試行
                print("1時間後に再試行します...")
                await asyncio.sleep(3600)
                
            except Exception as e:
                print(f"エラーが発生しました: {e}")
                traceback.print_exc()
                if discord_key:
                    await SAXOlib.send_discord_message(
                        discord_key, 
                        f"⚠️ SAXOボットエラー: {str(e)}"
                    )
                
                # エンドレスモードでない場合は終了
                if not endless_mode:
                    break
                
                # エンドレスモードの場合は10分待機して再試行
                print("10分後に再試行します...")
                await asyncio.sleep(600)
    
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        if discord_key:
            await SAXOlib.send_discord_message(
                discord_key, 
                f"⚠️ SAXOボット致命的エラー: {str(e)}"
            )
    
    finally:
        # トークン自動更新タスクを停止
        await bot.stop_token_refresh_task()
        print("\nSAXOボットを終了します。")

async def main():
    await run()

if __name__ == "__main__":
    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("saxobot.log"),
            logging.StreamHandler()
        ]
    )
    
    # 非同期実行
    asyncio.run(main())