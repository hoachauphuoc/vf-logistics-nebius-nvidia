# VF Logistics 認可レビュー是正報告書

| 項目 | 内容 |
|---|---|
| 対象リポジトリ | `hoachauphuoc/vf-logistics-nebius-nvidia` |
| レビュー対象 | コミット `bd6a210`（2026-10-11 付 認可レビュー報告書） |
| 是正後コミット | `923d36f`（`origin/master` と一致） |
| 本番環境 | Cloud Run `vf-app`（`vf-fraud-detection-phuochoa` / asia-southeast1）、リビジョン `vf-app-00019-9tl`（トラフィック 100%） |
| 再テスト実施 | 2026-10-12 08:56〜09:22（JST） |
| 結論 | **指摘 8 件すべてを是正し、本番へデプロイ済み。再テストで全項目合格。** |

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
| **A04** | メールアドレスの空白差でレート制限を回避でき、制限もインスタンスごとだった | メールを一度だけ正規化（trim＋小文字化）し、その値で計数と照合を行う。制限は「アカウントごと 5 回／分」「送信元ごと 20 回／分」の 2 系統。カウンタは Flask の `/internal/login-throttle` 経由で Firestore `login_throttle` に共有。取得できない場合のみインスタンス内カウンタにフォールバック |

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
| 21:51 | `923d36f` | Emulator で発見した同時実行問題の修正、Emulator テスト追加 | **`vf-app-00019-9tl`**（22:00、現行） |

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
| マルチテナント | 本番では未有効。取り込みシンクはテナントを解決しないため、`MULTI_TENANT=true` では動作しない。`/internal/execute` は、テナント内で `case_id` が属するかを検証しない（既知の制限として ARCHITECTURE に記載） |
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
2. マルチテナントを本番で有効にする場合は、`VF_TENANT_MEMBERS` を Secret Manager に登録した上で、取り込みシンクのテナント対応を先に行う必要があります。

---

## 付録：主な変更ファイル

| 区分 | ファイル |
|---|---|
| バックエンド | `src/vf_logistics/governance.py`、`store.py`、`app.py`、`auth.py`、`tenant.py`、`membership.py`（新規） |
| フロントエンド | `frontend/src/lib/proxy-policy.ts`、`session.ts`、`rate-limit.ts`、`login-limit.ts`（新規）、`tenant-choice.ts`（新規）、`identity.ts`、`app/api/auth/login/route.ts`、`app/api/proxy/[...path]/route.ts`、`app/governance/page.tsx`、`components/layout/TenantSwitcher.tsx` |
| テスト（新規） | `tests/test_boundary_schema.py`、`test_boundary_history.py`、`test_login_throttle.py`、`test_membership.py`、`test_firestore_emulator.py`、`frontend/src/lib/login-limit.test.ts`、`tenant-choice.test.ts` |
| 検査スクリプト | `scripts/check_test_sensitivity.py`（ミューテーション 13 件を追加、合計 49 件） |
| ドキュメント | `README.md`、`SUBMISSION.md`、`docs/ARCHITECTURE.md` |
