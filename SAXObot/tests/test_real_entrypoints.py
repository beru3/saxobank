#!/usr/bin/env python3
"""
SAXO証券 FXBot - 実際のスプレッドシートエントリーポイントテスト
実際のスプレッドシートの内容を使ってエントリーと決済をテスト
"""

import asyncio
import sys
import os
import logging
import json
import subprocess
import csv
from io import StringIO
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

def convert_ticker_format(ticker):
    """通貨ペアをSAXO形式に変換（例：USDJPY → USD_JPY）"""
    if len(ticker) == 6:
        return f"{ticker[:3]}_{ticker[3:]}"
    return ticker

def convert_nums_to_datetime(hour, minute, second=0):
    """時間と分から今日の日時オブジェクトを作成"""
    now = datetime.now()
    return now.replace(hour=hour, minute=minute, second=second, microsecond=0)

def load_entrypoints_from_curl(url):
    """curlを使ってスプレッドシートからエントリーポイントを読み込む"""
    try:
        # curlコマンドでスプレッドシートを取得（Windows環境対応）
        result = subprocess.run([
            'curl', '-L', '-s', 
            f"{url}/gviz/tq?tqx=out:csv"
        ], capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode != 0:
            print(f"curlエラー: {result.stderr}")
            return []
        
        # CSVデータの読み込み
        csv_data = StringIO(result.stdout)
        reader = csv.reader(csv_data)
        data = [row for row in reader]
        
        # 現在の曜日を取得
        now = datetime.now()
        weekday_num = now.weekday()  # 0=月曜日, 1=火曜日, ..., 6=日曜日
        current_day_jp = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][weekday_num]
        
        print(f"現在の曜日: {current_day_jp} ({now.strftime('%Y-%m-%d')})")
        
        # データの解析（簡易版）
        entrypoints = []
        
        # ヘッダー行をスキップしてデータ行を処理
        for i, row in enumerate(data[1:], 2):
            try:
                if len(row) < 4:
                    continue
                    
                # 空の行はスキップ
                if not row[0].strip():
                    continue
                
                # 合計行はスキップ
                if row[0].strip() == "合計":
                    continue
                
                # 時間形式を解析（HH:MM形式）
                entry_time_str = row[1].strip()
                close_time_str = row[2].strip()
                
                if not entry_time_str or not close_time_str:
                    continue
                
                # 時間と分に分割
                entry_hour, entry_minute = map(int, entry_time_str.split(':'))
                close_hour, close_minute = map(int, close_time_str.split(':'))
                
                # 現在の日付で日時オブジェクトを作成
                entry_time = convert_nums_to_datetime(entry_hour, entry_minute, 0)
                exit_time = convert_nums_to_datetime(close_hour, close_minute, 0)
                
                # 方向を標準化
                direction = row[3].strip().upper()
                if direction in ["SHORT", "S", "SELL", "売り"]:
                    direction = "SELL"
                elif direction in ["LONG", "L", "BUY", "買い"]:
                    direction = "BUY"
                else:
                    print(f"行{i} - 不明な取引方向: {direction}、スキップします")
                    continue
                
                # 通貨ペアをSAXO形式に変換
                ticker = convert_ticker_format(row[0].strip())
                
                # エントリーポイントレコードを作成
                record = {
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "ticker": ticker,
                    "direction": direction,
                    "amount": 0.1,  # デフォルトlot
                    "memo": f"{current_day_jp} {entry_time_str}-{close_time_str} {direction}"
                }
                
                entrypoints.append(record)
                
            except Exception as e:
                print(f"行{i} - データ解析エラー: {e}")
                continue
        
        # エントリー時刻でソート
        entrypoints.sort(key=lambda x: (x["entry_time"].hour, x["entry_time"].minute))
        return entrypoints
        
    except Exception as e:
        print(f"スプレッドシート読み込みエラー: {e}")
        return []

async def test_real_entrypoints():
    """実際のスプレッドシートからエントリーポイントを読み込んでテスト"""
    print("===== SAXO証券 実際のスプレッドシートエントリーポイントテスト =====")
    
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
    
    # エントリーポイントスプレッドシートのURLを取得
    entrypoints_url = settings.get("spreadsheets", {}).get("entrypoints_url", "")
    if not entrypoints_url:
        print("エントリーポイントスプレッドシートのURLが設定されていません。")
        return
    
    # スプレッドシートIDを抽出
    spreadsheet_id = entrypoints_url.split("/d/")[1].split("/")[0]
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    
    print(f"\nエントリーポイントを読み込み中: {csv_url}")
    
    # エントリーポイントを読み込み
    entrypoints = load_entrypoints_from_curl(csv_url)
    
    if not entrypoints:
        print("エントリーポイントが見つかりませんでした。")
        return
    
    # エントリーポイント情報を表示
    print(f"\n読み込んだエントリーポイント数: {len(entrypoints)}")
    print("\n今日のエントリーポイント:")
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
        
        print("\n✅ 実際のスプレッドシートエントリーポイントテストが完了しました")
        print("実際の取引を実行するには、SAXObotシステムが正常に動作していることを確認してください。")
        
        # Discord通知
        if discord_key:
            try:
                import requests
                message = f"✅ 実際のスプレッドシートエントリーポイントテスト完了\n{len(entrypoints)}件のエントリーポイントを読み込み\n最初のエントリー: {test_entrypoint['ticker']} {test_entrypoint['direction']} {test_entrypoint['amount']}ロット"
                requests.post(discord_key, json={"content": message})
                print("Discord通知を送信しました")
            except Exception as e:
                print(f"Discord通知エラー: {e}")
    
    print("\nテスト完了しました！")

async def main():
    """メイン関数"""
    await test_real_entrypoints()

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