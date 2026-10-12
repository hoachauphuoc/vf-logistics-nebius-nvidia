# VF Logistics 認可レビュー是正報告書

| 項目 | 内容 |
|---|---|
| 対象リポジトリ | `hoachauphuoc/vf-logistics-nebius-nvidia` |
| レビュー対象 | コミット `bd6a210`（2026-10-11 付 認可レビュー報告書）、および再レビュー（2026-10-12 付、対象 `923d36f`） |
| 是正後コミット | 初回 8 件：`923d36f`／再レビュー R01〜R04：`8d830c1`（＋`037f9a5`、`origin/master` と一致） |
| 本番環境 | Cloud Run `vf-app`（`vf-fraud-detection-phuochoa` / asia-southeast1）、リビジョン **`vf-app-00020-cd7`**（トラフィック 100%、10/12 13:04 デプロイ） |
| 再テスト実施 | 2026-10-12 08:56〜09:22（初回 8 件）、12:21〜13:12（R01〜R04）（JST） |
| 結論 | **初回指摘 8 件と再レビュー指摘 4 件（R01〜R04）をすべて是正し、本番へデプロイ済み。** R01 は本番のヘッダ経路で実地確認済み。R02〜R04 はマルチテナント用の修正で、本番（単一テナント）ではテストと Emulator で確認 |

---

## 1. 概要

レビューで指摘された 8 件（A01〜A04、S01、T01〜T03）を、ユーザーの判断に基づき 3 部構成で是正しました。

| 判断事項 | 採用した方針 |
|---|---|
| A01 | ワンクリック（ゲスト）セッションでは境界の公開を禁止する |
| S01 | ゲスト入口を閉じたら、発行済みゲストセッションも全体で無効化する |
| A04 | 試行回数を Firestore の共有カウンタで数える |
| T02/T03 | 第 3 部として今回実装する |

Firestore Emulator で検証した結果、MemoryStore では見えなかった実際の欠陥（同時アクセス時のロック待ち）が 1 件見つかり、追加で修正しました（第 5 章）。

---

## 2. 指摘事項と是正内容

### 第 1 部：境界（Delegation Boundary）の公開と保存

| ID | 指摘内容 | 是正内容 |
|---|---|---|
| **A01** | ゲスト（ワンクリック）が全拒否の境界を公開できた（revoke はパスワード必須だったが publish は無防備） | `governance/publish` に `@require_password_session` を付与。BFF の `PASSWORD_ONLY_POST` にも追加し、UI もロック表示。simulate（書き込みなし）はゲストに開放したまま |
| **A03** | `{"permitted": "false"}` が文字列の真偽値として「許可」と解釈された | permissions の厳格スキーマ `validate_permissions()` を追加（型の強制変換なし、未知キーは拒否、許可時は上限 2 つが必須）。publish・simulate とも違反時は **422** で全エラーを返す。ゲート側も `is not True` 判定に変更し、保存済みの不正データも拒否 |
| **A02** | revoke 後に再公開すると `BOUNDARY-v1` が再利用され、元の v1 が上書きされた | バージョンを「テナントで過去最大＋1」に変更（`boundary_counters/{tenant}`）。publish/revoke を 1 トランザクションで実行し、`create()` で既存 ID の上書きを拒否 |
| **T01** | 境界の保存キーが全テナント共通だった | 保存キーを `{tenant}__{boundary_id}` に変更。既定テナント `default` は既存キーのまま（本番の v1〜v3 に影響なし） |

### 第 2 部：セッションとサインイン

