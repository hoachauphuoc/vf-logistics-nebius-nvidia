# Báo cáo khắc phục sau tái kiểm chứng độc lập VI (17/10/2026)

- Nguồn: `Floorline_Independent_Reverification_VI_20261017.pdf` (kiểm tra mã `76e6b01`)
- Commit sửa: `83826f6` trên nhánh `reverification-vi-fixes` (chưa push, chưa mở PR, chưa triển khai)
- Mọi số liệu dưới đây lấy từ log của runner trong `orchestrator/runs/` (VFULL, V2, VMYPY, VGIT) và `attempt_N.log` của từng task. Số nào chưa đo thì ghi rõ "chưa đo".

## 1. Kết luận

Ba hạng mục còn mở trong báo cáo tái kiểm chứng (N06, N01, N08) đã được sửa trong repository bằng 5 task nhỏ. Cả 5 task qua kiểm tra của runner; bộ kiểm tra đầy đủ chạy lại trên cây đã commit đều xanh. Phần ngoài repository (bên nhận, Firestore thật, Pub/Sub thật, trình duyệt thật, CI trên commit mới) **chưa được kiểm chứng**; xem mục 5.

## 2. Đã sửa gì

| Task | Hạng mục | Lỗi trong báo cáo tái kiểm chứng | Cách sửa | File |
|---|---|---|---|---|
| N06e | N06 (P1) | `origin_country` dạng `["not stated","China"]` hoặc `["China","PRC"]` được coi là "đã cung cấp" nhưng không bị so với khai báo: 0 mâu thuẫn, phê duyệt release không cần lý do. Chuỗi `"China"` thì bị bắt. | Hàm mới `_stated_country` đọc một trường theo các giá trị còn nêu rõ và trả về đúng một quốc gia chuẩn hóa (hoặc rỗng nếu không có/nhiều hơn một). Phần kiểm tra mâu thuẫn của chứng nhận xuất xứ và hóa đơn dùng hàm này. Chỉ thêm mâu thuẫn, không bao giờ hạ sàn rủi ro. Trường nêu hai quốc gia khác nhau vẫn "chưa chứng minh" như cũ. | `verifier.py`, `tests/test_origin_inputs.py` |
| N01e1 | N01 (P1) | Lỗi hết hạn của Google SDK (`DeadlineExceeded`, `RetryError`) bị ghi là "failed", đọc như "chưa gửi". | Hàm `_may_have_been_accepted` nhận ra `TimeoutError` và hai lớp trên theo tên lớp (không cần import `google.api_core`). Các lỗi khác vẫn là "failed". | `tools.py`, `tests/test_publish_dedupe.py` |
| N01e2 | N01 (P1) | Broker đã nhận tin nhưng lưu bản ghi lỗi một lần: mất ID tiếp nhận, hồ sơ thành EXECUTION_FAILED, Retry publish lại lần hai. | Biến `accepted` ghi nhớ tin đã được nhận. Nếu lưu bản ghi lỗi thì bản ghi được lưu lại, kèm `message_id`, trạng thái "done"; bên gọi đọc là đã gửi. | `tools.py`, `tests/test_resume_after_publish.py` |
| N08g | N08 (P2) | Sau lỗi mạng ở bước approve/execute, màn hình không tải lại hồ sơ, vẫn ở trạng thái trước phê duyệt. | Lỗi kết nối (`ApiError` loại "unreachable") gọi `onDecided()` để tải lại hồ sơ. Từ chối do máy chủ trả lời (409) không tải lại. | `ReviewPanel.tsx`, `ReviewPanel.test.tsx` |
| N08h | N08 (P2) | Trang hồ sơ đọc một lần; hồ sơ đã hoàn tất vẫn hiện "gián đoạn, claim hết hạn" kèm nút Resume. | Hàm `caseRefetchMs`: hồ sơ ở trạng thái EXECUTING được đọc lại mỗi 15 giây, các trạng thái khác không. Trang hồ sơ dùng làm `refetchInterval`. | `operations.ts`, `operations.test.ts`, `cases/[id]/page.tsx` |

Task N01e2 cần một vòng RERUN: lệnh mypy trong `test_commands` do tôi viết yêu cầu `tools.py` sạch, trong khi 2 lỗi `no-any-return` ở dòng 200 và 290 có từ trước và nằm ngoài phần sửa. Mã và test đã pass ngay lần đầu; tôi thay lệnh đó bằng ruff rồi chạy lại. Hai lần chạy cho cùng một diff.

## 3. Kết quả kiểm tra (cây đã commit `83826f6`)

| Hạng mục | Kết quả | Mốc so sánh (CLAUDE.md, `85685a2`) |
|---|---|---|
| Backend `pytest tests/` | **1574 passed, 16 skipped** (187 s) | 1486/16 ở `85685a2`; 1564/16 ở báo cáo trước (+10 test của đợt này) |
| Frontend `npm test` (vitest) | **355 passed**, 26 file | 350 ở báo cáo trước (+5) |
| `mypy src/vf_logistics/` (cổng VFULL đã sửa: `mypy exit 1 errors 120 stopped early False`) | **120 lỗi** | 122 (trần CI 123) |
| mypy nghiêm ngặt `verifier.py`, `observability.py`, `evaluation.py` | sạch | sạch |
| `ruff check` | sạch | |
| `tsc --noEmit` | sạch | |
| `npm run lint` | sạch | |
| `scripts/verify_review_vi.py` (chạy trong VR1/VR2) | **32/32 mục đếm được đạt**, 9/9 hạng mục "fixed", 1 mục ngoài phạm vi (N01-e) | 27/27 trước khi thêm 5 hàng mới |

