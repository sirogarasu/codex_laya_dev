# Codex + Laya 開発環境

Codex用のdevcontainerと、LayaモデルをGPUで実行するAPIサイドカーを同じComposeプロジェクトで起動します。

## 起動

VS Codeでこのディレクトリを開き、Dev Containersから「Reopen in Container」を選びます。

手動で起動する場合は、次を実行します。

```sh
docker compose up --build
```

起動後のエンドポイント:

- Laya UI: <http://localhost:17860/ui>
- Laya API: <http://localhost:17861>
- APIドキュメント: <http://localhost:17861/docs>

devcontainer内からは `http://laya-api:8000` でAPIにアクセスできます。

初回起動時に、LayaがHugging Faceから `convaiinnovations/laya` の
`multilingual` モデルをダウンロードします。モデルは `laya_models` ボリュームに保存されます。

## API例

```sh
curl -X POST http://localhost:17861/v1/classify \
  -H 'content-type: application/json' \
  -d '{"message":"二重に請求されたので返金してください"}'
```

## 開発環境

`codex` サービスが作業用devcontainer、`laya-api` サービスがGPUサイドカーです。
Layaモデルは `laya-api` だけがロードするため、UIとハーネスでGPUメモリを二重に使用しません。
