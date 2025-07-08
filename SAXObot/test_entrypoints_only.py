#!/usr/bin/env python3
"""
SAXO証券 FXBot - エントリーポイントテスト用スクリプト
認証成功後、30秒待機してUSD/JPYのBUYエントリーを行い、さらに30秒後に決済します
"""

import asyncio
import sys
import os
import logging
from datetime import datetime, timedelta
import json

# SAXObotをインポート
import SAXObot
from SAXObot import SaxoBot

# OAuth認証モジュールの条件付きインポート
try:
    from saxo_token_oauth import get_valid_token as get_oauth_token
    USE_OAUTH = True
    print("OAuth認証モジュールを使用します")
except ImportError:
    print("OAuth認証モジュールが見つかりません。従来の認証を使用します。")
    from saxo_token_async import get_valid_token
    USE_OAUTH = False

# SAXOlibをインポート
try:
    import SAXOlib
except ImportError:
    print("エラー: SAXOlib.pyが見つかりません")
    sys.exit(1)

# 設定ファイルパス
SETTINGS_FILE = "saxo_settings.json"

async def load_settings():
    """設定ファイルから情報を読み込む"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        print(f"✓ 設定ファイル {SETTINGS_FILE} を読み込みました")
        return settings
    except Exception as e:
        print(f"設定ファイル読み込みエラー: {e}")
        sys.exit(1)

async def test_entry_exit():
    """
    テスト用のエントリーと決済を実行する関数
    """
    print(f"\n===== SAXO証券 FXBot テストスクリプト =====")
    
    # 現在の日時と曜日を表示
    now = datetime.now()
    weekday_jp = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][now.weekday()]
    print(f"現在日時: {now.strftime('%Y-%m-%d %H:%M:%S')} ({weekday_jp})")
    
    # 設定ファイルから情報を読み込む
    settings = await load_settings()
    
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
        import traceback
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
                    f"✅ SAXOボットテスト開始（{env_text}）\n口座残高: {balance['Currency']} {formatted_balance}\n実行日: {now.strftime('%Y-%m-%d')} ({weekday_jp})"
                )
        
        # 30秒待機してからエントリー
        print("\n30秒後にUSD/JPY（ドル円）のBUYエントリーを行います...")
        await asyncio.sleep(30)
        
        # エントリー実行
        ticker = "USD_JPY"  # ドル円
        direction = "BUY"    # 買い
        size = 10000         # 10,000通貨（0.1ロット）
        
        print(f"\n=== エントリー実行: {ticker} {direction} {size}通貨 ===")
        order_result = await bot.place_market_order(ticker, direction, size)
        
        if not order_result or 'ErrorInfo' in order_result:
            error_info = order_result.get('ErrorInfo', {}) if order_result else {}
            error_code = error_info.get('ErrorCode', 'Unknown')
            error_msg = error_info.get('Message', 'Unknown error')
            print(f"エントリーエラー: {error_code} - {error_msg}")
            return
        
        # 注文IDを取得
        order_id = order_result.get('OrderId')
        print(f"注文OK - OrderID: {order_id}")
        
        # ポジション確認
        print("ポジション確認中...")
        await asyncio.sleep(5)  # 約定を待つ
        
        positions = await bot.get_positions(ticker)
        if not positions or not positions.get('Data'):
            print("ポジションが見つかりません。エントリーに失敗した可能性があります。")
            return
        
        position = positions['Data'][0]
        position_base = position.get('PositionBase', {})
        position_id = position.get('PositionId')
        open_price = position_base.get('OpenPrice', 0)
        
        print(f"ポジションID: {position_id}")
        print(f"エントリー価格: {open_price}")
        
        # Discord通知
        if discord_key:
            await SAXOlib.send_discord_message(
                discord_key, 
                f"✅ テストエントリー成功\n{ticker} {direction} {size}通貨\nエントリー価格: {open_price}\nポジションID: {position_id}"
            )
        
        # 30秒待機してから決済
        print("\n30秒後に決済（エグジット）を行います...")
        await asyncio.sleep(30)
        
        # 決済実行
        print(f"\n=== 決済実行: ポジションID {position_id} ===")
        close_result = await bot.close_position(position_id, size)
        
        if not close_result or 'ErrorInfo' in close_result:
            error_info = close_result.get('ErrorInfo', {}) if close_result else {}
            error_code = error_info.get('ErrorCode', 'Unknown')
            error_msg = error_info.get('Message', 'Unknown error')
            print(f"決済エラー: {error_code} - {error_msg}")
            return
        
        # 決済確認
        print("決済確認中...")
        await asyncio.sleep(5)  # 約定を待つ
        
        # 現在価格を取得して損益計算
        price_info = await bot.get_price(ticker)
        if price_info:
            quote = price_info.get('Quote', {})
            bid = quote.get('Bid')
            ask = quote.get('Ask')
            
            # 損益計算（概算）
            if direction == "BUY":
                close_price = bid
                pips = (close_price - open_price) * 100  # ドル円の場合は100倍
            else:
                close_price = ask
                pips = (open_price - close_price) * 100  # ドル円の場合は100倍
            
            # 円換算の損益
            profit_loss = pips * size / 100
            
            print(f"決済価格: {close_price}")
            print(f"損益: {pips:.1f}pips（約{profit_loss:.0f}円）")
            
            # Discord通知
            if discord_key:
                await SAXOlib.send_discord_message(
                    discord_key, 
                    f"✅ テスト決済成功\n{ticker} {direction} {size}通貨\nエントリー価格: {open_price}\n決済価格: {close_price}\n損益: {pips:.1f}pips（約{profit_loss:.0f}円）"
                )
        
        print("\nテスト完了しました！")
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        
        if discord_key:
            await SAXOlib.send_discord_message(
                discord_key, 
                f"⚠️ テスト中にエラーが発生: {str(e)}"
            )
    
    finally:
        # トークン自動更新タスクを停止
        await bot.stop_token_refresh_task()

async def main():
    """メイン関数"""
    await test_entry_exit()

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
    
    # 非同期ループの実行
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("キーボード割り込みにより終了します")
    finally:
        loop.close() 