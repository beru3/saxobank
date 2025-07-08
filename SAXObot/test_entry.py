#!/usr/bin/env python3
"""
SAXO証券 テストエントリースクリプト
実行後3分後にドル円を成行注文し、1分後に決済するテストプログラム
"""

import asyncio
import sys
import logging
import json
from datetime import datetime, timedelta

# SAXOlib をインポート
try:
    import SAXOlib
except ImportError:
    print("エラー: SAXOlib.pyが見つかりません")
    sys.exit(1)

# OAuth認証モジュールのインポート
try:
    from saxo_token_oauth import get_valid_token as get_oauth_token
    USE_OAUTH = True
    print("OAuth認証モジュールを使用します")
except ImportError:
    print("OAuth認証モジュールが見つかりません。従来の認証を使用します。")
    from saxo_token_async import get_valid_token
    USE_OAUTH = False

# SAXOBotクラスをインポート
from SAXObot import SaxoBot

# 設定ファイルパス
SETTINGS_FILE = "saxo_settings.json"

async def load_settings():
    """設定ファイルを読み込む"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        print(f"✓ 設定ファイル {SETTINGS_FILE} を読み込みました")
        return settings
    except Exception as e:
        print(f"設定ファイル読み込みエラー: {e}")
        sys.exit(1)

async def run_test_entry():
    """テストエントリーを実行する"""
    print("\n===== SAXO証券 テストエントリー =====")
    
    # 現在の日時を表示
    now = datetime.now()
    print(f"現在日時: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 設定を読み込む
    settings = await load_settings()
    
    # デモ環境を強制的に使用
    settings["trading"]["is_live_mode"] = False
    print("実行環境: シミュレーション（デモ口座）")
    
    # Discord通知設定
    discord_key = settings.get("notification", {}).get("discord_webhook_url", "")
    if discord_key:
        print("Discord通知: 有効")
    else:
        print("Discord通知: 無効")
    
    # OAuth認証を使用してトークンを取得
    try:
        if USE_OAUTH:
            token = await get_oauth_token(False)  # デモ環境
        else:
            token = await get_valid_token()
            
        if not token:
            print("トークンの取得に失敗しました。終了します。")
            return
            
    except Exception as e:
        print(f"トークン取得エラー: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # ボットの初期化
    bot = SaxoBot(token, is_live=False, discord_key=discord_key)
    
    # トークン自動更新タスクを開始
    await bot.start_token_refresh_task()
    
    try:
        # 接続テスト
        if not await bot.test_connection():
            print("SAXO APIへの接続に失敗しました。終了します。")
            return
        
        # アカウント情報の取得
        account_info = await bot.get_account_info()
        if not account_info:
            print("アカウント情報の取得に失敗しました。終了します。")
            return
        
        # 残高の取得
        balance = await bot.get_balance()
        if balance:
            formatted_balance = f"{balance['TotalValue']:,.2f}"
            print(f"口座残高: {balance['Currency']} {formatted_balance} （デモ口座）")
        
        # テスト用の通貨ペアとパラメータ
        ticker = "USD_JPY"
        direction = "BUY"
        size = 100000  # 1ロット = 100,000通貨単位
        
        # エントリー時刻（現在時刻から30秒後）
        entry_time = datetime.now() + timedelta(seconds=30)
        # 決済時刻（エントリーから1分後）
        exit_time = entry_time + timedelta(minutes=1)
        
        print(f"\n=== テストエントリー設定 ===")
        print(f"通貨ペア: {ticker}")
        print(f"方向: {direction}")
        print(f"数量: {size} (1ロット)")
        print(f"エントリー予定時刻: {entry_time.strftime('%H:%M:%S')} (あと{(entry_time - datetime.now()).total_seconds():.0f}秒)")
        print(f"決済予定時刻: {exit_time.strftime('%H:%M:%S')}")
        
        # エントリー時刻まで待機
        wait_seconds = (entry_time - datetime.now()).total_seconds()
        if wait_seconds > 0:
            print(f"\nエントリー時刻まで待機中... ({wait_seconds:.0f}秒)")
            await asyncio.sleep(wait_seconds)
        
        # 現在の価格を取得
        price_info = await bot.get_price(ticker)
        if price_info:
            quote = price_info.get('Quote', {})
            bid = quote.get('Bid')
            ask = quote.get('Ask')
            print(f"\n現在価格 - Bid: {bid}, Ask: {ask}")
        
        # 成行注文を発注
        print(f"\n=== エントリー実行 ({datetime.now().strftime('%H:%M:%S')}) ===")
        print(f"{ticker} {direction} {size}単位 成行注文")
        
        order_result = await bot.place_market_order(ticker, direction, size)
        if not order_result or (isinstance(order_result, dict) and 'ErrorInfo' in order_result):
            print("注文エラー。詳細はログを確認してください。")
            return
        
        # 注文IDを取得
        order_id = order_result.get('OrderId')
        print(f"注文成功 - OrderID: {order_id}")
        
        # ポジション確認
        await asyncio.sleep(3)  # 約定を待つ
        positions = await bot.get_positions(ticker)
        
        if not positions or not positions.get('Data'):
            print("ポジションが見つかりません。")
            return
        
        position = positions['Data'][0]
        position_id = position.get('PositionId')
        position_base = position.get('PositionBase', {})
        open_price = position_base.get('OpenPrice')
        
        print(f"ポジション確認 - ID: {position_id}, 価格: {open_price}")
        
        # 決済時刻まで待機
        wait_seconds = (exit_time - datetime.now()).total_seconds()
        if wait_seconds > 0:
            print(f"\n決済時刻まで待機中... ({wait_seconds:.0f}秒)")
            await asyncio.sleep(wait_seconds)
        
        # 決済実行
        print(f"\n=== 決済実行 ({datetime.now().strftime('%H:%M:%S')}) ===")
        close_result = await bot.close_position(position_id, size)
        
        if not close_result or (isinstance(close_result, dict) and 'ErrorInfo' in close_result):
            print("決済エラー。詳細はログを確認してください。")
            return
        
        print("決済成功")
        
        # 決済後の価格を取得
        price_info = await bot.get_price(ticker)
        if price_info:
            quote = price_info.get('Quote', {})
            bid = quote.get('Bid')
            ask = quote.get('Ask')
            print(f"決済時価格 - Bid: {bid}, Ask: {ask}")
        
        # 決済詳細を取得
        await asyncio.sleep(3)  # 決済処理完了を待つ
        closed_position = await bot.get_recent_closed_position(ticker, position_id=position_id)
        
        if closed_position:
            closed_info = closed_position.get('ClosedPosition', {})
            close_price = closed_info.get('ClosePrice')
            pnl = closed_info.get('ProfitLossInBaseCurrency')
            
            print(f"\n=== 取引結果 ===")
            print(f"エントリー価格: {open_price}")
            print(f"決済価格: {close_price}")
            print(f"損益: {pnl}")
            
            # pips計算
            if ticker[-3:] == "JPY":
                pips = (float(close_price) - float(open_price)) * 100 if direction == "BUY" else (float(open_price) - float(close_price)) * 100
            else:
                pips = (float(close_price) - float(open_price)) * 10000 if direction == "BUY" else (float(open_price) - float(close_price)) * 10000
                
            print(f"pips: {pips:.1f}")
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # トークン自動更新タスクを停止
        await bot.stop_token_refresh_task()
        print("\nテストエントリーを終了します。")

if __name__ == "__main__":
    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("test_entry.log"),
            logging.StreamHandler()
        ]
    )
    
    # 非同期実行
    asyncio.run(run_test_entry()) 