| ID | 指摘内容 | 是正内容 |
|---|---|---|
| **S01** | `VF_ONE_CLICK_JUDGE=false` にしても、発行済みゲストセッション（4 時間）が有効なままだった | 検証のたびに `VF_ONE_CLICK_*` を再確認。入口が閉じている、期限切れ、または別アカウントを指すゲストトークンを拒否する。Flask（`auth.one_click_sessions_allowed`）と BFF（`session.ts verifySession`）の両方で判定 |
| **A04** | メールアドレスの空白差でレート制限を回避でき、制限もインスタンスごとだった | メールを一度だけ正規化（trim＋小文字化）し、その値で計数と照合を行う。制限は「アカウントごと 5 回／分」「送信元ごと 20 回／分」の 2 系統。カウンタは Flask の `/internal/login-throttle` 経由で Firestore `login_throttle` に共有。取得できない場合のみインスタンス内カウンタにフォールバック（**再レビュー R01 で廃止し 503 に変更、第 9 章**） |

### 第 3 部：マルチテナントの所属解決

| ID | 指摘内容 | 是正内容 |
|---|---|---|
| **T02** | テナントをメールドメインの先頭ラベルから推定していた（`acme.com` と `acme.net` が同一、`yahoo.co.jp` が `yahoo`） | `tenant_from_email()` を削除。明示的な所属レジストリ `VF_TENANT_MEMBERS`（JSON：`{principal: {tenant: role}}`）を新設。主体は、コンソールのメール、`iap:<sub>`、API キー用の `service` |
| **T03** | コンソール利用者が全員テナント `default` に入っていた | `MULTI_TENANT=true` のときはテナントとロールをレジストリから解決し、グローバルのロール一覧は使わない。複数所属の利用者は `X-VF-Tenant`（Cookie `vf_tenant` 経由）で**自分の所属の中からのみ**選択できる。未登録の主体は 403、匿名は 401。レジストリが空または不正なら起動しない。`/internal/execute` も service が所属するテナントのみ指定可能 |

> **注意**：本番は `MULTI_TENANT` 無効（単一テナント）で運用しています。T02/T03 の仕組みは実装・テスト済みですが、本番で有効にするのは `VF_TENANT_MEMBERS` を設定したときです。単一テナントの挙動は変わっていないことを確認済みです。

---

## 3. コミットとデプロイ履歴

| 日時（10/11） | コミット | 内容 | 本番リビジョン |
|---|---|---|---|
| 19:11 | `d05d745` | A01・A03・A02・T01 | — |
| 19:16 | `80431c9` | A03 テストの修正（ミューテーション検査で発覚した見かけ上の合格を解消） | `vf-app-00014-5z6`（19:26） |
| 19:44 | `a95af5f` | S01・A04 | `vf-app-00015-n6w`（19:54） |
| 20:08 | `1ca24ed` | T02・T03 | `vf-app-00016-xb6`（20:46） |
| 20:53 | — | S01 本番検証のためゲスト入口を一時的に閉鎖 | `vf-app-00017-cc6` |
| 20:56 | — | ゲスト入口を再開 | `vf-app-00018-c2p` |
| 21:51 | `923d36f` | Emulator で発見した同時実行問題の修正、Emulator テスト追加 | `vf-app-00019-9tl`（22:00） |
| 10/12 12:42 | `8d830c1` | 再レビュー R01〜R04 の是正（第 9 章） | — |
| 10/12 12:42 | `66d14ae` | 本報告書（初版）の追加 | — |
| 10/12 12:59 | `037f9a5` | ミューテーション検査スクリプトの文字コード修正（検査結果には影響なし） | **`vf-app-00020-cd7`**（13:04、現行） |

Part 2 以降は、未コミットの作業が混入しないよう、クリーンな `git worktree` からデプロイしました。

---

## 4. 再テスト結果（2026-10-12）

### 4.1 ローカルの品質ゲート（コミット `923d36f`）

| 項目 | 結果 | 時刻 |
|---|---|---|
| ruff（CI と同じルール） | 合格 | 08:58 |
| pytest（全体） | **1002 passed**, 10 skipped, 415 subtests passed | 09:02 |
| pytest（認可関連 7 ファイル） | **187 passed**, 202 subtests passed | 09:02 |
| mypy（パッケージ全体） | 122 件（是正前と同数、CI 上限 123 以内） | 09:02 |
| mypy（strict 対象 3 モジュール） | エラーなし | 09:03 |
| tsc | 合格 | 09:00 |
| eslint | 合格 | 09:02 |
| vitest | **167 passed**（16 ファイル） | 09:05 |
| next build | 合格 | 09:07 |

