# Floorline 再構築報告書 — Plan 1（検証ループ）＋ Plan 2（運用画面）

| 項目 | 内容 |
|---|---|
| 対象リポジトリ | `hoachauphuoc/vf-logistics-nebius-nvidia` |
| 起点コミット | `2d447e2`（R01–R04 是正完了、rev `vf-app-00020-cd7`） |
| 最終コミット | `9a276cb`（`origin/master` と一致） |
| 本番リビジョン | **`vf-app-00022-fbr`**（トラフィック 100%、2026-10-13 11:47 デプロイ） |
| 変更規模 | 43 ファイル、+6,691 行 / −699 行 |
| テスト | pytest **1,181** 通過（11 スキップ）、vitest 全通過、mypy **123**（CI 上限と一致） |
| CI | 全コミットで **5/5 グリーン**（test / typecheck / lint / frontend / container） |
| 根拠文書 | `Floorline_De_xuat_tai_cau_truc_huong_toi_giai_thuong_VI_20261012.pdf`（12/10/2026 付提案書） |

---

## 1. 概要

12/10 の再構築提案に基づき、次の 2 本の計画を実装・デプロイしました。

- **Plan 1**（検証ループ）：書類不足で保留中のケースに対し、必要な証拠を要求し、受領し、照合し、承認し、実行するまでの一連の流れ。全 8 ステップ。
- **Plan 2**（運用画面）：「今日のケース」「ケース詳細」「成果」の 3 画面と、レビュアーの作業時間計測。全 6 ステップ。

Plan 3（計測・デモ・提出）は未着手です。

---

## 2. Plan 2 — 運用画面（コミット `579f641`、`005f91e`）

### 2.1 実装内容

| # | 項目 | 状態 | 備考 |
|---|---|---|---|
| 1 | ナビゲーション再編 | 完了 | サイドバーを「Your work」と「Verification & oversight」の 2 グループに分割。ログイン後のデフォルトを `/today` に変更 |
| 2 | `/today`（本日のケース） | 完了 | 4 バケット（書類待ち / レビュー待ち / 署名待ち / 実行待ち）。件数はサーバー側で全テナントを集計（`worklist.py`）、ページ内の 40 件ではない |
| 3 | `/cases/[id]`（ケース詳細） | 完了 | タイムライン（到着→finding→エージェント→拒否→要求→決定）＋ ReviewPanel（review/page.tsx から分離）。作業時間を自動計測 |
| 4 | `/outcomes`（成果） | 完了 | 解決件数、解決時間、情報要求回数、モデルコスト/件、保留中、拒否回数。未計測の値はゼロではなくダッシュで表示 |
| 5 | 作業時間記録 | 完了 | `POST /api/v1/cases/<id>/activity`（レビュアーのみ）。`activity.ts` のメーターはアイドル 60 秒で停止、非表示タブは加算しない |
| 6 | テスト | 完了 | vitest: operations / activity / help-registry / proxy-policy。pytest: `test_worklist.py`（26 件、ルート・集計・activity） |

### 2.2 修正した欠陥

| 欠陥 | 原因 | 修正 |
|---|---|---|
| タイムラインの拒否理由が空欄 | `governance.execute` は `detail.gate_reason` に書くが、`operations.ts` がトップレベル `gate_reason`（未使用）を読んでいた | `detail.gate_reason` を優先して読み、トップレベルにフォールバック |
| `/today` がビルド不可 | `WorkCard` と `DUE_TONE` が `today/page.tsx` に重複コピーされていた | 重複を削除、`WorkCard.tsx` に統一 |
| コストタイルが「モデルと検索」と表示 | `_estimated_cost_usd` は Nebius のみ | 「モデルコスト」に修正、注釈追加 |
| CI mypy が `80431c9` 以降レッド | `governance._is_number` が `bool` を返すため `float()` に 2 エラー | `TypeGuard[float]` に変更（`005f91e`）。CI 初めてグリーンに |

### 2.3 本番確認（2026-10-12 18:20）

- `/api/v1/worklist` → total 14 = レビューキュー 14 件（ESCALATED 10, PENDING_HUMAN 3, HELD_FOR_REVIEW 1）
- `/api/v1/outcomes` → resolved 6（ルール 2 / AI 0 / レビュアーrelease 2 / block 2）
- `human_handling_ms` → n=0（計測開始前のため）
- `POST /api/v1/cases/NOPE/activity`（匿名）→ 403
- `GET /api/v1/outcomes?since=yesterday` → 400

---

## 3. Plan 1 — 検証ループ（コミット `7dbd40b`〜`9a276cb`）

### 3.1 設計原則

提案書の条件をそのまま実装しました。

