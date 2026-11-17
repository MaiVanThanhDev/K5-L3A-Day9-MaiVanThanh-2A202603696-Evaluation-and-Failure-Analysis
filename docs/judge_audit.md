# Judge audit

Chạy: `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10` và `python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5` (judge replay, không cần key).

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Tỉ lệ fail quan sát → hiệu chỉnh RG | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | **Đạt** | dùng (chỉ để theo dõi, không gate tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.09 → 0.30 | **Không đạt** (κ, R) | loại |

## Audit thủ công các case bất đồng
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em… nha" quá suồng sã với khách khiếu nại. Rubric thêm: "xưng LogiX / anh/chị; cấm 'em… nha', 'bạn ơi'" |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Judge coi "bạn ơi" là thân thiện. Cùng sửa như #1, thêm ví dụ âm tính vào few-shot |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn "Dạ, vui lòng". Rubric: "giọng ra lệnh/đuổi khách là FAIL dù có kính ngữ" |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric: "xin lỗi không bắt buộc khi đã giải quyết xong; ngắn gọn đủ ý là PASS" |
| 5 | H-051 "…đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép "refund". Rubric thêm whitelist thuật ngữ: refund, ship, COD |
| 6 | H-063 "…sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống: thực ra là lỗi nội dung (gần FM-08), không phải giọng. Tách ra cho grader code, không giao cho judge tone |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | Người | Rubric: "emoji cười trong ngữ cảnh khiếu nại là FAIL" |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket). Sửa nhãn người; không đổi rubric. Case này cho thấy nhãn người cũng cần double-check |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Người (ranh giới) | Lặp "Dạ" do gõ, không ảnh hưởng giọng. Rubric: "lỗi gõ nhẹ không phải lỗi giọng" |
| 10 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Rubric: "tiếng Việt không dấu / dịch máy là FAIL" |
| 11 | HL-015 "…đã hoàn 55.000đ cho đơn O-112" (ledger 40.000) | PASS | FAIL | Người | Judge không thấy ledger nên không thể biết sai tiền. Đây là FM-08, phải chấm bằng code (`reply_matches_ledger`), không bằng judge |
| 12 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Sai xưng hô + không nói kết quả. Judge helpful bỏ qua |

## Kết luận
- **tone_ok dùng được**: κ=0.757, P=0.857, R=0.80 đều qua sàn. 7/10 bất đồng là judge dễ dãi với giọng suồng sã (fn=6), 1 case nhãn người sai. Sửa rubric theo bảng trên rồi calibrate lại trên nhãn mới.
- **helpful bị loại, không được làm gate**: P=1.0 nhưng R=0.30 (21 fn / 30 lỗi thật), κ=0.375 < 0.6. Judge gần như luôn nói PASS: bỏ sót 70% reply sai. 18/21 fn là **sai tiền**: judge chỉ đọc văn bản, không đọc ledger, nên về nguyên tắc không thể chấm đúng. Tỉ lệ fail quan sát 0.09, sau hiệu chỉnh Rogan-Gladen là 0.30: nếu dùng judge này, ta sẽ báo cáo thấp hơn thực tế khoảng 3 lần. Gate trên judge này sẽ cho qua phần lớn regression về tiền. Thay thế: `reply_matches_ledger` (code) cho FM-08; phần "có nói rõ kết quả/hỏi lại mã đơn" cần rubric mới + calibration lại.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (có thể đã bị "học" khi viết rubric); cần nhãn người mới làm held-out thật. Precision 1.0 của helpful không cứu được nó: judge chỉ nói FAIL ở 9 case lộ liễu nhất, nên hiếm khi sai khi nói FAIL nhưng bỏ sót gần hết lỗi.
