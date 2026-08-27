# Benchmark Source

`benchmarks/` là nơi duy nhất chứa tracked source và procedure cho benchmark, hardware test và performance measurement của project.

## Ranh giới với các thư mục khác

```text
tests/
→ software unit/regression/parser/state/backend contract tests

benchmarks/
→ tracked benchmark và hardware measurement source/procedure

logs/benchmarks/
→ ignored raw output và generated result

data/
→ ignored benchmark/runtime input

docs/
→ methodology, accepted conclusions và historical report
```

Generated output không được ghi vào `benchmarks/`. Runner phải ghi vào `logs/benchmarks/<topic>/<run-id>/` hoặc path runtime tương đương đã document.

## Policy HOST-first bắt buộc

Mọi benchmark hoặc hardware measurement được dùng để đưa ra kết luận kỹ thuật phải có tracked source/procedure trên HOST **trước khi chạy trên Jetson**.

Không được tạo benchmark/test source trực tiếp trên Jetson.

Không chấp nhận:

```text
SSH Jetson
→ viết test.py
→ chạy
→ lấy con số
→ xóa test.py
```

Không chấp nhận paste một command loop dài trên Jetson, lấy result để chọn model/architecture rồi không lưu procedure trong Git.

Workflow chuẩn:

```text
HOST
benchmarks/<topic>/...
→ review/syntax/software test
→ git diff --check
→ commit
→ push origin dev

JETSON
git pull origin dev
→ chạy exact tracked benchmark
→ ghi logs/benchmarks/<topic>/<run-id>/
→ đưa accepted conclusion vào docs/
```

## Jetson execution-only policy

Jetson là target để chạy runtime, hardware test và benchmark. Jetson không phải nơi phát triển tracked benchmark source. Nếu cần sửa runner/procedure, quay lại HOST, sửa, review, commit/push rồi Jetson pull lại.

## Debug command và accepted measurement

Các command tương tác ngắn như `ls`, `cat`, `grep`, `top`, `ps`, `free`, `--help` hoặc `aplay` được phép chạy trực tiếp trên Jetson để inspect/debug.

Ranh giới:

- Dùng `top` để xem nhanh CPU: debug, được phép.
- Thu 15 CPU sample để kết luận CPU giảm 81.5%: benchmark; sampling procedure phải được track dưới `benchmarks/` trước khi chạy.
- Xem một transcript để debug: được phép.
- Dùng nhiều transcript để kết luận model accuracy: benchmark; input selection, normalization và metric phải được track.

Nếu một measurement sẽ xuất hiện trong benchmark comparison, architecture decision, README, performance report hoặc model selection thì procedure đo bắt buộc là tracked benchmark source.

## Yêu cầu reproducibility

Mỗi benchmark directory phải có README/runbook hoặc runner ghi rõ tối thiểu:

- mục tiêu và câu hỏi kỹ thuật;
- target hardware/OS;
- model/backend/runtime identity;
- input và manifest/fixture;
- exact command/config;
- environment variables;
- warmup policy;
- sample count/repetition;
- metric và công thức;
- generated output location;
- cách chạy trên HOST/Jetson;
- cách tính summary;
- điều kiện PASS/FAIL nếu đã được chốt trước.

Python/shell runner phải được track. Nếu benchmark chỉ cần vài command, procedure vẫn phải nằm trong README hoặc script tracked; không chỉ tồn tại trong shell history/chat.

Mỗi result cần trace được về Git commit, runtime/model version, config, input manifest, timestamp/timezone và target hardware.

## Naming convention

Tên directory và runner phải mô tả purpose. Không dùng `test.py`, `bench.py`, `run2.py`, `new_test.py` hoặc `benchmark_final.py`.

Ví dụ hợp lệ:

```text
benchmark_stt_backend.py
benchmark_noise_robustness.py
benchmark_speech_gating.py
benchmark_llm_latency.py
```

Hoặc dùng directory purpose-specific để filename ngắn mà vẫn rõ.

## Cấu trúc mục tiêu

```text
benchmarks/
├── README.md
├── stt/
│   ├── backend_comparison/
│   ├── noise_robustness/
│   └── speech_gating/
├── audio/
├── llm/
└── full_pipeline/
```

Không tạo empty directory chỉ để hoàn thiện sơ đồ. Chỉ tạo topic directory khi có source/procedure thật.

## Software test hay benchmark?

Đặt trong `tests/` nếu test dùng fake/mocked dependency và kiểm tra deterministic contract như parser, state transition, queue lifecycle, feature flag hoặc request format.

Đặt trong `benchmarks/` nếu cần microphone, Jetson, model weight, real runtime/server hoặc dùng CPU/RAM/latency/accuracy để so sánh và đưa ra quyết định.

Một hardware-dependent integration measurement là benchmark, dù filename cũ từng bắt đầu bằng `test_`.

## Historical benchmark

Các benchmark trước policy này có thể chỉ còn accepted report trong `docs/`; raw implementation hoặc result cũ có thể đã bị xóa. Không dùng lại procedure lịch sử không còn reproducible làm baseline mới.

Từ thời điểm policy này có hiệu lực, mọi benchmark mới phải có tracked producer/procedure trong `benchmarks/` trước lần chạy chính thức đầu tiên.

## Benchmark tiếp theo

STT noise robustness sẽ so sánh:

```text
Whisper Tiny.en
vs
Zipformer 2023-06-21

clean / noisy
GTCRN OFF / ON
```

VoiceBank-DEMAND `prepared_15/` được giữ dưới `data/stt/voicebank_demand/` làm runtime input. Task cleanup này chưa tạo runner mới; runner/procedure phải được phát triển trên HOST dưới `benchmarks/stt/noise_robustness/` ở task tiếp theo.
