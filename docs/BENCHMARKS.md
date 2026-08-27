# Benchmark Reference

## 1. Mục đích

Tài liệu này định nghĩa ranh giới và workflow benchmark mới của project. Benchmark infrastructure cũ đã được reset: raw runner/result cũ không còn được dùng làm nền cho benchmark mới; accepted conclusion lịch sử vẫn được giữ trong report.

## 2. Phân loại Code / Data / Result / Report

~~~text
tests/
→ software unit/regression tests

benchmarks/
→ tracked benchmark/hardware/performance source và procedure

data/
→ ignored benchmark/runtime input

logs/benchmarks/
→ ignored generated output và raw result

docs/
→ methodology, accepted conclusions và reports
~~~

tests/ không chứa board benchmark. benchmarks/ không chứa generated output. logs/benchmarks/ không chứa runnable source.

## 3. Software test và hardware benchmark

| Loại | Đặc điểm | Vị trí |
|---|---|---|
| Software regression | Deterministic; có thể dùng fake/mock; kiểm tra parser, request format, queue, state, lifecycle, feature flag | tests/ |
| Board/model benchmark | Cần Jetson, microphone, model weight, real runtime/server hoặc đo CPU/RAM/latency/accuracy | benchmarks/ |
| Hardware-dependent integration measurement | Đo behavior/performance của nhiều runtime component trên board | benchmarks/ |
| Benchmark input | Dataset, WAV, parquet và manifest | data/ |
| Generated/raw benchmark result | JSONL, CPU sample, memory sample và transcript capture | logs/benchmarks/ |

Tên file bắt đầu bằng test_ không làm một board measurement trở thành software test; phân loại dựa trên dependency và mục tiêu.

## 4. Quy trình benchmark HOST -> Jetson

Mọi benchmark hoặc hardware measurement dùng để đưa ra kết luận kỹ thuật phải có tracked source/procedure trên HOST trước khi chạy trên Jetson.

~~~text
HOST
benchmarks/<topic>/...
→ review
→ syntax/software test
→ git diff --check
→ commit
→ push origin dev

JETSON
git pull origin dev
→ chạy exact tracked benchmark
→ ghi logs/benchmarks/<topic>/<run-id>/
→ collect raw result

HOST
→ review evidence
→ cập nhật accepted report trong docs/
~~~

Không được tạo benchmark/test source trực tiếp trên Jetson.

Không chấp nhận:

- viết test.py tạm trên Jetson, chạy rồi xóa;
- paste command loop dài để thu official samples nhưng không lưu procedure;
- dùng con số từ shell history/chat để quyết định architecture/model mà không có tracked producer.

Nếu cần sửa runner, quay lại HOST, commit/push rồi Jetson pull lại.

## 5. Debug command và accepted measurement

Interactive command như ls, cat, grep, top, ps, free, --help và aplay được phép chạy trực tiếp trên Jetson để inspect/debug.

~~~text
top để xem nhanh CPU
→ debug, được phép

thu 15 CPU samples để kết luận CPU giảm 81.5%
→ benchmark, procedure phải tracked trước
~~~

Nếu measurement sẽ được dùng trong benchmark comparison, architecture decision, README, performance report hoặc model selection thì procedure đo phải trở thành tracked benchmark source.

## 6. Yêu cầu reproducibility

Mỗi benchmark mới phải ghi rõ:

- mục tiêu/câu hỏi kỹ thuật;
- target hardware và OS;
- Git commit;
- model/backend/runtime version;
- input và manifest/fixture;
- exact command/config;
- environment variables;
- warmup policy;
- sample count/repetition;
- metric và công thức;
- output location;
- cách chạy;
- cách tạo summary;
- acceptance threshold nếu threshold được chốt trước.

Python/shell runner phải được track. Nếu chỉ cần vài command, tạo README/runbook hoặc script tracked trong benchmark directory.

Mỗi result phải trace được producer, source revision, runtime/model identity, input, timestamp/timezone và hardware.

## 7. Source và output

~~~text
benchmarks/stt/noise_robustness/benchmark_noise_robustness.py
→ logs/benchmarks/stt/noise_robustness/<run-id>/
~~~

Generated output không được ghi cạnh source. Runner không được tự commit result.

## 8. Naming convention

Tên phải mô tả purpose:

~~~text
benchmark_stt_backend.py
benchmark_noise_robustness.py
benchmark_speech_gating.py
benchmark_llm_latency.py
~~~

