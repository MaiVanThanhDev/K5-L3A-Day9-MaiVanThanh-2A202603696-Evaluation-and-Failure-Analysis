# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

Output thật (rút gọn):
```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {"allowed_tools": ["lookup_order", "lookup_policy", "compute_compensation"], ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-515", ...}}}
   3 quote              {"amount_vnd": 150000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03", "DMG-04"], ...}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal           {"amount_vnd": 120000}
   6 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
-- ledger vs label
  refund_vnd     ledger=90000    label=120000   <-- differs
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, report `reports/eval_seeded_regression.json` (run `E-seeded_regression-20261117-539e`) |
| Triệu chứng | `pass_rate`, `refund_amount_correct`, `reply_matches_ledger` fail. Reply nói **120.000đ**, ledger ghi **90.000**, nhãn là 120.000 |
| Bước sai đầu tiên | Event **5** `proposal {"amount_vnd": 120000}`: agent tự trừ 30.000 đã hoàn trước đó khỏi quote 150.000 |
| Vì sao là bước *đầu tiên* | Event 1–2 đúng (handoff chỉ cho read tool, order O-515 visible). Event 3 `quote` 150.000 đúng max-of-eligible (DMG-04). Event 4 `refund_history` chỉ là đọc, chưa sai. Event 5 là chỗ số tiền bắt đầu lệch so với quote, và host (`durability.issue_refund`) lại trừ 30.000 lần nữa theo trần đơn → 90.000 |
| Failure mode | **FM-05** (pre_deducted) là nguyên nhân; **FM-08** (reply ≠ ledger) là hệ quả nhìn thấy được ở event 6 |
| Đối chứng | `fixed C-014@11`: không có event `refund_history`/`proposal`; quote 150.000 đi thẳng vào host, ledger 120.000, reply "120.000đ" → mọi grader pass |
| Regression test | `tests/test_lab9_trace_case.py::test_trace_case_c014_seed11_regression`: chạy lại claim@seed, assert `RefundAmountCorrect` và `ReplyMatchesLedger` đều False trên `seeded_regression` và đều True trên `fixed`. Đã chạy: fail đúng chỗ trên variant lỗi, pass trên `fixed`. Item E-014 cũng ghi `provenance.from_trace = "seeded_regression C-014@11"` |
| Chưa chắc chắn | Trace không cho biết *vì sao* agent trừ trước (MockLLM không có lời giải thích). Với LLM thật có thể vì prompt nhắc "đã được hoàn trước đó". Trace cũng không phân biệt được lỗi này với một host trừ hai lần; phải đọc `business_rules.md` mới biết host là bên được phép trừ |

## Case phụ: swarm C-002@55 (FM-03)
`python -m lab9.trace_case --shape swarm --claim C-002 --seed 55`: event 3 `model_override {"delay_days": 5}` là bước sai đầu tiên (order O-202 có `delay_days=2`), dẫn tới quote 20.000 và ledger 20.000 trong khi nhãn là `denied`/0. Đây là điểm yếu `seed % 5 == 0` của swarm tham chiếu và là lý do baseline có `pass_rate` 0.9857, `db_fact_kept` 0.9857. Grader bước `DbFactKept` bắt được nó; bản `quiet_override` (không ghi event) thì chỉ grader kết quả `RefundAmountCorrect` bắt được.

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được.
