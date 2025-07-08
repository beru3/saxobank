import asyncio
import logging
import requests
import csv
from io import StringIO
from datetime import datetime, timedelta
import aiohttp

logger = logging.getLogger(__name__)

#==========================================
# Bot設定データ読み込み（新配置対応版）
#==========================================

async def load_config(url: str) -> dict:
    """
    指定したCSVファイルからボットの設定情報を読み込みます。
    新しい配置に対応：OAuth認証情報も読み込み
    
    Parameters:
    - url (str): スプレッドシートのURL
    
    Returns:
    dict: ボットの設定情報を含む辞書
    """
    # スプレッドシートのIDをURLから抽出
    configspreadsheet_id = url.split("/d/")[1].split("/")[0]
   
    # CSV形式でスプレッドシートを取得
    csv_url1 = f"https://docs.google.com/spreadsheets/d/{configspreadsheet_id}/gviz/tq?tqx=out:csv"
    response1 = requests.get(csv_url1)
    response1.encoding = 'utf-8'  # エンコーディングをUTF-8に設定

    # CSVデータの読み込み
    csv_data1 = StringIO(response1.text)
    configreader = csv.reader(csv_data1)
    configdata = [row1 for row1 in configreader]

    # デバッグ：読み込んだデータを表示
    logger.info(f"設定データ行数: {len(configdata)}")
    
    if len(configdata) < 14:  # B14まで読み込む必要がある
        raise ValueError("設定データが不完全です。B14までのデータが必要です。")

    # 新配置に従ってデータを読み込み（B列 = インデックス1）
    try:
        # B14（LiveModeOnOff）の値を先に読み込む
        is_live_mode = False
        if len(configdata) >= 14 and len(configdata[13]) > 1:
            live_mode_value = configdata[13][1].strip()  # B14
            is_live_mode = live_mode_value.upper() == 'TRUE'
            logger.info(f"ライブモード設定: {live_mode_value} → {is_live_mode}")
        
        # 各設定値を読み込み（行インデックスは0ベース）
        record1 = {
            # OAuth認証情報（シミュレーション）
            'developer_id_sim': configdata[1][1].strip() if len(configdata[1]) > 1 else '',  # B2
            'developer_password_sim': configdata[2][1].strip() if len(configdata[2]) > 1 else '',  # B3
            'app_key_sim': configdata[3][1].strip() if len(configdata[3]) > 1 else '',  # B4
            'app_secret_sim': configdata[4][1].strip() if len(configdata[4]) > 1 else '',  # B5
            
            # OAuth認証情報（ライブ）
            'developer_id_live': configdata[5][1].strip() if len(configdata[5]) > 1 else '',  # B6
            'developer_password_live': configdata[6][1].strip() if len(configdata[6]) > 1 else '',  # B7
            'app_key_live': configdata[7][1].strip() if len(configdata[7]) > 1 else '',  # B8
            'app_secret_live': configdata[8][1].strip() if len(configdata[8]) > 1 else '',  # B9
            
            # その他の設定
            'max_error_count': int(configdata[9][1]) if len(configdata[9]) > 1 and configdata[9][1].strip() else 5,  # B10
            'Discord_key': configdata[10][1].strip() if len(configdata[10]) > 1 else '',  # B11
            'autolot': configdata[11][1].strip() if len(configdata[11]) > 1 else 'FALSE',  # B12
            'leverage': configdata[12][1].strip() if len(configdata[12]) > 1 else '1',  # B13
            'is_live_mode': is_live_mode,  # B14から取得済み
            
            # 後方互換性のため、現在の環境の認証情報も設定
            'userid': configdata[5][1].strip() if is_live_mode and len(configdata[5]) > 1 else configdata[1][1].strip() if len(configdata[1]) > 1 else '',
            'userpass': configdata[6][1].strip() if is_live_mode and len(configdata[6]) > 1 else configdata[2][1].strip() if len(configdata[2]) > 1 else ''
        }
        
        # 設定内容を表示（パスワードとシークレットは隠す）
        print("\n=== 読み込んだ設定（新配置） ===")
        print(f"環境モード: {'ライブ' if record1['is_live_mode'] else 'シミュレーション'}")
        print("\n[シミュレーション環境]")
        print(f"デベロッパーID: {record1['developer_id_sim']}")
        print(f"パスワード: {'*' * len(record1['developer_password_sim'])}")
        print(f"App Key: {record1['app_key_sim']}")
        print(f"App Secret: {'*' * len(record1['app_secret_sim'])}")
        print("\n[ライブ環境]")
        print(f"デベロッパーID: {record1['developer_id_live']}")
        print(f"パスワード: {'*' * len(record1['developer_password_live'])}")
        print(f"App Key: {record1['app_key_live']}")
        print(f"App Secret: {'*' * len(record1['app_secret_live'])}")
        print("\n[取引設定]")
        print(f"最大エラー回数: {record1['max_error_count']}")
        print(f"Discord Webhook: {'設定あり' if record1['Discord_key'] else '設定なし'}")
        print(f"オートロット: {record1['autolot']}")
        print(f"レバレッジ: {record1['leverage']}")
        print("========================\n")
        
        return record1
        
    except Exception as e:
        logger.error(f"設定データの解析エラー: {e}")
        logger.error(f"データ行数: {len(configdata)}")
        for i, row in enumerate(configdata[:15]):
            logger.error(f"行{i}: {row[:2] if len(row) >= 2 else row}")
        raise

