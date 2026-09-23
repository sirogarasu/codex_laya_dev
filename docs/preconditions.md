# Shadow Modeの構造化候補検証

`preconditions`は呼び出し側が持つ評価用データであり、Laya APIの入力・出力契約は変更しない。
`harness.preconditions.check_preconditions`は選択された候補の構造を検査する。
Tool実行機能はなく、検査成功も権限の付与ではない。

```json
{
  "operation_count": 1,
  "candidates": {
    "read_file": {
      "required_arguments": ["target"],
      "arguments": {"target": "README.md"}
    },
    "stop": {"required_arguments": [], "arguments": {}}
  }
}
```

このオブジェクトを評価JSONLの各ケースの`preconditions`に置く。
`required_arguments`は信頼できるTool定義から設定する。Layaの応答や未信頼テキストに
必須項目を決めさせてはならない。`arguments`と`operation_count`は呼び出し側が構造化した状態。
本実装は自然文からそれらを抽出するものではない。

| 条件 | 結果 |
| --- | --- |
| 定義の形式が不正 | `invalid_preconditions` |
| 操作数が0または2以上 | `unresolved_operations` |
| 選択された候補の定義がない | `candidate_missing` |
| 必須引数が欠損、null、空文字、空リスト、空辞書 | `argument_missing` |
| 構造検査を通過 | `passed`。別途Policy・信頼度も確認 |

操作数が未解決の場合、stopの選択であっても仮採用にしない。
本機能は引数の存在確認に限る。値の型、対象の実在、パスの解決、要求との意味的一致、
権限や認可はそれぞれの実行側で別途検証する。空でない誤った対象はこの検査だけでは検出できない。

既存評価との互換性のため、`preconditions`自体がないケースは`not_checked`と記録し、
従来どおりの仮採用評価をする。nullを明示した場合は不正として拒否する。
`not_checked`の仮採用を本番実行可能と解釈してはならない。

## GPUでの回帰確認（2026-09-23）

[評価入力](../examples/tool_selection_preconditions.jsonl)は先の探索集合から6タスクを選び、
選択肢の元順・逆順で計12例にしたもの。構造化候補は手作業で付与した。
既知の失敗に対する回帰確認であり、独立した最終評価集合ではない。

[生結果](evaluations/tool-selection-preconditions-20260923.jsonl):

- APIエラー0、Tool実行0。平均応答時間約19.62ms。
- モデル自体の一致は4/12。検査によってモデルの正解率が改善したわけではない。
- 対象あり4例は仮採用。仮採用中の誤り0。
- 対象なし4例は`argument_missing`で不採用。
- 複数操作4例は`unresolved_operations`で不採用。
- confidence=1.0でread_fileを選んだ対象なしの2例も不採用。

```sh
python3 -m harness.shadow examples/tool_selection_preconditions.jsonl --output /tmp/laya-preconditions-new.jsonl
```

次は構造化処理自体の評価が必要。候補の必須引数定義は信頼できる設定に固定し、
抽出された対象の根拠と操作数を検証する。誤誘導についてはcontext有無の対照評価も必要。
本番実行への接続は引き続き保留する。