スキップされた 10 件はすべて Emulator 用テストで、`FIRESTORE_EMULATOR_HOST` 未設定時に自動でスキップされる設計です。同じファイルにある Emulator 不要の 2 件（競合判定のテスト）は実行され、合格しています。

### 4.2 本番での確認（非破壊、09:00〜09:22）

| ID | 確認内容 | 結果 | 判定 |
|---|---|---|---|
| — | ヘルスチェック | 200 | ✅ |
| A01 | ゲスト（`governance_admin` / `one_click`）で全拒否境界を publish | **403** | ✅ |
| A01 | ゲストで revoke | **403** | ✅ |
| A01 | ゲストで simulate | 200（利用可能のまま） | ✅ |
| A01 | `/auth/policy` の publish 定義 | `required_role=governance_admin`、`requires_password_session=True` | ✅ |
| A03 | simulate で `permitted` = `"false"` / `"true"` / `0` / `1` | すべて **422** | ✅ |
| A03 | API キーで `permitted:"false"` を publish | **422**（書き込みなし） | ✅ |
| A02/T01 | 境界の履歴 | `BOUNDARY-v3:ACTIVE, v2:SUPERSEDED, v1:SUPERSEDED`（是正前から変化なし） | ✅ |
| S01 | ゲスト入口の設定 | `VF_ONE_CLICK_JUDGE=true`、`UNTIL=2026-12-16`（審査用に開放中） | ✅ |
| S01 | 偽造 Cookie で whoami | `viewer` / `anonymous`（権限なしとして扱う） | ✅ |
| A04 | 新規の架空アカウントへ、空白・大文字小文字を変えて 7 回誤ログイン | `401,401,401,401,401,429,429` | ✅ |
| A04 | Firestore `login_throttle` | アカウント用と送信元用の 2 文書、各 `count=7`、`expire_at` あり（ID はハッシュでメールを含まない） | ✅ |
| A04 | TTL ポリシー（`login_throttle.expire_at`） | `ACTIVE` | ✅ |
| T03 | 匿名の whoami | `viewer` / テナント `default` / `memberships` なし（単一テナントの挙動は不変） | ✅ |
| T03 | `/internal/login-throttle`、`/internal/execute` をインターネットから呼び出し | 405（Flask に到達しない） | ✅ |
| T03 | BFF 経由の `/api/proxy/internal/...` | 404（転送対象外） | ✅ |

### 4.3 前日（10/11）に実施し、今回は再実行していない検証

コード（`923d36f`）は前日から変わっていないため、以下の結果は有効です。

| 項目 | 結果 |
|---|---|
| ミューテーション検査（`scripts/check_test_sensitivity.py`） | **49/49 すべて検出**（21:55）。今回の是正分は A01・A03・A02・T01・S01・A04・T02/T03 の計 13 件 |
| Firestore Emulator テスト（`tests/test_firestore_emulator.py`） | **12/12 合格**を 2 回連続（21:45、21:48） |
| S01 本番実地テスト | 20:53 にゲスト入口を閉鎖。**同じゲスト Cookie** が `governance_admin/one_click` から `viewer/anonymous` に変わり、simulate は **401**、新規ゲストサインインは **404**。20:56 に再開し、新規ゲストは 200。審査用ログインの停止時間は約 2 分 |

---

## 5. Emulator 検証で見つかった問題と対応

MemoryStore のテストとシグネチャ一致検査だけでは、FirestoreStore のトランザクションの実挙動は確認できません。そこで Emulator で検証し、以下の問題を見つけて修正しました（コミット `923d36f`）。

