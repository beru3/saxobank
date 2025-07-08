#!/usr/bin/env python3
"""
SAXOボット エントリーポイント読み込みテスト
スプレッドシートから曜日ごとのエントリーポイントを読み込むテスト
"""

import asyncio
import json
import sys
import os
from datetime import datetime

# SAXOlibをインポート
try:
    import SAXOlib
except ImportError:
    print("エラー: SAXOlib.pyが見つかりません")
    sys.exit(1)

# 設定ファイルパス
SETTINGS_FILE = "saxo_settings.json"

async def test_load_entrypoints():
    """エントリーポイントの読み込みをテスト"""
    print("===== SAXOボット エントリーポイント読み込みテスト =====")
    
    # 現在の日時と曜日を表示
    now = datetime.now()
    weekday_num = now.weekday()  # 0=月曜日, 1=火曜日, ..., 6=日曜日
    weekday_jp = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][weekday_num]
    print(f"現在日時: {now.strftime('%Y-%m-%d %H:%M:%S')} ({weekday_jp})")
    
    # 設定ファイルの読み込み
    if not os.path.exists(SETTINGS_FILE):
        print(f"エラー: 設定ファイル {SETTINGS_FILE} が見つかりません")
        return
    
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        print(f"✓ 設定ファイル {SETTINGS_FILE} を読み込みました")
    except Exception as e:
        print(f"設定ファイル読み込みエラー: {e}")
        return
    
    # エントリーポイントスプレッドシートのURLを取得
    entrypoints_url = settings.get("spreadsheets", {}).get("entrypoints_url", "")
    if not entrypoints_url:
        print("エントリーポイントスプレッドシートのURLが設定されていません。")
        return
    
    print(f"\nエントリーポイントを読み込み中: {entrypoints_url}")
    print(f"現在の曜日({weekday_jp})に対応するエントリーポイントを検索します...")
    
    try:
        # エントリーポイントを読み込み
        entrypoints = await SAXOlib.load_entrypoints_from_public_google_sheet(entrypoints_url)
        
        if not entrypoints:
            print("エントリーポイントが見つかりませんでした。")
            return
        
        # エントリーポイント情報を表示
        print("\n今日のエントリーポイント:")
        print("----------------------------")
        print("  通貨ペア  | エントリー | クローズ | 方向")
        print("----------------------------")
        for i, ep in enumerate(entrypoints):
            entry_time = ep["entry_time"].strftime("%H:%M")
            exit_time = ep["exit_time"].strftime("%H:%M")
            print(f"{i+1:2d}. {ep['ticker']:8s} | {entry_time:8s} | {exit_time:7s} | {ep['direction']}")
        
        print("\n読み込み成功！")
        print(f"合計 {len(entrypoints)} 件のエントリーポイントを読み込みました。")
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

async def main():
    await test_load_entrypoints()

if __name__ == "__main__":
    asyncio.run(main()) 