#==========================================
# エントリーポイント読み込み（曜日対応版・改良）
#==========================================
async def load_entrypoints_from_public_google_sheet(url: str, test_weekday: int = None) -> list:
   """
   指定した公開Googleスプレッドシートからエントリーポイントの情報を読み込みます。
   曜日ごとのブロック対応版（改良）

    Parameters:
    - url (str): スプレッドシートのURL
    - test_weekday (int, optional): テスト用の曜日インデックス（0=月曜日, 1=火曜日, ..., 6=日曜日）

   Returns:
   list: エントリーポイントの情報を含む辞書のリスト
   """
   # スプレッドシートのIDをURLから抽出
   spreadsheet_id = url.split("/d/")[1].split("/")[0]
   
   # CSV形式でスプレッドシートを取得
   csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
   response = requests.get(csv_url)
   response.encoding = 'utf-8'  # エンコーディングをUTF-8に設定
   
   # CSVデータの読み込み
   csv_data = StringIO(response.text)
   reader = csv.reader(csv_data)
   data = [row for row in reader]
   
   # 現在の曜日を取得（テスト用の曜日が指定されていればそれを使用）
   now = datetime.now()
   if test_weekday is not None:
       weekday_num = test_weekday
       print(f"テスト用の曜日を使用: インデックス {test_weekday}")
   else:
       weekday_num = now.weekday()  # 0=月曜日, 1=火曜日, ..., 6=日曜日
   
   current_day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weekday_num]
   current_day_jp = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][weekday_num]
   
   print(f"現在の曜日: {current_day_jp} ({now.strftime('%Y-%m-%d')})")
   
   # データの解析
   blocks = []  # ブロック（曜日）ごとのデータを格納
   current_block = []
   in_block = False
   
   # ヘッダー検出条件を拡張（通貨ペアが含まれる行、またはエントリが2列目にある行）
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
   
   # ブロックを検出（ヘッダー行と合計行で区切る）
   for i, row in enumerate(data):
       # 空行はスキップ
       if not row or not any(cell.strip() for cell in row):
           continue
           
       # ヘッダー行を検出（拡張条件）
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
   
   # 曜日の順番（月〜金）
   weekdays = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日"]
   
   # 現在の曜日に対応するブロックを選択
   target_block = None
   
   # 各ブロックは曜日ごとのデータ。月曜日は1番目のブロック、火曜日は2番目のブロック、...
   if 0 <= weekday_num <= 4:  # 月〜金
       block_index = weekday_num  # 曜日インデックスをそのまま使用
       if len(blocks) > block_index:
           target_block = blocks[block_index]
           print(f"現在の曜日 {current_day_jp} に対応するブロック（{block_index + 1}番目）を使用します")
           
           # ブロックのヘッダー情報を表示
           if target_block and len(target_block) > 0:
               print(f"ブロックヘッダー: {target_block[0]}")
   
   # 該当するブロックがない場合は最初のブロックを使用
   if target_block is None and blocks:
       target_block = blocks[0]
       print(f"現在の曜日に対応するブロックが見つからないため、最初のブロック（{weekdays[0]}）を使用します")
       if len(target_block) > 0:
           print(f"ブロックヘッダー: {target_block[0]}")
   
   if not target_block:
       logger.warning("有効なブロックが見つかりませんでした")
       return []
   
   # ヘッダー行をスキップ
   data_rows = target_block[1:]  # ヘッダー行をスキップ
   
   # エントリーポイントを解析
   new_data = []
   for idx, row in enumerate(data_rows):
       try:
           # 合計行をスキップ
           if len(row) > 0 and row[0].strip() == "合計":
               continue
               
           # 列の位置を特定
           ticker_col = 0  # 通貨ペア列
           entry_col = 1   # エントリー時間列
           close_col = 2   # クローズ時間列
           direction_col = 3  # 方向列
           
           # 必要なデータが揃っているか確認
           if len(row) <= max(ticker_col, entry_col, close_col, direction_col):
               continue
               
           # 空の行はスキップ
           if not row[ticker_col].strip():
               continue
               
           # 時間形式を解析（HH:MM形式）
           entry_time_str = row[entry_col].strip()
           close_time_str = row[close_col].strip()
           
           # 空の場合はスキップ
           if not entry_time_str or not close_time_str:
               continue
               
           # 時間と分に分割
           entry_hour, entry_minute = map(int, entry_time_str.split(':'))
           close_hour, close_minute = map(int, close_time_str.split(':'))
           
           # 現在の日付で日時オブジェクトを作成
           entry_time = await convert_nums_to_datetime(entry_hour, entry_minute, 0)
           exit_time = await convert_nums_to_datetime(close_hour, close_minute, 0)
           
           # 方向を標準化（BUY/SELL形式に変換）
           direction = row[direction_col].strip().upper()
           if direction in ["SHORT", "S", "SELL", "売り"]:
               direction = "SELL"
           elif direction in ["LONG", "L", "BUY", "買い"]:
               direction = "BUY"
           else:
               logger.warning(f"行{idx+2} - 不明な取引方向: {direction}、スキップします")
               continue
           
           # 通貨ペアをSAXO形式に変換（例：USDJPY → USD_JPY）
           ticker = convert_ticker_format(row[ticker_col].strip())
           
           # エントリーポイントレコードを作成
           record = {
               "entry_time": entry_time,  # エントリー時間
               "exit_time": exit_time,    # イグジット時間
               "ticker": ticker,          # 通貨ペア
               "direction": direction,    # BUY/SELL
               "amount": 0.1,             # デフォルトlot（設定ファイルから上書き可能）
               "LimitRate": 0,            # 指し値（成行）
               "StopRate": 0,             # 逆指し値（なし）
               "wait_exittime": "FALSE",  # 判定待機
               "save_screenshot": "FALSE", # スクショ
               "line_notify": "TRUE",     # 通知
               "memo": f"{current_day_jp} {entry_time_str}-{close_time_str} {direction}", # memo（曜日情報を追加）
               "orderid": "",             # オーダーID
               "idcalc": ""               # オーダーID作成用
           }
           
           # エントリー時刻とエグジット時刻をタプルとしてnew_dataに追加
           new_data.append(record)

       except ValueError as e:
           logger.error(f"行{idx+2} - 時刻変換エラー: {e}")
           logger.error(f"データ: {row}")
           continue
       except Exception as e:
           logger.error(f"行{idx+2} - データ解析エラー: {e}")
           logger.error(f"データ: {row}")
           continue

   if not new_data:
       logger.warning(f"{current_day_jp}のエントリーポイントが見つかりませんでした。")
       return []

   # エントリー時刻でソート（時間の昇順）
   sorted_data = sorted(new_data, key=lambda x: (x["entry_time"].hour, x["entry_time"].minute))
   return sorted_data