| 問題 | 影響 | 対応 |
|---|---|---|
| ログイン試行カウンタ（トランザクション版）が、同一アカウントへの 12 件同時試行でロック待ちになり、数分かかった | コンソールは 3 秒で待つのをやめてインスタンス内カウンタに戻るため、**攻撃が集中したときに A04 の弱点が再発する** | アトミックな `Increment(1)` と読み直しによる固定ウィンドウ方式に変更。ロックも再試行もなく、各ウィンドウで許可されるのは**最大でも上限回数まで**（同時実行で 0.16 秒） |
| トランザクション内の**読み取り**で `Aborted` が発生すると、クライアントの自動リトライの対象外だった | 同時 publish がエラー（500）になる。データは壊れない | トランザクション全体を最大 8 回、ジッター付きで再実行する `_run_transaction()` を追加。リトライするのは競合系の例外だけ |
| `google.api_core` を import 時に読み込むよう変更してしまい、memory モードで依存エラーになった（修正途中で発生） | ローカルテストの収集エラー（本番への影響なし） | import を `FirestoreStore.__init__` 内へ移動 |

---

## 6. 残存リスクと制約

| 項目 | 内容 |
|---|---|
| S01 は「一括遮断」であり「個別失効」ではない | 入口を閉じている間はすべてのゲストトークンを拒否するが、再開すると有効期限内のトークンは再び使える（選択した方針どおり） |
| 同一テナントでの同時 publish | Emulator では 6 件同時でもすべて成功し、バージョンは重複せず ACTIVE は 1 件だったが、完了までに 55〜155 秒かかった。publish はまれで慎重に行う操作のため許容範囲。`docs/ARCHITECTURE.md` に記載 |
| ログインカウンタの固定ウィンドウ | 拒否された試行も数える。ウィンドウの境目をまたぐと最大 2 倍まで通る可能性がある（影響は 1 ウィンドウ分に限られる）。README に記載 |
| 共有カウンタが応答しない場合（R01 以降） | ログインは **503** で一時的に拒否する（インスタンス内カウンタへは戻らない）。Flask は同一コンテナ内にあるため、応答しないときはコンソール全体も使えない状態であり、限度を守ることを優先した |
| マルチテナント | 本番では未有効。取り込みシンクはテナントを解決しないため、`MULTI_TENANT=true` では動作しない。`case_id` の所属検証は `/internal/execute`（外部送信の直前）では実施するようになったが（R02）、その他の経路には同等の検証はない |
| Emulator の JRE | Temurin 21 でも動作するが、gcloud は将来 JRE 25 以上を要求するという警告を出している |

---

## 7. 作業中に発生した副作用

| 事象 | 対応 |
|---|---|
| Emulator テストのためメインの Python に `google-cloud-firestore` を入れた際、`protobuf` が 7.x に上がり、Snowflake CLI（`protobuf<6` が必要）と衝突した | `protobuf` を 5.29.6 に戻し、`google-cloud-firestore` をアンインストール。Snowflake CLI 3.20.0 が動作することを確認。`google-api-core` など一部の Google 系パッケージは新しい版のまま残り、`pip check` で警告が出るが、CLI は使っていない |
| 今後の Emulator テスト | メイン環境を汚さないよう、独立した venv（`%TEMP%\vf_emu_venv`）で実行する |
| 導入したツール | Eclipse Temurin 21 JRE（winget）、gcloud コンポーネント `cloud-firestore-emulator` |

---

## 8. 残作業（要対応）

1. **Devpost の「Testing instructions」の更新**（ユーザー側の作業）：ゲスト（ワンクリック）では境界の公開ができなくなったため、`SUBMISSION.md` の記載に合わせて修正してください。
2. マルチテナントを本番で有効にする場合は、`VF_TENANT_MEMBERS` を Secret Manager に登録した上で、取り込みシンクのテナント対応を先に行う必要があります。R02〜R04 の修正により、「対象組織での権限」と「初回サインイン時の組織選択」の前提条件は満たしましたが、取り込み経路は未対応のままです。

