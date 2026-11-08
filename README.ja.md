# Everything Search

XeFM から **Everything 1.5** を検索し、検索結果を現在のペインで開く Windows 向け拡張です。voidtools の公式 **Everything SDK 3** を使って named pipe IPC に接続します。Everything の実行ファイルを起動・検索・特定しないため、実行ファイル名を変更していても利用できます。

## 動作条件

- XeFM 1.13.0 以降
- Windows 64-bit と 64-bit Python
- Everything 1.5 が起動しており、SDK 3 の IPC 接続ができること

拡張には公式 SDK の 64-bit DLL が含まれます。追加の Python パッケージ、Everything の実行ファイルのパス設定、資格情報は不要です。接続は Everything の既定 instance を先に試し、失敗した場合は Everything 1.5 alpha 用の `1.5a` instance を試します。SDK の接続エラーは XeFM に表示されます。

## インストール

XeFM のコマンドラインからインストールします。

```text
xefm ext install github:SinisterSoftware/xefm-everything-search
```

インストール後、XeFM で **Tools ▸ Reload Configuration** を実行するか、XeFM を再起動してください。バージョン更新を確認する場合は **Check Extension Updates** を使えます。マニフェストは GitHub の `v1.0.2` 以降のタグを更新元として設定しています。

## アクション

すべてのアクションは XeFM のコマンドパレットから実行できます。キー候補は他のアクションと競合しない場合にだけ自動で設定されます。

| アクション | キー候補 | 動作 |
|---|---|---|
| `everything.search-folder` | `Alt-S` | 現在のペインのフォルダー以下を対象に検索語を入力して検索します。 |
| `everything.search-all` | `Alt-Shift-S` | 全体を対象に検索語を入力して検索します。 |
| `everything.go-to-result-location` | `Alt-O` | カーソル項目のあるフォルダーを同じペインで開き、その項目にカーソルを合わせます。 |
| `everything.pick-filter` | `Alt-Shift-F` | フィルターを選択し、全体から検索します。 |
| `everything.pick-filter-folder` | `Alt-Shift-L` | フィルターを選択し、現在のフォルダー以下から検索します。 |
| `everything.bookmarks` | `Alt-B` | 拡張のブックマークまたは Everything の CSV ブックマークを選択して検索します。 |
| `everything.save-bookmark` | `Alt-Shift-B` | 最後に成功した検索を名前を付けて拡張ブックマークに保存します。 |
| `everything.delete-bookmark` | なし | 拡張が保存したブックマークを選んで削除します。 |
| `everything.show-help` | なし | XeFM 内に簡単なヘルプを表示します。 |

キー候補が別アクションと競合する場合は、既存の `KEY_BINDINGS` を編集し、必要なら競合先のキーも変更してください。たとえば明示的に割り当てる場合は、`~/.xefm/config.py` の既存の `Config` クラスに次のように追加します。

検索結果で `Alt-O` を押すと、検索結果一覧を抜けて、カーソル項目のあるフォルダーを同じペインに表示します。`Shift-O` は検索結果を残したまま別ペインに表示します。`O` の XeFM 標準のペイン同期動作は変更しません。

```python
KEY_BINDINGS = {
    # 既存の設定は残してください
    'everything.search-folder': ['Alt-S'],
}
```

### 検索結果

検索はバックグラウンドタスクで行われ、結果のパス一覧をアクティブペインの仮想リストとして開きます。ファイルの移動・変更は行いません。キャンセルした場合はキャンセルが通知されます。接続できない、SDK の検索に失敗した、または検索結果を取得できない場合は XeFM にエラーが表示されます。

検索結果を取得した後、XeFM が各パスを確認して一覧を準備します。件数が多い場合、準備中は元のペインが表示されたままになることがあります。準備が完了すると、XeFM のログに表示件数が出ます。表示できるパスがない場合もログで通知されます。

`Search All` に空の語を入力することはできません。Everything の **Everything** フィルターを選ぶと、空の検索式で全件検索できます。大規模なインデックスでは結果一覧の取得に時間やメモリを使う場合があります。

## フィルター

標準フィルターは **Everything**, **Audio**, **Compressed**, **Document**, **Executable**, **Folder**, **Image**, **Video** です。Everything の検索式（例: `ext:pdf`、`folder:`、`audio:`）を使います。

拡張独自のフィルターを作る場合は、`~/.xefm/state/everything_filters.json` に UTF-8 JSON オブジェクトを置きます。キーがフィルター名、値が検索式、または `query` と `files_only` を持つオブジェクトです。

```json
{
  "PDF": "ext:pdf",
  "ソースコード": {
    "query": "ext:c;h;py",
    "files_only": true
  },
  "フォルダー": {
    "query": "folder:",
    "files_only": false
  }
}
```

単純な文字列形式、およびオブジェクトで `files_only` を省略した場合は、ファイルだけを検索します。`files_only: false` はフォルダーも結果に含めます。JSON のフィルター名は大文字・小文字を区別せずに統合されます。同じ名前が複数の場所にある場合、後述の順で後から読み込んだ定義が優先されます。

Everything の `Filters.csv` が見つかる場合は読み込みます。検索する場所は次の順で、各ファイルについて最初に見つかったものだけを使用します。

1. `%SCOOP%\persist\everything-beta\Filters.csv`
2. `%SCOOP%\persist\everything\Filters.csv`
3. `%APPDATA%\Everything\Filters.csv`
4. `%LOCALAPPDATA%\Everything\Filters.csv`