16 test bị bỏ qua cần Firestore emulator; số này không đổi.

Các test mới (7 + 2 + 1 trường hợp backend; 3 + 2 frontend) đều được chạy xanh. Việc "test mới fail trên mã cũ" **chưa đo bằng runner** (không có lượt chạy đỏ trước khi sửa); đó là suy luận từ việc đọc mã, ví dụ N06e: bản cũ bỏ qua danh sách nên cả 6 trường hợp tham số hóa sẽ fail. Nếu cần bằng chứng đo được, chia mỗi task thành cặp test-trước/mã-sau như N03d1t/N03d1c.

## 4. Hai điều đã phát hiện trong lúc kiểm tra, và đã xử lý

1. **Ngưỡng mypy trong `VFULL` từng không kiểm tra gì.** `mypy src/vf_logistics/` thoát mã 2 và dừng sớm với "Found 1 error ... (errors prevented further checking)": stub của numpy dùng cú pháp `type` của Python 3.12+. Lệnh cũ đọc "1 ≤ 123" và báo đạt. **Đã sửa trong plan:** lệnh mới truyền `--python-version` của Python đang chạy, và thất bại khi mypy dừng sớm (mã thoát lớn hơn 1 hoặc có "prevented further checking") hoặc khi vượt 123. Lần chạy `VFULL` sau khi sửa in `mypy exit 1 errors 120 stopped early False` và đạt. **Chưa thử trường hợp mypy dừng sớm với lệnh mới** (chưa cố tình tạo lại lỗi để xem cổng đỏ). Khi commit tôi đã nói sai rằng `VFULL` không chạy mypy; thực tế nó chạy, nhưng cổng bị vô hiệu như trên.
2. **Bảng kiểm tra thiếu hàng cho các sửa mới.** **Đã thêm** 5 hàng vào `scripts/verify_review_vi.py` (task VR1, VR2): N06-f (danh sách quốc gia, 6 test), N01-g (lỗi SDK, 1 test), N01-h (bản ghi đã nhận nhưng lỗi khi lưu, 1 test), N08-f (tải lại sau mất kết nối, 3 test), N08-g (đọc lại mỗi 15 giây, 1 test), cùng việc cho `src/lib/operations.test.ts` chạy trong lệnh vitest của script. Bảng hiện 32/32. Lưu ý: script này vẫn đang sửa dở trong cây làm việc (gồm cả các hàng N01-f, N03-c, N06-e của bạn) và chưa commit. Con số "27 mục" trong báo cáo khắc phục trước khớp với bảng của bản script chưa commit này, không khớp với 25 mục của script tại `76e6b01`.

Ghi chú về runner: `attempt_N.diff` không liệt kê file có `[id]` trong đường dẫn (`cases/[id]/page.tsx`) dù file đã sửa đúng. Ở VR1 sub-agent chèn thừa một dòng trống trong danh sách `CHECKS` (hợp lệ về cú pháp); tôi đã xóa dòng đó (1 dòng, ngoại lệ ≤5 dòng của CLAUDE.md).

## 5. Chưa kiểm chứng / còn mở

- **Bên nhận ngoài repository:** chưa chứng minh nghiệp vụ phía nhận chỉ áp dụng một lần. Thuộc tính `idempotency_key` đã được gửi kèm, nhưng việc bỏ bản lặp là việc của bên nhận.
- **Tiến trình chết giữa lúc broker nhận và lúc lưu bất kỳ bản ghi nào** (ví dụ `CancelledError`): chưa có biện pháp trong repository; Resume sau khi hết claim vẫn có thể publish lại. Nếu lần lưu thứ hai cũng lỗi, ngoại lệ vẫn tới bên gọi như trước và ID tiếp nhận có thể mất.
- **Firestore thật hoặc emulator:** 16 test bị bỏ qua; chưa kiểm tra tranh chấp claim, lỗi lưu, phục hồi sau gián đoạn.
- **Pub/Sub thật và trình duyệt thật:** chưa kiểm tra. Các test frontend chạy trên React/jsdom với API giả.
- **CI trên GitHub:** commit `83826f6` chưa push nên chưa có kết quả CI. Cần chạy `PDCI` sau khi push và merge.
- **Chưa đo:** độ chính xác trích xuất của mô hình thật, tỷ lệ xử lý ngoại lệ của nhân viên, chi phí và thời gian thực.
- Trạng thái triển khai: chưa triển khai. Việc triển khai là bước của con người.

## 6. Việc cần làm tiếp

1. Đọc `git diff 83826f6~1 83826f6`, rồi push nhánh và mở PR (con người thực hiện).
2. Commit các thay đổi sau `83826f6`: `scripts/verify_review_vi.py` (bản sửa dở của bạn cùng 5 hàng mới) và `orchestrator/execution_plan.md` (lệnh mypy mới của `VFULL`, task `VMYPY`, `VR1`, `VR2`).
4. Sau khi push: chạy `PDCI` để xác nhận CI xanh trên đúng commit.
5. Với phần "chưa kiểm chứng" ở mục 5, lập kế hoạch kiểm thử riêng trên môi trường đã triển khai thử.

## 7. Thay đổi trong cây làm việc không thuộc đợt này (không nằm trong commit)

`docs/architecture.html`, `eval.json`, `orchestrator/archive/`. Còn `scripts/verify_review_vi.py` và `orchestrator/execution_plan.md` có thay đổi sau commit `83826f6` (xem mục 6, bước 2); `orchestrator/reverification_vi_fix_report.md` là file mới.
