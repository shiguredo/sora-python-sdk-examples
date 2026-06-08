# 変更履歴

- CHANGE
  - 後方互換性のない変更
- UPDATE
  - 後方互換性がある変更
- ADD
  - 後方互換性がある追加
- FIX
  - バグ修正

## main

- [UPDATE] GitHub Actions の ubuntu-24.04-arm による E2E テストを mediapipe 非対応のため削除
  - @voluntas
- [UPDATE] GitHub Actions の macOS E2E テストを macos-15 / macos-26 のみに変更
  - raw-player が macosx_15_0_arm64 向け wheel のみ提供するため macos-14 を除外
  - @voluntas
- [UPDATE] recvonly.py を複数受信表示に対応
  - `--grid-cols` 引数で横に並べる数を指定可能
    - デフォルトは 3
  - グリッドで表示する
  - @voluntas
- [ADD] sendonly.py に `--show-preview` オプションを追加
  - 配信映像をプレビュー表示する
  - @voluntas
- [ADD] examples に argparse を利用した引数指定を追加
  - @voluntas
- [ADD] examples に環境変数での args の上書きを追加
  - @voluntas

## 2025.4

### misc

- [ADD] GitHub Actions の actions/checkout を v5 に上げる
  - @miosakuma

## 2025.2

- [UPDATE]  Sora Python SDK サンプル集のバージョンを 0.0.0 にする
  - 公開の予定はないためこのバージョンで固定し変更しない
  - @miosakuma
- [UPDATE] Sora Python SDK のバージョンを 2025.2.3 に上げる
  - @voluntas
- [UPDATE] Sora Python SDK のバージョンを 2025.2.1 に上げる
  - @miosakuma

### misc

- [ADD] .github ディレクトリに copilot-instructions.md を追加
  - @torikizi

## 2025.1.0

- [CHANGE] Sora Python SDK に合わせて Python 3.10 を落とす
  - @voluntas
- [UPDATE] Sora Python SDK のバージョンを 2025.1.0 に上げる
  - @voluntas

### misc

- [CHANGE] GitHub Actions の ubuntu-latest を ubuntu-24.04 に変更
  - @voluntas
- [CHANGE] E2E テスト成功時に slack 通知をしないようにする
  - @voluntas
- [UPDATE] GitHub Actions の openh264 のバージョンを 2.6.0 に上げる
  - @voluntas
- [ADD] GitHub Actions に ubuntu-24.04-arm による E2E テストを追加
  - @voluntas

## 2024.3.0

**祝いリリース**
