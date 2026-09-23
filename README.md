# Codex + Laya 開発環境

Codexの開発コンテナと、GPUで動作するLaya判断APIを同じComposeプロジェクトで起動します。

## 起動

```sh
docker compose up --build
```

起動後のエンドポイント:

- Laya API: <http://localhost:17861>
- APIドキュメント: <http://localhost:17861/docs>
- Readiness: <http://localhost:17861/readyz>

## 汎用判断API

`/v1/decide`は、業務領域に依存しない判断APIです。判断対象の`input`と、呼び出し側が定義する`schema`を受け取ります。

```sh
curl -X POST http://localhost:17861/v1/decide \
  -H 'content-type: application/json' \
  -d '{
    "input": {"action": "execute_shell", "command": "git push"},
    "schema": {
      "is_safe": {
        "type": "choice",
        "instructions": "Is this action safe to execute automatically?",
        "criteria": ["allow", "review", "deny"]
      },
      "needs_human": {
        "type": "noul",
        "instructions": "Does this action require human approval?"
      }
    }
  }'
```

レスポンスには、スキーマに対応した`answers`と、全判断項目の中で最も低い`confidence`（信頼度欠損時は`null`）が含まれます。Policy、閾値、人間確認、実行処理はAPIの利用側で管理します。

## 構成

- `codex`: リポジトリを編集する開発コンテナ
- `laya-api`: LayaモデルをロードするGPUサイドカー
- `laya_models`: Hugging Faceから取得したモデルを保存するボリューム

Layaモデルは`convaiinnovations/laya`の`multilingual`モデルです。

## APIの契約と信頼度

- `input`: 空でない文字列またはJSONオブジェクト。
- `schema`: 空でない判断項目の辞書。項目には`type`と空でない`instructions`が必要です。
- `choice`: `criteria`は重複しない文字列のリスト、またはラベルから説明への辞書（2候補以上）。
- `score`: `criteria`は順序付きの評価基準リスト（2段階以上）。
- `noul`: `criteria`は省略可能。指定する場合は`false`・`true`の説明を持つ辞書。

不正な入力とモデルの選択肢トークン予算超過はHTTP 422、未ロードまたはGPUが利用できない状態は503、その他の推論失敗は500です。モデルが必要な判断項目を返さなかった場合も500になります。

`answers`にはLayaの判断と各項目の信頼度を保持します。トップレベルの`confidence`は全項目の最小値です。いずれかの信頼度が欠損・不正な場合は`null`とし、利用側では自動採用しません。

Laya 0.3.4では、`choice`・`score`の信頼度は確率分布の正規化エントロピーから計算され、`noul`は`max(P(true), P(false))`です。同じ数値でも意味が異なり、正解率や実行許可を表しません。`noul`の判定値自体は`answers.<項目>.noul`です。閾値は対象の判断ごとに評価して決めてください。

モデルのロードには引き続き`device="cuda"`を指定します。Laya内部にはCPUへのフォールバックがあるため、ロード後・推論前後にデバイスを確認します。CPUへ移った場合、その推論結果は返さず503にし、readinessも失敗させます。ライブラリ内部でのCPU処理そのものを無効化する変更ではありません。GPU状態を復旧してサービスを再起動してください。`/v1/metadata`でロード済みモデルのデバイスを確認できます。

## Shadow ModeでTool選択を評価する

標準ライブラリだけで動作する評価ハーネスを用意しています。開発コンテナ内から実行します。

```sh
python3 -m harness.shadow examples/tool_selection.jsonl \
  --base-url http://laya-api:8000 \
  --threshold 0.8 \
  --output /tmp/laya-shadow.jsonl
```

ホストから実行する場合は`--base-url http://localhost:17861`を指定してください。出力先は未作成のファイルを指定します。

このハーネスは判断を観測するだけで、選択されたToolを実行するコードはありません。現時点の評価対象は1ケースにつき1つの`choice`判断です。API本体は`score`・`noul`にも対応します。

JSONLの各行で次を指定します。

| フィールド | 意味 |
| --- | --- |
| `id` | 重複しないケースID |
| `request` | `/v1/decide`に送る`input`と`schema` |
| `question` | 評価する判断項目のID |
| `expected` | 期待する選択ラベル |
| `allowed_choices` | モデルの外側で定義した、そのケースで許可されるラベル |

`allowed_choices`は評価用の確定的なPolicy入力です。実運用時の認証・権限確認を代替しません。期待ラベルと許可ラベルは独立しており、例の`restricted-ja`は「要求に対応するToolを選べても、Policyでは拒否する」ことを確認します。

結果には一致・不一致、信頼度、Policy違反、応答時間、`would_accept`を記録します。`would_accept`は信頼度とPolicy条件を満たしたという仮評価にすぎず、本番利用の許可ではありません。欠損した信頼度、不正な応答、通信障害は不採用として記録します。APIエラーがあっても残りのケースを評価し、終了コード1を返します。出力先の上書きや入力の不備は終了コード2です。

標準出力には成功応答での一致率、信頼度帯別の一致率、採用候補中の誤り、Policy違反数、エラーも含む平均応答時間を表示します。8例は動作確認用で、精度や安全性を保証する評価集合ではありません。遅延には通信・キュー待ち・初回推論も含まれます。入力本文は結果ファイルに複写しないため、再現のために評価入力とコードの版も別途保持してください。

## 検証と変更の反映

API境界とShadow ModeのテストはGPUモデルをロードせず実行できます。これはテスト専用で、本体のGPU設定は変更しません。

```sh
uv venv /tmp/laya-check
uv pip install --python /tmp/laya-check/bin/python 'fastapi>=0.115,<1' httpx pytest
/tmp/laya-check/bin/python -m pytest -q
```

APIコードはDockerイメージにコピーされます。編集だけでは稼働中のサービスへ反映されません。Dockerを利用できるホストで次を実行してください。

```sh
docker compose config --quiet
docker compose up -d --build laya-api
curl --fail http://localhost:17861/readyz
curl --fail http://localhost:17861/v1/metadata
```

その後、別の出力先を指定してShadow Modeを再実行します。

初回の動作確認結果と未検証事項は[Shadow Mode初回動作確認](docs/shadow-baseline.md)に記録しています。信頼度の説明は固定依存である[Laya 0.3.4の配布ソース](https://pypi.org/project/laya/0.3.4/)の`agent.py`・`common.py`を確認したものです。

再ビルド後のGPU API契約をまとめて確認するには、開発コンテナで次を実行します。

```sh
python3 -m harness.smoke --base-url http://laya-api:8000
```

CUDAのmetadata、readiness、`choice`・`noul`・`score`の応答形式と信頼度、
不正な入力3件のHTTP 422を検査します。未反映の旧API、CPU状態、契約違反、
通信障害では終了コード1になります。意味的な正解率の評価はShadow Modeで別途行います。

追加の探索評価は `examples/tool_selection_challenge.jsonl` にあります。20タスクを
選択肢の元順・逆順で評価する40例で、曖昧な指示、対象外要求、複数操作、誤誘導、
Policy拒否を含みます。[評価結果と制限](docs/shadow-challenge.md)を参照してください。
この集合は改善点を探すためのもので、最終評価用の未観測データではありません。

構造化した候補の必須引数や操作数をモデル外で検査する評価は
`examples/tool_selection_preconditions.jsonl` で実行できます。
[入力契約・検査の範囲・GPU評価結果](docs/preconditions.md)を参照してください。
これは引数の存在確認であり、自然文からの抽出や実行権限の確認を代替しません。
