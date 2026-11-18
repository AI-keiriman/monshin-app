#!/usr/bin/env bash
set -euo pipefail

# SSH から呼ばれたときに uv が見つかるようにする
export PATH="$HOME/.local/bin:$PATH"

echo "==> プロジェクトのフォルダーへ移動"
cd /var/www/monshin-app

echo "==> 最新のコードを取得（main、fast-forward のみ）"
git pull --ff-only origin main

echo "==> 依存パッケージを同期（本番用、ロックファイル固定）"
uv sync --frozen --no-dev

echo "==> データベースのマイグレーションを適用"
uv run --frozen --no-dev flask db upgrade

echo "==> 料金表を入れる（すでにある行は更新する）"
uv run --frozen --no-dev flask seed

echo "==> monshin-app を再起動"
sudo -n systemctl restart monshin-app

echo "==> 起動を確認（2秒待つ）"
sleep 2
systemctl is-active monshin-app

echo "==> 更新が完了しました"