1. **AI は決してリスクフロアを下げない。** 良い証拠は `provided` と報告されるだけでフロアは変わらない。矛盾のみがフロアを上げる。
2. **承認は証拠バージョンに紐付く。** 新しい証拠が届くと既存の承認は `SUPERSEDED` になり、実行できない。
3. **実行直前に全条件を再検証する。** 承認のバージョン、ケースの状態、未処理の要求の有無を再確認した上で Pub/Sub に送信する。
4. **リンクはケースに保存しない。** ケース JSON は viewer が読めるため、トークンを保存すると誰でも「証拠」を提出できる。ケースにはフィンガープリント（12 文字）のみを保持。

### 3.2 各ステップの実装状況

| ステップ | 内容 | コミット | 状態 |
|---|---|---|---|
| **1** | 出自偽装ウォッチテーブル（6 レーン）、`check_origin_inputs`（MEDIUM/45、`blocks_auto_clear`）、`check_origin_evidence`、`EVIDENCE_CATALOGUE`（3 種の書類）、`dossier.json` ルート | `7dbd40b` | 完了 |
| **2** | `evidence.py`：要求・リンク発行・キャンセル。HMAC トークン（ドメイン分離鍵、7 日有効）。`AWAITING_EVIDENCE` 状態。3 ルート | `42517c2` | 完了 |
| **3** | `POST /api/v1/evidence/respond`：トークン認証→ファイル受領→Model Armor→アーカイブ→抽出→バージョン加算→承認無効化。`extract_evidence` を文書種別ごとのプロンプトで実行 | `ed9f7a0` | 完了 |
| **4** | `reevaluate`：出自チェック再実行＋証拠照合→評価レコード→要求クローズ | `045bcd6` | 完了 |
| **5** | `approve`：リリースにはパスワードセッション必須（A01 方針）。証拠バージョンと評価を紐付け | `045bcd6` | 完了 |
| **6** | `execute_approval`：全条件再検証→ツール呼び出し→Pub/Sub 送信。拒否は理由付きで記録。proxy-policy 更新 | `85511f4` | 完了 |
| **7** | lineage に `evidence_version`・`approval_id`・`provenance_uri` を追加 | `0dfe79e` | 完了 |
| **8** | `seed_verification_demo.py`：合板 2 ケースを投入 | `0dfe79e` | 完了 |

### 3.3 ステップ 1 で発見した設計上の欠陥

計画では `ORIGIN_INPUTS_UNVERIFIED` を `MEDIUM`・floor 45 としていました。しかし実装中にホワイトリストの仕組みを読んだところ、`_floor_for` と `validate` の `skip_ai` は **HIGH/CRITICAL 以外のすべての finding を無視して** `auto_clear_by_rules` を判定することがわかりました。

つまり、ホワイトリスト登録済みの荷送人が出自偽装の疑いがあるレーンで貨物を送った場合、**MEDIUM の finding は無視され、無人で通関される** ことになります。

修正：`blocks_auto_clear` フラグを追加し、`_floor_for`・`validate.skip_ai`・`orchestrator.competing` の 3 箇所で HIGH/CRITICAL と同等に扱うようにしました。severity を HIGH に上げる案は **採用しませんでした**。理由：2 件の HIGH finding があると相関ルール（floor 80）が発動し、スコアが歪むため。

ミューテーションテスト `"P1: a whitelisted shipper's cargo on a watched lane is cleared by the rules"` がこの修正を検証しています。

### 3.4 出自ウォッチの影響測定

| コーパス | 件数 | 一致 | 備考 |
|---|---|---|---|
| 合成（1,000 件） | 0 | — | FPR 変動なし（テストで固定） |
| 公開判例（38 件） | 10 | 6 詐欺＋4 対照 | README/SUBMISSION は「保留待ち」と記載すべき（「検出」ではない）。Plan 3 でベンチマーク再実行が必要 |

### 3.5 トークンのセキュリティ設計

| 項目 | 仕様 |
|---|---|
| 署名 | HMAC-SHA256 |
| 鍵 | `HMAC(VF_SESSION_SECRET, b"evidence-response\x00")` — セッション鍵からのドメイン分離 |
| ペイロード | `{v, t(テナント), c(ケース), r(リクエスト), s(シーケンス), e(有効期限)}` |
| 有効期限 | 7 日 |
| 無効化 | 新しいリンクを発行すると `link_seq` が上がり、旧リンクの `s` と一致しなくなる |
| 保存 | ケース JSON には **保存しない**（viewer が読めるため）。`outbox` に 12 文字のフィンガープリントのみ |
| 応答ヘッダ | `Cache-Control: no-store` |
| 失敗応答 | 不正・偽造・期限切れ・別鍵のいずれも **同一レスポンス**（区別不能） |

