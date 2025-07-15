# SAXObot 仮想環境セットアップ

## 環境情報

- Python バージョン: 3.10.11
- 仮想環境ディレクトリ: `saxobot_venv`
- 必要なパッケージ: requirements.txtに記載

## インストール済みパッケージ

- saxo-openapi==0.6.0
- aiohttp==3.12.13
- playwright==1.53.0
- requests==2.32.4
- aiofiles==24.1.0

## 仮想環境の使用方法

### 仮想環境の有効化

```
# Windows (コマンドプロンプト)
saxobot_venv\Scripts\activate.bat

# Windows (PowerShell)
.\saxobot_venv\Scripts\Activate.ps1
```

### SAXObotの起動

仮想環境を有効化した後、以下のコマンドでSAXObotを起動できます：

```
python SAXObot.py
```

または、作成したバッチファイルを使用して起動することもできます：

```
run_saxobot.bat
```

## Playwrightについて

Playwrightは自動ブラウザ制御ライブラリで、OAuth認証に使用されています。
インストール済みのブラウザ: Chromium

## 注意事項

- OAuth認証を使用する場合、初回実行時にブラウザが起動し認証が必要です
- `saxo_settings.json`ファイルに適切な認証情報が設定されていることを確認してください
- シミュレーション環境とライブ環境の切り替えは`saxo_settings.json`の`is_live_mode`で設定できます 