#==========================================
# Discord通知
#==========================================

async def send_discord_message(line_notify_token: str,
                      message: str,
                      image_path: str = None) -> None:
    """
    Discord webhookを用いてメッセージを送信する。
    Args:
        line_notify_token (str): Discord Webhook Urlにします
        message (str): 送信するメッセージ。
        image_path (str, optional): 送信する画像のパス。デフォルトはNone。
    """
    discord_webhook_url = line_notify_token
    data = {"content": message}
    files = None
    if image_path is not None:
        with open(image_path, "rb") as image_file:
            files = { "imageFile": image_file }
            response = requests.post(
                discord_webhook_url,
                data=data,
                files=files)
    else:
        response = requests.post(
            discord_webhook_url,
            data=data)

#==========================================
# トレンド分析
#==========================================

async def trend_get(symbol: str):
    """
    現在のトレンド方向を取得（SAXO対応版）
    移動平均線のクロスオーバーを使用してトレンドを判定
    
    Args:
        symbol (str): 取引ペア (例: "USD_JPY")
        
    Returns:
        int: トレンド方向 (1: 上昇, -1: 下降, 0: レンジ)
        str: トレンド情報の説明
    """
    try:
        # 実際のSAXO APIでは過去の価格データを取得して移動平均を計算する
        # この実装では簡易的に時間帯によってトレンドを判断
        # 実際の実装では、以下のような処理を行う：
        # 1. 過去の価格データを取得
        # 2. 短期と長期の移動平均を計算
        # 3. クロスオーバーを検出してトレンドを判断
        
        # 現在時刻に基づいた疑似トレンド判定（デモ用）
        now = datetime.now()
        hour = now.hour
        
        # 時間帯によって異なるトレンドを返す
        if 0 <= hour < 8:  # 深夜〜早朝: アジア時間
            trend = 0
            trend_info = "アジア時間帯はレンジ相場が多い"
        elif 8 <= hour < 16:  # 朝〜昼: ヨーロッパ時間
            if symbol.startswith("EUR"):
                trend = 1
                trend_info = "ヨーロッパ時間はEURが強い傾向"
            else:
                trend = -1
                trend_info = "ヨーロッパ時間はドル売りが多い"
        else:  # 夕方〜夜: 米国時間
            if symbol.startswith("USD"):
                trend = 1
                trend_info = "米国時間はドル買いが多い"
            else:
                trend = -1
                trend_info = "米国時間は他通貨売りが多い"
        
        # 曜日による調整
        weekday = now.weekday()  # 0=月曜日, 6=日曜日
        if weekday >= 5:  # 週末
            trend = 0
            trend_info = "週末はボラティリティが低い"
        
        logger.info(f"トレンド判定: {symbol} = {trend} ({trend_info})")
        return trend, trend_info
        
    except Exception as e:
        logger.error(f"トレンド取得エラー: {e}")
        return 0, "トレンド判定エラー"  # エラー時はレンジとして扱う