テスト `"P1.2: the link key is the session secret itself"` は、セッション鍵そのもので正しい形式のリンクに署名し、それが拒否されることを確認しています（ドメイン分離がなければ通過してしまう）。

### 3.6 新しい状態遷移

```
HELD_FOR_REVIEW / ESCALATED / PENDING_HUMAN
    │  reviewer: request-evidence
    ▼
AWAITING_EVIDENCE  ── cancel (理由必須) ──▶ 元の状態に復帰
    │  shipper: evidence/respond
    │  reviewer: reevaluate
    ▼
HELD_FOR_REVIEW / ESCALATED  （評価結果による）
    │  reviewer: approve （リリースにはパスワード必須）
    ▼
APPROVED
    │  reviewer: execute （全条件再検証）
    ▼
RELEASED_BY_HUMAN / BLOCKED_BY_HUMAN
```

`AWAITING_EVIDENCE` は `TERMINAL`（エージェントは何もしない）だが `AWAITING_HUMAN` には含まない（`human_decide` で決定できない）。キャンセルが唯一の脱出口。

### 3.7 テスト

| ファイル | 件数 | 対象 |
|---|---|---|
| `test_origin_inputs.py` | 30 | ウォッチテーブル、ホワイトリスト防御、証拠照合、`dossier.json` ルート |
| `test_evidence_request.py` | 61 | トークン（署名・偽造・期限切れ・ドメイン分離）、要求、リンク、キャンセル、ルート |
| `test_evidence_respond.py` | 19 | 受領、バージョン加算、コスト集計、承認無効化、Model Armor、ルート |
| `test_evidence_eval_approve.py` | 12 | 再評価、承認、パスワード要件、未処理要求ガード |
| `test_evidence_execution.py` | 6 | 実行、拒否記録、Pub/Sub 未呼び出し確認 |

ミューテーション：Plan 1 分 **18 件**（ステップ 1：7 件、ステップ 2：11 件）。ステップ 3–8 分は未実行。

---

## 4. 未完了事項

### Plan 1

| 項目 | 理由 |
|---|---|
| `frontend/src/app/respond/[token]/page.tsx` | 荷送人がリンクを開いてファイルをアップロードする画面。バックエンドは完成しているが、フロントエンドの公開ページが未作成 |
| `scripts/make_origin_evidence_docs.py` | デモ用 PDF（C/O、生産者申告書、仕入れ請求書）の生成スクリプト。未作成 |
| Emulator テスト | `verification` の楽観ロック競合テストを `test_firestore_emulator.py` に追加していない |
| 本番での実地検証 | `seed_verification_demo.py` → ルート A/B を本番で走破 → `message_id` 確認。未実施 |
| ミューテーション（ステップ 3–8） | コミット後に実行予定だったが未着手 |

### Plan 2

| 項目 | 理由 |
|---|---|
| 専用の `test_activity.py` | テストは `test_worklist.py::TestRecordingActivity`（4 件）＋ `activity.test.ts`（7 件）に存在するが、独立ファイルではない |

### Plan 3（全体が未着手）

- `data/verification_cases.json`、`scripts/run_verification_eval.py`
- 公開ベンチマーク再実行、Super/Ultra モデル比較
- デモ動画撮影、`SUBMISSION.md` 最終更新
- 機能凍結＋独立走破テスト

---

## 5. 本番デプロイ履歴

| リビジョン | コミット | 日時 | 内容 |
|---|---|---|---|
| `vf-app-00020-cd7` | `8d830c1` | 10-12 13:04 | R01–R04 是正 |
| `vf-app-00021-m2h` | `579f641` | 10-12 18:17 | Plan 2（運用画面） |
| `vf-app-00022-fbr` | `9a276cb` | 10-13 11:47 | Plan 1＋Plan 2 全体 |

---

## 6. 公表済みの制約事項（変更なし）

前回の是正報告書に記載した制約事項は引き続き有効です。

- ゲスト入口を再開すると、有効期限内のゲストトークンは再び使用可能
- 固定ウィンドウ方式のため、境界付近で最大 2 倍の試行が通過する可能性
- `publish_decision` の同時実行時の遅延
- データ取込パスのマルチテナント未対応

これらに加え、Plan 1 で新たに次の制約が発生しています。

- **証拠抽出はモデルに依存する。** 偽造された証明書を正しく読んだ場合でもフロアは **下がらない**（人間の承認が必要）。モデルが誤読した場合はフロアが **上がる** 可能性がある（誤警報→レビュアーが判断）
- **シッパー向けページが未実装。** リンクは発行されるが、アップロード用の公開ページがないため、API を直接呼ぶか `curl` で送信する必要がある
- **`AWAITING_EVIDENCE` 中はケースを決定できない。** キャンセル（理由必須）が唯一の復帰手段
