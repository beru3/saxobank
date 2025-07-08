#!/usr/bin/env python3
"""
SAXOボットのエントリーポイント読み込み機能をテストするスクリプト
曜日ごとのブロック検出機能を確認
"""

import asyncio
import sys
from datetime import datetime
from SAXOlib import load_entrypoints_from_public_google_sheet

async def test_load_entrypoints_for_weekday(weekday_num):
    """指定した曜日のエントリーポイント読み込み機能のテスト"""
    # テスト用のスプレッドシートURL
    url = "https://docs.google.com/spreadsheets/d/17GdaxR8q0qTx19TOWva62ksdRWIxHrmRZkwXz6lTfgM/edit?gid=0"
    
    # 曜日名
    weekday_names = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    current_day_jp = weekday_names[weekday_num]
    
    print(f"\n=== {current_day_jp} (インデックス: {weekday_num}) のエントリーポイントテスト ===")
    
    # エントリーポイントを読み込み（test_weekdayパラメータを使用）
    try:
        entry_points = await load_entrypoints_from_public_google_sheet(url, test_weekday=weekday_num)
        
        # 通貨ペア別のカウント
        currency_pairs = {}
        directions = {"BUY": 0, "SELL": 0}
        
        # エントリーポイント情報を表示
        print(f"\n{current_day_jp}のエントリーポイント一覧:")
        print("--------------------------------------------------------------")
        print("  通貨ペア  |  エントリー  |  クローズ  |  方向  |  メモ")
        print("--------------------------------------------------------------")
        
        for i, entry in enumerate(entry_points):
            # 通貨ペアのカウントを更新
            if entry["ticker"] not in currency_pairs:
                currency_pairs[entry["ticker"]] = 0
            currency_pairs[entry["ticker"]] += 1
            
            # 方向のカウントを更新
            directions[entry["direction"]] += 1
            
            # エントリー情報を表示
            print(f"{i+1:2d}. {entry['ticker']:8s} | {entry['entry_time'].strftime('%H:%M:%S')} | {entry['exit_time'].strftime('%H:%M:%S')} | {entry['direction']:4s} | {entry['memo']}")
        
        print("--------------------------------------------------------------")
        
        # 統計情報を表示
        print(f"\n{current_day_jp}の統計情報:")
        print(f"合計エントリーポイント: {len(entry_points)}")
        print(f"通貨ペア別カウント: {currency_pairs}")
        print(f"方向別カウント: BUY {directions['BUY']}件, SELL {directions['SELL']}件")
        
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

async def find_blocks_with_header(url, header_pattern=None):
    """
    特定のヘッダーパターンを持つブロックを検索する
    
    Parameters:
    - url (str): スプレッドシートのURL
    - header_pattern (list): 検索するヘッダーパターン（例: ['通貨ペア', '', '', '方向']）
    
    Returns:
    - list: 見つかったブロックのリスト
    """
    import requests
    from io import StringIO
    import csv
    
    print(f"\n=== ヘッダーパターン検索 ===")
    if header_pattern:
        print(f"検索パターン: {header_pattern}")
    
    # スプレッドシートのIDをURLから抽出
    spreadsheet_id = url.split("/d/")[1].split("/")[0]
    
    # CSV形式でスプレッドシートを取得
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
    response = requests.get(csv_url)
    response.encoding = 'utf-8'
    
    # CSVデータの読み込み
    csv_data = StringIO(response.text)
    reader = csv.reader(csv_data)
    data = [row for row in reader]
    
    # ブロック検出
    blocks = []
    current_block = []
    in_block = False
    
    # ヘッダー検出条件
    def is_header_row(row):
        if len(row) == 0:
            return False
        # 1列目に「通貨ペア」が含まれる
        if "通貨ペア" in row[0].strip():
            return True
        # 2列目が「エントリ」
        if len(row) > 1 and row[1].strip() == "エントリ":
            return True
        return False
    
    # ブロックを検出
    for i, row in enumerate(data):
        # 空行はスキップ
        if not row or not any(cell.strip() for cell in row):
            continue
            
        # ヘッダー行を検出
        if is_header_row(row):
            # 新しいブロックの開始
            if current_block:
                blocks.append(current_block)
            current_block = [row]
            in_block = True
            continue
            
        # 合計行を検出
        if len(row) > 0 and row[0].strip() == "合計":
            # ブロックの終了
            if in_block:
                current_block.append(row)
                blocks.append(current_block)
                current_block = []
                in_block = False
            continue
            
        # ブロック内のデータ行
        if in_block:
            current_block.append(row)
    
    # 最後のブロックを追加
    if current_block:
        blocks.append(current_block)
    
    print(f"検出したブロック数: {len(blocks)}")
    
    # ヘッダーパターンに一致するブロックを検索
    matching_blocks = []
    if header_pattern:
        for i, block in enumerate(blocks):
            if len(block) > 0:
                header = block[0]
                # ヘッダーパターンとの照合
                match = True
                for j, pattern in enumerate(header_pattern):
                    if j >= len(header) or (pattern and pattern != header[j]):
                        match = False
                        break
                
                if match:
                    matching_blocks.append((i, block))
                    print(f"ブロック {i+1} がパターンに一致: {header}")
    
    return matching_blocks

async def main():
    print("=== SAXOボット 曜日別エントリーポイント読み込みテスト ===")
    
    # テスト用のスプレッドシートURL
    url = "https://docs.google.com/spreadsheets/d/17GdaxR8q0qTx19TOWva62ksdRWIxHrmRZkwXz6lTfgM/edit?gid=0"
    
    # 実際の現在の曜日を表示
    now = datetime.now()
    weekday_num = now.weekday()
    weekday_names = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    print(f"実際の現在の曜日: {weekday_names[weekday_num]} (インデックス: {weekday_num})")
    
    # 特定のヘッダーパターンを持つブロックを検索
    header_pattern = ['通貨ペア', '', '', '方向']
    matching_blocks = await find_blocks_with_header(url, header_pattern)
    
    if matching_blocks:
        print(f"\n特定のヘッダーパターンを持つブロックが {len(matching_blocks)} 個見つかりました")
        for i, (block_index, block) in enumerate(matching_blocks):
            print(f"ブロック {block_index+1}:")
            print(f"  ヘッダー: {block[0]}")
            print(f"  データ行数: {len(block)-1}")
            if len(block) > 1:
                print(f"  最初のデータ行: {block[1]}")
                print(f"  最後のデータ行: {block[-1]}")
    
    # 月曜日から金曜日までのエントリーポイントをテスト
    results = []
    for day in range(5):  # 0=月曜日, 1=火曜日, ..., 4=金曜日
        result = await test_load_entrypoints_for_weekday(day)
        results.append(result)
    
    # 結果の概要を表示
    print("\n=== テスト結果概要 ===")
    for day in range(5):
        status = "成功" if results[day] else "失敗"
        print(f"{weekday_names[day]}: {status}")
    
    # すべてのテストが成功したかどうかを確認
    all_success = all(results)
    sys.exit(0 if all_success else 1)

if __name__ == "__main__":
    asyncio.run(main()) 