---

## 9. 再レビュー（2026-10-12）指摘 R01〜R04 への対応

再レビュー（対象 `923d36f`）では、初回 8 件の修正が有効であることが確認された一方、A04 に R01・R04、T03 に R02・R03・R04 が残っていると指摘されました。すべてコミット `8d830c1` で是正し、`vf-app-00020-cd7` として本番にデプロイしました。

### 9.1 判断事項

| 判断事項 | 採用した方針 |
|---|---|
| R01：共有カウンタが応答しないとき | **503 で拒否**（本番ではインスタンス内カウンタを使わない） |
| 対象範囲 | R01〜R04 をすべて今回対応（`/internal/execute` の `case_id` 所属検証も含む） |

### 9.2 指摘と是正内容

| ID | 原因（再レビューの指摘） | 是正内容 |
|---|---|---|
| **R01** | `clientIp()` が X-Forwarded-For の**先頭**（呼び出し側が自由に書ける値）を使っていた。長い値でキーが 300 文字を超えると共有カウンタが 400 を返し、どのエラーでも未使用のインスタンス内カウンタに切り替わっていた | (1) Cloud Run が末尾に追加する**最後の要素**を使用（Flask の `ProxyFix(x_for=1)` と同じ要素）。IPv4/IPv6 として妥当でなければ `unknown`。(2) キーを `acct:`/`ip:` ＋ SHA-256 にして長さを固定（生のメール・IP は保存しない）。(3) 共有カウンタが 4xx・5xx・タイムアウト・不正な応答のいずれでも、ログインは **503**（`Retry-After: 5`）とし PBKDF2 を実行しない。ログに理由を出力。インスタンス内カウンタは「API キー未設定かつ非 production」（ローカル開発）に限定。judge ルートの送信元判定も同じ関数で修正 |
| **R02** | `/internal/execute` が、ヘッダで選ばれた組織で operator を確認した後、body の `tenant_id` で別の組織を指定できた。また「API キー＋本人のセッション」もサービスとして扱われた | (1) `AuthContext.is_machine_identity`（キーのみ、セッションなし）を新設し、それ以外は **403**。(2) 対象組織は常に認証時に `X-VF-Tenant` で解決された組織＝ロールを確認した組織。body の `tenant_id` が異なれば **409**。(3) `case_id` が対象組織のケースでなければ **404**（存在しない場合と同じ応答）。いずれも外部送信の前に判定。(4) `executor_client` が `X-VF-Tenant` を送信 |
| **R03** | 複数所属の利用者の初回サインインで whoami が 403（choices 付き）を返すが、`getAuth()` が破棄し選択 UI が出なかった。古い Cookie でも詰まった | (1) 拒否応答に `reason`（`tenant_choice_required`／`not_member_of_requested`／`invalid_choice`／`no_membership`）を追加。(2) `identity.ts` が `TenantChoiceRequired` を投げ、`TenantSwitcher` が「組織を選択」を表示（本人の choices のみ）。(3) ログイン・ワンクリック・ログアウトで `vf_tenant` Cookie を失効 |
| **R04** | `MULTI_TENANT=true` で service が 2 組織以上に所属すると、`/internal/login-throttle` が「組織を選択」の 403 になり、共有カウンタが失われた | 新しいデコレータ `require_platform_key`：キーを定数時間比較し、セッション付きは 403、キーなし・不一致は 401。所属レジストリは参照しない。カウンタは固定スコープ `platform-login`（`store.LOGIN_THROTTLE_SCOPE`）で記録し、全インスタンス・全組織で 1 つの上限を共有 |

### 9.3 品質ゲート（修正後のコード、10/12）

