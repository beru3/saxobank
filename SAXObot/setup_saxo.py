#!/usr/bin/env python3
"""
SAXO証券 FXBot セットアップスクリプト
設定情報を対話形式で入力し、saxo_settings.jsonに保存します
"""

import json
import os
import sys

def load_settings():
    """既存の設定を読み込む"""
    if os.path.exists('saxo_settings.json'):
        try:
            with open('saxo_settings.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"設定ファイルの読み込みエラー: {e}")
    
    # デフォルト設定
    return {
        "developer_account": {
            "sim": {
                "developer_id": "",
                "developer_password": ""
            },
            "live": {
                "developer_id": "",
                "developer_password": ""
            }
        },
        "application": {
            "sim": {
                "app_key": "",
                "app_secret": ""
            },
            "live": {
                "app_key": "",
                "app_secret": ""
            }
        },
        "trading": {
            "is_live_mode": False,
            "leverage": 1,
            "autolot": False,
            "max_error_count": 5
        },
        "notification": {
            "discord_webhook_url": ""
        },
        "spreadsheets": {
            "config_url": "",
            "entrypoints_url": ""
        },
        "oauth": {
            "live": {
                "auth_endpoint": "https://live.logonvalidation.net/authorize",
                "token_endpoint": "https://live.logonvalidation.net/token",
                "redirect_uri": "http://localhost:8080/callback"
            },
            "sim": {
                "auth_endpoint": "https://sim.logonvalidation.net/authorize",
                "token_endpoint": "https://sim.logonvalidation.net/token",
                "redirect_uri": "http://localhost"
            }
        }
    }

def save_settings(settings):
    """設定をファイルに保存"""
    try:
        with open('saxo_settings.json', 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        print("\n✅ 設定を saxo_settings.json に保存しました")
    except Exception as e:
        print(f"設定ファイルの保存エラー: {e}")

def get_input(prompt, default=""):
    """ユーザー入力を取得（デフォルト値付き）"""
    if default:
        result = input(f"{prompt} [{default}]: ")
        return result if result else default
    else:
        return input(f"{prompt}: ")

def get_boolean_input(prompt, default=False):
    """真偽値の入力を取得"""
    default_str = "y" if default else "n"
    result = input(f"{prompt} (y/n) [{default_str}]: ").lower()
    if not result:
        return default
    return result.startswith('y')

def setup_developer_account(settings):
    """開発者アカウント情報の設定"""
    print("\n=== SAXO開発者アカウント情報 ===")
    
    # シミュレーション環境
    print("\n[シミュレーション環境]")
    settings["developer_account"]["sim"]["developer_id"] = get_input(
        "デベロッパーID（メールアドレス）",
        settings["developer_account"]["sim"]["developer_id"]
    )
    settings["developer_account"]["sim"]["developer_password"] = get_input(
        "デベロッパーパスワード",
        settings["developer_account"]["sim"]["developer_password"]
    )
    
    # ライブ環境
    print("\n[ライブ環境]")
    settings["developer_account"]["live"]["developer_id"] = get_input(
        "デベロッパーID（メールアドレス）",
        settings["developer_account"]["live"]["developer_id"]
    )
    settings["developer_account"]["live"]["developer_password"] = get_input(
        "デベロッパーパスワード",
        settings["developer_account"]["live"]["developer_password"]
    )

def setup_application(settings):
    """アプリケーション認証情報の設定"""
    print("\n=== アプリケーション認証情報 ===")
    
    # シミュレーション環境
    print("\n[シミュレーション環境]")
    settings["application"]["sim"]["app_key"] = get_input(
        "App Key",
        settings["application"]["sim"]["app_key"]
    )
    settings["application"]["sim"]["app_secret"] = get_input(
        "App Secret",
        settings["application"]["sim"]["app_secret"]
    )
    
    # ライブ環境
    print("\n[ライブ環境]")
    settings["application"]["live"]["app_key"] = get_input(
        "App Key",
        settings["application"]["live"]["app_key"]
    )
    settings["application"]["live"]["app_secret"] = get_input(
        "App Secret",
        settings["application"]["live"]["app_secret"]
    )

def setup_oauth(settings):
    """OAuth設定"""
    print("\n=== OAuth設定 ===")
    
    # シミュレーション環境
    print("\n[シミュレーション環境]")
    settings["oauth"]["sim"]["auth_endpoint"] = get_input(
        "認証エンドポイント",
        settings["oauth"]["sim"]["auth_endpoint"]
    )
    settings["oauth"]["sim"]["token_endpoint"] = get_input(
        "トークンエンドポイント",
        settings["oauth"]["sim"]["token_endpoint"]
    )
    settings["oauth"]["sim"]["redirect_uri"] = get_input(
        "リダイレクトURI",
        settings["oauth"]["sim"]["redirect_uri"]
    )
    
    # ライブ環境
    print("\n[ライブ環境]")
    settings["oauth"]["live"]["auth_endpoint"] = get_input(
        "認証エンドポイント",
        settings["oauth"]["live"]["auth_endpoint"]
    )
    settings["oauth"]["live"]["token_endpoint"] = get_input(
        "トークンエンドポイント",
        settings["oauth"]["live"]["token_endpoint"]
    )
    settings["oauth"]["live"]["redirect_uri"] = get_input(
        "リダイレクトURI",
        settings["oauth"]["live"]["redirect_uri"]
    )

def setup_trading(settings):
    """取引設定"""
    print("\n=== 取引設定 ===")
    
    settings["trading"]["is_live_mode"] = get_boolean_input(
        "ライブ環境を使用しますか？",
        settings["trading"]["is_live_mode"]
    )
    
    leverage_str = get_input(
        "レバレッジ",
        str(settings["trading"]["leverage"])
    )
    try:
        settings["trading"]["leverage"] = int(leverage_str)
    except ValueError:
        print("警告: レバレッジは整数値である必要があります。デフォルト値を使用します。")
    
    settings["trading"]["autolot"] = get_boolean_input(
        "自動ロットサイズを使用しますか？",
        settings["trading"]["autolot"]
    )
    
    max_error_str = get_input(
        "最大エラー回数",
        str(settings["trading"]["max_error_count"])
    )
    try:
        settings["trading"]["max_error_count"] = int(max_error_str)
    except ValueError:
        print("警告: エラー回数は整数値である必要があります。デフォルト値を使用します。")

def setup_notification(settings):
    """通知設定"""
    print("\n=== 通知設定 ===")
    
    settings["notification"]["discord_webhook_url"] = get_input(
        "Discord Webhook URL",
        settings["notification"]["discord_webhook_url"]
    )

def setup_spreadsheets(settings):
    """スプレッドシート設定"""
    print("\n=== スプレッドシート設定 ===")
    
    settings["spreadsheets"]["config_url"] = get_input(
        "設定スプレッドシートURL",
        settings["spreadsheets"]["config_url"]
    )
    settings["spreadsheets"]["entrypoints_url"] = get_input(
        "エントリーポイントスプレッドシートURL",
        settings["spreadsheets"]["entrypoints_url"]
    )

def update_config_files(settings):
    """設定ファイルを更新"""
    try:
        # saxo_token_oauth.pyの更新
        if os.path.exists('saxo_token_oauth.py'):
            with open('saxo_token_oauth.py', 'r', encoding='utf-8') as f:
                content = f.read()
            
            # DEFAULT_CONFIG_URLの更新
            if settings["spreadsheets"]["config_url"]:
                import re
                pattern = r'DEFAULT_CONFIG_URL\s*=\s*"[^"]*"'
                replacement = f'DEFAULT_CONFIG_URL = "{settings["spreadsheets"]["config_url"]}"'
                content = re.sub(pattern, replacement, content)
                
                with open('saxo_token_oauth.py', 'w', encoding='utf-8') as f:
                    f.write(content)
                print("✅ saxo_token_oauth.py を更新しました")
        
        # saxo_token_async.pyの更新
        if os.path.exists('saxo_token_async.py'):
            with open('saxo_token_async.py', 'r', encoding='utf-8') as f:
                content = f.read()
            
            # sheet_idの更新
            if settings["spreadsheets"]["config_url"]:
                import re
                # スプレッドシートIDを抽出
                sheet_id = settings["spreadsheets"]["config_url"].split("/d/")[1].split("/")[0] if "/d/" in settings["spreadsheets"]["config_url"] else ""
                if sheet_id:
                    pattern = r'sheet_id\s*=\s*"[^"]*"'
                    replacement = f'sheet_id = "{sheet_id}"'
                    content = re.sub(pattern, replacement, content)
                    
                    with open('saxo_token_async.py', 'w', encoding='utf-8') as f:
                        f.write(content)
                    print("✅ saxo_token_async.py を更新しました")
        
        # URL.txtの更新
        with open('URL.txt', 'w', encoding='utf-8') as f:
            f.write("SAXOエントリーポイント V2\n")
            f.write(f"{settings['spreadsheets']['entrypoints_url']}\n\n")
            f.write("SAXOボット設定シート\n")
            f.write(f"{settings['spreadsheets']['config_url']}\n")
        print("✅ URL.txt を更新しました")
        
    except Exception as e:
        print(f"設定ファイルの更新エラー: {e}")

def main():
    """メイン関数"""
    print("===== SAXO証券 FXBot セットアップ =====")
    
    # 既存の設定を読み込む
    settings = load_settings()
    
    # 各セクションの設定
    setup_developer_account(settings)
    setup_application(settings)
    setup_oauth(settings)
    setup_trading(settings)
    setup_notification(settings)
    setup_spreadsheets(settings)
    
    # 設定を保存
    save_settings(settings)
    
    # 他の設定ファイルを更新
    update_config_files(settings)
    
    print("\n設定が完了しました。以下のコマンドでボットを実行できます：")
    print("python SAXObot.py")

if __name__ == "__main__":
    main() 