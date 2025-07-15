# SAXObot - SAXO証券FX自動取引システム

SAXObotは、SAXO証券のAPIを使用したFX自動取引システムです。Googleスプレッドシートからエントリーポイントを読み込み、指定時間に自動エントリーと決済を実行します。

## 機能

- **自動エントリー**: Googleスプレッドシートからエントリーポイントを読み込み、指定時間に自動エントリー
- **自動決済**: 設定された決済時間にポジションを自動クローズ
- **Discord通知**: 取引状況をリアルタイムでDiscordに通知
- **トレンド検出**: 時間帯に基づく移動平均クロスオーバー方式
- **OAuth認証**: SAXO証券APIへの安全な認証

## セットアップ

### 1. 環境構築

```bash
# 仮想環境の作成
python -m venv saxobot_env_py39

# 仮想環境の有効化（Windows）
saxobot_env_py39\Scripts\activate

# 依存関係のインストール
pip install -r requirements.txt
```

### 2. 設定ファイル

`saxo_settings.json`を編集して、以下の設定を行ってください：

```json
{
    "saxo_username": "your_username",
    "saxo_password": "your_password",
    "discord_webhook_url": "your_discord_webhook_url",
    "spreadsheet_id": "your_google_spreadsheet_id"
}
```

### 3. Googleスプレッドシートの設定

エントリーポイント用のスプレッドシートを作成し、以下の列を含めてください：
- 日付
- 時間
- 通貨ペア
- エントリー方向（BUY/SELL）
- 決済時間

## 使用方法

### 手動実行

```bash
# 仮想環境を有効化
saxobot_env_py39\Scripts\activate

# SAXObotを実行
python SAXObot.py
```

### 自動実行（Windowsタスクスケジューラ）

1. `SAXOtrade.bat`ファイルを編集して、正しいパスを設定
2. Windowsタスクスケジューラで毎朝実行するように設定

## ファイル構成

```
SAXObot/
├── SAXObot.py              # メイン実行ファイル
├── SAXOlib.py              # SAXO証券API操作ライブラリ
├── saxo_token_oauth.py     # OAuth認証処理
├── saxo_token_async.py     # 従来の認証処理
├── saxo_settings.json      # 設定ファイル
├── requirements.txt        # 依存関係
├── tests/                  # テストファイル
│   ├── test_entry.py       # 基本エントリーテスト
│   ├── test_spreadsheet_entry.py  # スプレッドシート読み込みテスト
│   ├── test_manual_entry.py       # 手動エントリーテスト
│   ├── test_real_entrypoints.py   # 実際のエントリーポイントテスト
│   ├── test_entrypoints_only.py   # エントリーポイントのみテスト
│   ├── test_load_entrypoints.py   # エントリーポイント読み込みテスト
│   └── setup_saxo.py       # セットアップスクリプト
├── scripts/                # 実行スクリプト
│   ├── run_saxobot.bat     # SAXObot実行バッチ
│   └── SAXOtrade.bat       # 自動実行用バッチ
└── docs/                   # ドキュメント
    ├── README.md           # このファイル
    ├── SAXOBOT_ENV_README.md  # 環境構築ガイド
    └── SAXO bot インストール方法SAXO設定編.pdf  # インストールガイド
```

## 注意事項

- 本システムはデモ環境でのテストを推奨します
- 実際の取引には十分なテストとリスク管理が必要です
- APIキーやパスワードは安全に管理してください

## ライセンス

このプロジェクトは個人使用を目的としています。 