| 項目 | 結果 | 時刻 |
|---|---|---|
| ruff（CI と同じルール） | 合格 | 12:21 |
| pytest（全体） | **1027 passed**, 11 skipped（Emulator 用） | 12:37 |
| mypy（パッケージ全体） | 122 件（`923d36f` と同数、新規エラーなし）。※ローカルの numpy 型スタブが `python_version=3.11` で解析できないため、修正前後とも `--python-version 3.12` で比較 | 12:24 |
| mypy（strict 対象 3 モジュール） | エラーなし | 12:22 |
| tsc ／ eslint | 合格 | 12:29 |
| vitest | **199 passed**（19 ファイル、修正前 167／16） | 12:30 |
| next build | 合格 | 12:31 |
| Firestore Emulator（`tests/test_firestore_emulator.py`、独立 venv：Python 3.13.14、google-cloud-firestore 2.34.1、Temurin JRE 21、`127.0.0.1:8681`） | **13 passed**（Emulator 11 件＝既存 10 件＋ R04 の固定スコープ検証 1 件、および競合判定 2 件）。`8d830c1` と同一内容のツリーで実行 | 12:39〜12:41 |
| ミューテーション検査（クリーンなツリー `66d14ae`） | **61/61 すべて検出**。R01〜R04 用に 13 件追加し、コードが変わった既存 2 件を更新。フロントエンドの変異は vitest で検査するようスクリプトを拡張 | 12:43〜12:54 |

再レビューが求めた再検証条件と、対応するテスト：

| 条件 | テスト |
|---|---|
| R01：5 回後にヘッダを変えても、共有カウンタがエラーを返しても、パスワード検査は増えない | `login-limit.test.ts`（400/403/500/不正応答/接続拒否/タイムアウト → すべて `unavailable`、5 回計数後に障害でも追加なし）、`login/route.test.ts`（503 のとき `verifyOperator` 未呼び出し） |
| R01：実際の送信元は、信頼できない部分を変えても同じバケット | `rate-limit.test.ts`、`login-limit.test.ts`（25 回、先頭とアカウントを毎回変更 → 20 回で制限） |
| R01：複数インスタンス | `login-limit.test.ts`（モジュールを 2 つ読み込み、共有台帳で 1 つの上限） |
| R02：対象組織で viewer の service／対象組織に属さない利用者／ヘッダと body の不一致を拒否、正常系 1 件、拒否時は外部送信なし | `tests/test_internal_execute.py`（再レビューと同じ構成：service は A で operator・B で viewer、Alice は A のみ。`publish_decision_direct` はモックで、拒否時は未呼び出しを検証） |
| R03：2 組織所属の初回サインインで Cookie を手で触らずに選択できる、利用者を変えても詰まらない | `TenantSwitcher.test.tsx`（403＋choices で選択 UI を表示、選択で `chooseTenant` 呼び出し、古い選択の文言）、`test_membership.py`（whoami の `reason`/`choices`、他人の Cookie からの復帰）、ログイン／ログアウト／judge での Cookie 失効 |
| R04：service が 2 組織所属、コンソール 2 インスタンスで 1 つの上限、設定ミスで制限が弱まらない | `test_login_throttle.py::TestUnderMultiTenancy`（ヘッダ無しで 200、テナントヘッダを変えても 1 つの台帳、2 クライアントで 1 つの上限）、Emulator の固定スコープ検証。設定ミスは R01 の 503 で拒否側に倒れる |

### 9.4 本番での確認（`vf-app-00020-cd7`、13:09〜13:12、非破壊）

存在しない架空アカウントに誤ったパスワードでサインインしただけで、サインインの成功や外部への送信はありません。