Không dùng:

~~~text
test.py
bench.py
run2.py
new_test.py
benchmark_final.py
~~~

Directory/file dùng lowercase snake_case. Result có thể dùng run ID hoặc timestamp YYYY-MM-DD_HH-MM-SS.

## 9. Historical benchmark và reproducible benchmark

### Historical accepted benchmark

Các benchmark trước policy mới có thể được chạy bằng command/procedure không còn tracked. Khi kết luận quan trọng đã được tổng hợp trong report, report được giữ như historical accepted evidence.

> Benchmark lịch sử; raw implementation cũ không còn được sử dụng. Các benchmark mới phải tuân theo benchmark workflow hiện tại.

Historical report không tự trở thành reproducible benchmark mới. Không dùng raw procedure không còn trace được để tạo baseline mới.

### Reproducible benchmark

Từ thời điểm policy này được áp dụng, mọi benchmark mới phải có tracked producer/procedure trong benchmarks/ trước lần chạy chính thức đầu tiên. Result mới phải trace được về exact tracked revision.

## 10. Historical reports được giữ

- docs/stt-models/BENCHMARK.md: accepted model comparison và speech-gating findings.
- docs/PERFORMANCE.md: accepted latency/bottleneck summary.
- deps/runtime-sources.md: accepted runtime/model provenance và benchmark-derived roles.

Các kết luận lịch sử được giữ gồm:

- Zipformer 2023-06-21 là selected primary streaming backend;
- VAD-gated streaming được chọn;
- rolling pre-roll 480 ms;
- idle ASR CPU khoảng 120.4% xuống 22.3%;
- speech frontend latency khoảng 0.520 s lên 0.570 s;
- live exact observation 2/3 trước và sau gating.

Các con số này là historical accepted evidence, không phải output của benchmark infrastructure mới.

## 11. Raw result reset

Các tracked one-off result cũ đã bị xóa vì conclusion cần giữ đã được migrate vào report:

- full-pipeline latency JSONL ngày 2026-08-18;
- LLM latency text result ngày 2026-08-18;
- hai Python/LLM latency JSONL ngày 2026-08-18;
- VAD/STT latency text log ngày 2026-08-18.

Git history vẫn giữ historical files. Từ nay raw result mới chỉ nằm dưới ignored logs/benchmarks/.

Các directory runtime lịch sử như reference_results/, live_baseline_before_gating/ hoặc live_after_gating/ có thể tồn tại trên Jetson cũ, nhưng không phải benchmark source và không được dùng làm producer mới.

## 12. Runtime input được giữ

VoiceBank-DEMAND là input cho benchmark STT noise robustness tiếp theo, không phải old result:

~~~text
data/stt/voicebank_demand/
└── prepared_15/
│   ├── clean/       # 15 WAV
│   ├── noisy/       # 15 WAV
│   └── manifest.tsv # 15 mapping/reference rows
~~~

Không xóa prepared_15/. Dataset/audio/parquet tiếp tục ignored. Raw download/cache preparation cũ đã được dọn; procedure chuẩn trong tương lai phải được track để tái tạo input khi cần.

## 13. Benchmark tiếp theo

~~~text
STT noise robustness

Whisper Tiny.en
vs
Zipformer 2023-06-21

clean / noisy
GTCRN OFF / ON
~~~

Runner/procedure chưa được implement trong task cleanup này. Source mới phải được phát triển dưới benchmarks/stt/noise_robustness/ trên HOST, sau đó commit/push trước khi chạy trên Jetson.

## 14. Cấu trúc mục tiêu

~~~text
benchmarks/
├── README.md
├── stt/
│   ├── backend_comparison/
│   ├── noise_robustness/
│   └── speech_gating/
├── audio/
├── llm/
└── full_pipeline/
~~~

Chỉ tạo directory khi có source/procedure thật. Hiện chỉ benchmarks/README.md được tạo để thiết lập policy.

## 15. Git policy

Track:

- benchmark runner/procedure/README;
- fixture/manifest nhỏ khi license và provenance cho phép;
- methodology và accepted report;
- dependency/runtime identity.

Không track:

- model weight;
- WAV/parquet dataset;
- download archive;
- generated JSONL/TXT/TSV result;
- CPU/memory sample;
- runtime build;
- cache hoặc virtual environment.

benchmarks/ phải được track. logs/benchmarks/, models/, runtime/, .venv/, __pycache__/ và bytecode phải được ignore.