`Filters.csv` は UTF-8 BOM 付きまたは BOM なしのヘッダー付き CSV として読み込み、`Name` と `Search` 列を使います。検索式が `folder:` で始まる場合は `files_only: false` として扱い、それ以外はファイルだけを検索します。フィルターの優先順位は **標準フィルター → Everything の CSV → `everything_filters.json`** です。CSV や JSON に必要な列・形式がない場合はエラーを表示し、無効なファイルを空データとして扱いません。

## ブックマークと検索履歴

### 拡張のブックマーク

`everything.save-bookmark` は最後に成功した検索語とフォルダー範囲を、指定した名前で `~/.xefm/state/everything_bookmarks.json` に保存します。ファイルの形式は UTF-8 JSON 配列です。

```json
[
  {
    "name": "作業中の PDF",
    "query": "ext:pdf",
    "scope": "C:\\Users\\me\\Documents"
  }
]
```

`scope` が `null` なら全体検索です。フォルダー検索を保存すると、そのフォルダー範囲も一緒に保存されます。同名ブックマークを保存すると、既存項目の `name`、`query`、`scope` が更新されます。これら以外の既存キーは保持されます。

ファイル更新は同じディレクトリに一時ファイルを書き、原子的に置き換えて行います。JSON が壊れている、読み取れない、または形式が違う場合は保存・削除を中止してエラーを表示します。空のブックマーク一覧で既存ファイルを上書きすることはありません。

### Everything の CSV ブックマーク

同じディレクトリ候補から `Bookmarks.csv` も読み取ります。こちらも CSV は読み取り専用で、拡張から変更・削除しません。`everything.bookmarks` では拡張ブックマークと Everything の CSV ブックマークの両方を選べます。`everything.delete-bookmark` が削除するのは拡張 JSON の項目だけです。

`Bookmarks.csv` は UTF-8 BOM 付きまたは BOM なしのヘッダー付き CSV として読み込みます。`Type` が空欄または `0` で、`Name` が空でない行を対象にします。`Filter` が指定され、名前が一致するフィルターがある場合、その検索式をブックマークの `Search` に加えます。`Case`, `Whole Word`, `Path`, `Diacritic`, `Prefix`, `Suffix`, `Ignore Punctuation`, `Ignore Whitespace`, `Regex` のフラグを SDK の検索オプションとして適用します。`Sort` と `Descending` は SDK が扱える並べ替え項目に変換します。未対応の並べ替え項目はログに警告し、並べ替えを省略します。`Folder` は選択画面に出す表示名への付加に使います。

最後に成功した検索は XeFM の拡張状態に保存され、XeFM 再起動後も `Save Bookmark` から保存できます。別の検索履歴ファイルは作成しません。

## Migemo 連携

この拡張は c/migemo や辞書を同梱・起動しません。既存の `EverythingSearchConfig.MIGEMO_EXPAND` に設定された同期 callable を利用します。引数は検索トークンの文字列、戻り値は Everything の `regex:` 条件に渡す正規表現文字列です。未設定時の既定値は `None` です。

設定例（`expand_migemo` の本体は利用者側で用意してください）:

```python
def expand_migemo(token):
    # token を正規表現へ変換する既存の関数を呼び出す例
    return your_migemo_function(token)

class EverythingSearchConfig:
    MIGEMO_EXPAND = expand_migemo
```

設定クラスは `Config` の外に定義します。検索入力はセミコロンで区切って処理し、英字とハイフンだけで構成され、英大文字を少なくとも一つ含むトークンだけを callable に渡します。小文字のみの語、数字・記号を含む語、Everything 構文トークン、フィルター式、保存済みブックマーク式には適用しません。callable が falsey 値を返すか例外を送出した場合は元のトークンで検索を続け、例外はログに記録します。

空白では分割されません。例えば `Tenki;Yohou` は2語とも対象ですが、`Tenki Yohou` は空白を含む1トークンとしてそのまま検索されます。callable 側の最小文字数などの条件により、対象トークンでも展開されない場合があります。

検索タスク終了時、XeFM のログペインに入力、Migemo に渡したトークンと返された正規表現（または展開しなかった理由）、展開後の式、フォルダー範囲や `file:` を加えた最終検索式を表示します。`SDK search text prepared` は SDK に渡すために準備した式です。`SDK SetSearchTextW attempted` は接続と検索状態の作成に成功して、その SDK 呼び出しを試みる場合にのみ表示されます。これは SDK が式を受け付けたことや検索が成功したことを意味しません。失敗・キャンセル時も、準備済みの情報は表示します。長い値は番号付きの JSON 文字列の断片に分割され、順番に連結すると元の値を復元できます。

**ログには検索語、Migemo の正規表現、フォルダーパスが含まれることがあります。** フィルターやブックマークも対象です。ログの閲覧・コピー・共有時は機密情報に注意してください。拡張は専用のログファイルを作成しませんが、XeFM や実行環境がログを保持・取得する場合があります。

## ライセンス

拡張本体は MIT License です。付属の `Everything3_x64.dll` は voidtools の Everything SDK 3.0.0.9 から取得したもので、SDK も MIT License です。著作権表示とライセンス本文は [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) に記載しています。

## 開発・検証

パッケージのルートで次を実行します。

```text
xefm ext check .
python -m pytest tests
```

テストは偽 SDK と偽 XeFM コンテキストを使い、XeFM アプリや Everything を起動しません。拡張は XeFM の Preview API（プロンプト、選択ダイアログ、バックグラウンドタスク、仮想リスト、Markdown ヘルプ、拡張設定）を使います。`xefm ext check` が表示する Preview の警告は、XeFM の将来のリリースで API が変わる可能性を示します。