#==========================================
# ユーティリティ
#==========================================

async def wait_until(target_time: datetime, preparation_time: int = 0, raise_exception: bool = True):
    """
    指定された時間まで待機する。

    Args:
        target_time (datetime): 目標時間。
        preparation_time (int, optional): 準備時間（秒）。デフォルトは0。
        raise_exception (bool): 時刻超過時に例外を発生させるかどうか。デフォルトはTrue。
    """
    sleep_seconds = (target_time - timedelta(seconds=preparation_time) - datetime.now()).total_seconds()
    if sleep_seconds > 0:
        await asyncio.sleep(sleep_seconds)
    elif raise_exception:
        raise ValueError(f'エントリ－時間を超過している({sleep_seconds}秒)')
    else:
        # 時刻が過ぎているが例外を発生させない場合
        logger.warning(f'エントリー時間を超過している({sleep_seconds}秒) - スキップします')

#==========================================
# 時刻変換ユーティリティ（修正版）
#==========================================
async def convert_nums_to_datetime(
        hour: int, minute: int, second: int) -> datetime:
    """
    与えられた時、分、秒を使用して日時オブジェクトを生成します。
    常に現在の日付を使用し、過去の時刻でも翌日に設定しません。
    
    Parameters:
    - hour (int): 時
    - minute (int): 分
    - second (int): 秒
    
    Returns:
    datetime.datetime: 生成された日時オブジェクト
    """
    # 入力値の検証
    if not (0 <= hour <= 23):
        raise ValueError(f"時間が無効です: {hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"分が無効です: {minute}")
    if not (0 <= second <= 59):
        raise ValueError(f"秒が無効です: {second}")
    
    now = datetime.now()
    
    # デバッグログ
    logger.debug(f"現在時刻: {now}, 指定時刻: {hour}:{minute}:{second}")
    
    # 常に現在の日付を使用
    specified_time = datetime(now.year, now.month, now.day, hour, minute, second)
    
    # 過去の時刻かどうかをログに記録
    if now > specified_time:
        logger.debug(f"過去の時刻ですが、現在の日付のまま使用します: {specified_time}")
    
    return specified_time

#==========================================
# デバッグ用：CSVデータ構造を確認する関数
#==========================================
async def debug_csv_structure(url: str):
    """
    CSVデータの構造をデバッグ表示する
    
    Parameters:
    - url (str): スプレッドシートのURL
    """
    # スプレッドシートのIDをURLから抽出
    spreadsheet_id = url.split("/d/")[1].split("/")[0]
    
    # CSV形式でスプレッドシートを取得
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
    response = requests.get(csv_url)
    response.encoding = 'utf-8'
    
    # CSVデータの読み込み
    csv_data = StringIO(response.text)
    reader = csv.reader(csv_data)
    
    print("=== CSVデータ構造のデバッグ ===")
    for i, row in enumerate(reader):
        if i == 0:
            print(f"ヘッダー行: {row}")
        else:
            print(f"データ行{i}: {row[:20]}")  # 最初の20列を表示
            if i >= 5:  # 最初の5行だけ表示
                break
    print("=================================")
    
#==========================================
# SAXO証券API用ヘルパー関数
#==========================================

def convert_ticker_format(ticker: str, to_saxo: bool = True) -> str:
    """
    通貨ペアのフォーマットを変換
    
    Args:
        ticker (str): 通貨ペア
        to_saxo (bool): True: GMO形式→SAXO形式, False: SAXO形式→GMO形式
        
    Returns:
        str: 変換後の通貨ペア
    """
    if to_saxo:
        # USD_JPY → USDJPY
        return ticker.replace("_", "")
    else:
        # USDJPY → USD_JPY (6文字の場合のみ)
        if len(ticker) == 6:
            return f"{ticker[:3]}_{ticker[3:]}"
        return ticker

def calculate_pip_value(ticker: str) -> tuple:
    """
    通貨ペアのpip計算用の倍率を取得
    
    Args:
        ticker (str): 通貨ペア
        
    Returns:
        tuple: (multiply, gmultiply) - pip計算用の倍率
    """
    if ticker[-3:] != "JPY":
        return (10000, 100000)
    else:
        return (100, 1000)

async def get_historical_prices(client, ticker: str, horizon: int = 60, count: int = 100):
    """
    ヒストリカル価格データを取得（将来的な実装用）
    
    Args:
        client: SAXOクライアント
        ticker (str): 通貨ペア
        horizon (int): 時間軸（分）
        count (int): 取得するデータ数
        
    Returns:
        list: 価格データのリスト
    """
    # 将来的にSAXO証券のチャートAPIが利用可能になった場合の実装
    # 現在は空のリストを返す
    return []
