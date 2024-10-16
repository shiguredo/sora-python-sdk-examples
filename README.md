# Sora Python SDK サンプル集

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## 概要

Sora Python SDK のサンプルコードをまとめたリポジトリです。

- Sora Python SDK の最新の安定版を利用しています
- PyPI に登録されている Sora Python SDK を利用しています
- サンプルコードを利用した E2E テストを実行できます

## セットアップ

[uv](https://docs.astral.sh/uv/) というパッケージマネージャーを利用しています。

インストール方法は <https://docs.astral.sh/uv/getting-started/installation/> をご確認ください。

### 依存パッケージのビルド

```bash
uv sync
```

## サンプルコードの実行

`.env.template` をコピーして `.env` に必要な変数を設定してください。

```bash
cp .env.template .env
```

例えば `media_sendonly.py` を実行する場合は以下のコマンドを実行してください。

```bash
uv run python3 src/media_sendonly.py
```

## E2E テストの実行

`.env.template` をコピーして `.env` に必要な変数を設定してください。

```bash
cp .env.template .env
```

```bash
uv run pytest tests
```

## ライセンス

Apache License 2.0

```text
Copyright 2023-2024, tnoho (Original Author)
Copyright 2023-2024, Shiguredo Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

このリポジトリに含まれる `shiguremaru.png` ファイルのライセンスは [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/deed.ja) です。
