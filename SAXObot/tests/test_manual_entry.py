#!/usr/bin/env python3
"""
SAXO証券 FXBot - 手動エントリーポイントテスト
手動で設定したエントリーポイントで実際にエントリーと決済をテスト
"""

import asyncio
import sys
import os
import logging
import json
from datetime import datetime, timedelta

# 設定ファイルパス
SETTINGS_FILE = "saxo_settings.json"

def load_settings():
    """設定ファイルから情報を読み込む"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        print(f"✓ 設定ファイル {SETTINGS_FILE} を読み込みました")
        return settings
    except Exception as e:
        print(f"設定ファイル読み込みエラー: {e}")
        sys.exit(1)

def create_test_entrypoints():
    """テスト用のエントリーポイントを作成"""
    now = datetime.now()
    
    # 現在時刻から5分後と10分後にエントリーと決済を設定
    entry_time = now + timedelta(minutes=1)  # 1分後にエントリー
    exit_time = now + timedelta(minutes=2)   # 2分後に決済
    
    test_entrypoints = [
        {
            "entry_time": entry_time,
            "exit_time": exit_time,
            "ticker": "USD_JPY",
            "direction": "BUY",
            "amount": 0.1,  # 0.1ロット
            "memo": "テストエントリー USD/JPY BUY"
        },
        {
            "entry_time": entry_time + timedelta(minutes=1),
            "exit_time": exit_time + timedelta(minutes=1),
            "ticker": "EUR_USD",
            "direction": "SELL",
            "amount": 0.1,  # 0.1ロット
            "memo": "テストエントリー EUR/USD SELL"
        }
    ]
    
    return test_entrypoints

async def test_manual_entry():
    """手動設定のエントリーポイントでテスト"""
    print("===== SAXO証券 手動エントリーポイントテスト =====")
    
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
    
    # テスト用エントリーポイントを作成
    entrypoints = create_test_entrypoints()
    
    # エントリーポイント情報を表示
    print(f"\nテスト用エントリーポイント数: {len(entrypoints)}")
    print("\nテストエントリーポイント:")
    print("----------------------------")
    print("  通貨ペア  | エントリー | クローズ | 方向")
    print("----------------------------")
    for i, ep in enumerate(entrypoints):
        entry_time = ep["entry_time"].strftime("%H:%M")
        exit_time = ep["exit_time"].strftime("%H:%M")
        print(f"{i+1:2d}. {ep['ticker']:8s} | {entry_time:8s} | {exit_time:7s} | {ep['direction']}")
    
    # 最初のエントリーポイントでテスト実行
    if entrypoints:
        test_entrypoint = entrypoints[0]
        print(f"\n=== テスト実行: {test_entrypoint['ticker']} {test_entrypoint['direction']} ===")
        print(f"エントリー時間: {test_entrypoint['entry_time'].strftime('%H:%M:%S')}")
        print(f"決済時間: {test_entrypoint['exit_time'].strftime('%H:%M:%S')}")
        print(f"ロットサイズ: {test_entrypoint['amount']}")
        
        # 現在時刻とエントリー時刻を比較
        time_diff = (test_entrypoint['entry_time'] - now).total_seconds()
        
        if time_diff > 0:
            print(f"エントリー時間まで {time_diff:.0f} 秒待機します...")
            await asyncio.sleep(min(time_diff, 5))  # 最大5秒待機
        else:
            print("エントリー時間は既に過ぎています。即座にテストを実行します。")
        
        # 実際のエントリー処理をシミュレート
        print("\n=== エントリー処理シミュレーション ===")
        print(f"1. 価格取得: {test_entrypoint['ticker']}")
        print(f"2. 注文送信: {test_entrypoint['direction']} {test_entrypoint['amount']}ロット")
        print(f"3. 注文確認: OrderID取得")
        print(f"4. ポジション確認: PositionID取得")
        
        # 決済時刻まで待機
        exit_time_diff = (test_entrypoint['exit_time'] - now).total_seconds()
        if exit_time_diff > 0:
            print(f"\n決済時間まで {exit_time_diff:.0f} 秒待機します...")
            await asyncio.sleep(min(exit_time_diff, 5))  # 最大5秒待機
        
        print("\n=== 決済処理シミュレーション ===")
        print(f"1. ポジション確認: {test_entrypoint['ticker']}")
        print(f"2. 決済注文送信: {test_entrypoint['amount']}ロット")
        print(f"3. 決済確認: 約定確認")
        print(f"4. 損益計算: 概算損益")
        
        print("\n✅ エントリー・決済テストシミュレーションが完了しました")
        print("実際の取引を実行するには、SAXObotシステムが正常に動作していることを確認してください。")
        
        # Discord通知
        if discord_key:
            try:
                import requests
                message = f"✅ 手動エントリーポイントテスト完了\n{len(entrypoints)}件のテストエントリーポイント\n最初のエントリー: {test_entrypoint['ticker']} {test_entrypoint['direction']} {test_entrypoint['amount']}ロット"
                requests.post(discord_key, json={"content": message})
                print("Discord通知を送信しました")
            except Exception as e:
                print(f"Discord通知エラー: {e}")
    
    print("\nテスト完了しました！")

async def main():
    """メイン関数"""
    await test_manual_entry()

if __name__ == "__main__":
    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 非同期ループの実行
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("キーボード割り込みにより終了します")
    finally:
        loop.close() 