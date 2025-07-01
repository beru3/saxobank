#!/usr/bin/env python3
"""
スプレッドシートのブロック検出問題を調査するためのデバッグスクリプト
"""

import asyncio
import csv
import requests
from io import StringIO
from datetime import datetime

async def debug_blocks(url):
    """スプレッドシートのブロック検出をデバッグ"""
    print(f"=== スプレッドシート ブロック検出デバッグ ===")
    print(f"URL: {url}")
    
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
    
    print(f"読み込んだ行数: {len(data)}")
    
    # 最初の10行を表示
    print("\n最初の10行:")
    for i, row in enumerate(data[:10]):
        print(f"行{i+1}: {row}")
    
    # 現在の曜日を取得
    now = datetime.now()
    weekday_num = now.weekday()  # 0=月曜日, 1=火曜日, ..., 6=日曜日
    current_day_jp = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][weekday_num]
    
    print(f"\n現在の曜日: {current_day_jp} (インデックス: {weekday_num})")
    
    # ブロックを検出（修正版）
    blocks = []
    current_block = []
    in_block = False
    
    print("\n=== ブロック検出（現在のロジック） ===")
    print("「通貨ペア」を含む行をヘッダーとして検出")
    
    for i, row in enumerate(data):
        # 空行はスキップ
        if not row or not any(cell.strip() for cell in row):
            print(f"行{i+1}: 空行をスキップ")
            continue
        
        # 行の内容を表示
        print(f"行{i+1}: {row}")
        
        # ヘッダー行を検出（通貨ペアが含まれる行）
        if len(row) > 0 and "通貨ペア" in row[0].strip():
            print(f"行{i+1}: ヘッダー行を検出 -> {row[0]}")
            # 新しいブロックの開始
            if current_block:
                blocks.append(current_block)
                print(f"  -> 前のブロック（{len(current_block)}行）を保存")
            current_block = [row]
            in_block = True
            continue
        
        # 合計行を検出
        if len(row) > 0 and row[0].strip() == "合計":
            print(f"行{i+1}: 合計行を検出 -> {row[0]}")
            # ブロックの終了
            if in_block:
                current_block.append(row)
                blocks.append(current_block)
                print(f"  -> 現在のブロック（{len(current_block)}行）を保存")
                current_block = []
                in_block = False
            continue
        
        # ブロック内のデータ行
        if in_block:
            current_block.append(row)
            print(f"行{i+1}: ブロック内のデータ行を追加")
    
    # 最後のブロックを追加
    if current_block:
        blocks.append(current_block)
        print(f"最後のブロック（{len(current_block)}行）を保存")
    
    print(f"\n検出したブロック数: {len(blocks)}")
    
    # 各ブロックの内容を表示
    for i, block in enumerate(blocks):
        print(f"\nブロック {i+1} ({len(block)}行):")
        print(f"  ヘッダー: {block[0]}")
        print(f"  データ行数: {len(block)-1}")
        if len(block) > 1:
            print(f"  最初のデータ行: {block[1]}")
    
    # 修正案：ヘッダー検出条件を変更
    print("\n=== ブロック検出（修正案） ===")
    print("最初の列に「通貨ペア」という文字列が含まれるか、または「エントリ」が2列目にある行をヘッダーとして検出")
    
    blocks_alt = []
    current_block = []
    in_block = False
    
    for i, row in enumerate(data):
        # 空行はスキップ
        if not row or not any(cell.strip() for cell in row):
            continue
        
        # ヘッダー行を検出（通貨ペアが含まれる行、または2列目がエントリの行）
        is_header = False
        if len(row) > 0:
            if "通貨ペア" in row[0].strip():
                is_header = True
                print(f"行{i+1}: 「通貨ペア」を含むヘッダー行を検出")
            elif len(row) > 1 and row[1].strip() == "エントリ":
                is_header = True
                print(f"行{i+1}: 「エントリ」を含むヘッダー行を検出")
        
        if is_header:
            # 新しいブロックの開始
            if current_block:
                blocks_alt.append(current_block)
            current_block = [row]
            in_block = True
            continue
        
        # 合計行を検出
        if len(row) > 0 and row[0].strip() == "合計":
            # ブロックの終了
            if in_block:
                current_block.append(row)
                blocks_alt.append(current_block)
                current_block = []
                in_block = False
            continue
        
        # ブロック内のデータ行
        if in_block:
            current_block.append(row)
    
    # 最後のブロックを追加
    if current_block:
        blocks_alt.append(current_block)
    
    print(f"\n修正案で検出したブロック数: {len(blocks_alt)}")
    
    # 各ブロックの内容を表示
    for i, block in enumerate(blocks_alt):
        print(f"\nブロック {i+1} ({len(block)}行):")
        print(f"  ヘッダー: {block[0]}")
        print(f"  データ行数: {len(block)-1}")
        if len(block) > 1:
            print(f"  最初のデータ行: {block[1]}")
            print(f"  最後のデータ行: {block[-1]}")
    
    # 現在の曜日に対応するブロックを選択
    if 0 <= weekday_num < len(blocks_alt):
        target_block = blocks_alt[weekday_num]
        print(f"\n現在の曜日 {current_day_jp} に対応するブロック（{weekday_num + 1}番目）:")
        if len(target_block) > 1:
            print(f"  データ行数: {len(target_block)-1}")
            for i, row in enumerate(target_block[1:6]):  # 最初の5行だけ表示
                print(f"  データ{i+1}: {row}")

async def main():
    url = "https://docs.google.com/spreadsheets/d/17GdaxR8q0qTx19TOWva62ksdRWIxHrmRZkwXz6lTfgM/edit?gid=0"
    await debug_blocks(url)

if __name__ == "__main__":
    asyncio.run(main()) 