| 確認内容 | 結果 | 判定 |
|---|---|---|
| トラフィック／ヘルスチェック | `vf-app-00020-cd7` 100%、`healthy`（firestore connected） | ✅ |
| (b) 同一アカウントに 5 回、その後先頭に 5 KB の偽の値を入れて 6 回（再レビューの 2 行目と同じ条件） | `401×5 → 429×6`（修正前は「401 が 5 回追加」だった） | ✅ |
| (a) 21 個の別アカウント、毎回先頭を変更（再レビューの 3 行目と同じ条件） | `401×20 → 429`（21 回目で送信元制限。修正前は 25/25 通過） | ✅ |
| (c) Cloud Logging の `httpRequest.remoteIp` | 上記 32 件すべて確認用端末の実 IP（`113.161.32.84`）、`401×25`・`429×7`、503 は 0 件 | ✅ |
| `MULTI_TENANT` | 未設定（無効）。`STORE_BACKEND=firestore`、`ANONYMOUS_ROLE=viewer` | ✅ |
| TTL（`login_throttle.expire_at`） | `ACTIVE` | ✅ |

(a)(b) は、「呼び出し側が書いた要素をどう変えても、Cloud Run が追加した最後の要素で数えられる」ことを、本番のヘッダ経路で示しています。また Next.js 16.3.5 は `x-forwarded-for` が無い場合にしか設定しない（`??=`、`base-server.js`）ことをソースで確認しました。ただし、確認は 1 つの送信元からのみです。「別の実 IP が別バケットになること」は、本番では確認していません（Flask 側の既存のレート制限も同じ要素に依存しています）。

R02〜R04 はマルチテナント用の修正です。本番は単一テナントのため、確認はテストと Emulator によるものです。本番では `/internal/*` はインターネットから到達できません（4.2 節）。

### 9.5 引き続き記録する制約（再レビューの要請どおり）

- ゲスト入口を再開すると、有効期限内のゲストトークンは再び使える（S01、選択した方針）。
- 固定ウィンドウのため、境目をまたぐと最大 2 倍まで通る可能性がある。
- 同一テナントでの同時 publish は遅延する（55〜155 秒）。
- 取り込み経路はマルチテナント未対応。`case_id` の所属検証は `/internal/execute` のみ。
- 本章の結果は「全体が安全であることを検証した」ものではなく、上記の条件を上記の方法で確認したものです。
- 分離構成（executor を別サービスにする構成）では、executor がケースを参照できる共有 Firestore が必要になる（R02 の `case_id` 検証のため）。現在の本番は 1 サービス構成で、この経路は使っていない。

---

## 付録：主な変更ファイル

| 区分 | ファイル |
|---|---|
| バックエンド | `src/vf_logistics/governance.py`、`store.py`、`app.py`、`auth.py`、`tenant.py`、`membership.py`（新規） |
| フロントエンド | `frontend/src/lib/proxy-policy.ts`、`session.ts`、`rate-limit.ts`、`login-limit.ts`（新規）、`tenant-choice.ts`（新規）、`identity.ts`、`app/api/auth/login/route.ts`、`app/api/proxy/[...path]/route.ts`、`app/governance/page.tsx`、`components/layout/TenantSwitcher.tsx` |
| テスト（新規） | `tests/test_boundary_schema.py`、`test_boundary_history.py`、`test_login_throttle.py`、`test_membership.py`、`test_firestore_emulator.py`、`frontend/src/lib/login-limit.test.ts`、`tenant-choice.test.ts` |
| 検査スクリプト | `scripts/check_test_sensitivity.py`（初回 13 件を追加して合計 49 件。再レビューで 13 件追加・2 件更新して合計 61 件、vitest 対応） |
| 再レビュー R01〜R04 | `frontend/src/lib/rate-limit.ts`、`login-limit.ts`、`identity.ts`、`tenant-choice.ts`、`components/layout/TenantSwitcher.tsx`、`app/api/auth/{login,logout,judge}/route.ts`、`src/vf_logistics/auth.py`、`app.py`、`membership.py`、`executor_client.py`、`store.py`、`docs/ARCHITECTURE.md`。テスト新規：`frontend/src/lib/rate-limit.test.ts`、`app/api/auth/login/route.test.ts`、`components/layout/TenantSwitcher.test.tsx`、`tests/test_internal_execute.py` |
| ドキュメント | `README.md`、`SUBMISSION.md`、`docs/ARCHITECTURE.md` |
