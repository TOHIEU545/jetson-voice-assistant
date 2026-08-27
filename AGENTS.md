# AGENTS.md

## Phạm vi project

Repository này chứa source, test, script vận hành, metadata dependency và patch stack của `jetson-voice-assistant` trên Jetson Nano 4GB. Agent được phép chỉnh tracked source trên HOST, nhưng phải giữ nguyên behavior chức năng nếu task chỉ là tài liệu, cleanup hoặc tổ chức repository.

## Source of Truth

GitHub và branch phát triển `dev` là source of truth. Khi tài liệu mâu thuẫn, ưu tiên theo thứ tự: source hiện tại, patch hiện tại, benchmark evidence mới, metadata trong `deps/`, rồi mới đến tài liệu cũ.

## Vai trò HOST và Jetson

- HOST: edit tracked source, chạy syntax/unit/regression test, kiểm tra diff, commit và push.
- Jetson: `git pull origin dev`, runtime test, hardware test, model/latency/audio benchmark và hardware-dependent debugging.
- Không chỉnh tracked source trực tiếp trên Jetson. Thay đổi debug tạm thời trên Jetson không được trở thành source chính thức.

## Quy tắc inventory repository

Use `git ls-files` as the default repository inventory.

Luôn bắt đầu bằng:

```bash
git branch --show-current
git status --short
git ls-files | sort
```

Đọc `.gitignore` trước khi phân loại source và runtime data. Không dùng `find . -type f`, `tree -a` hoặc lệnh tương đương để dump toàn repository.

## Bản đồ repository

- `app/`: source Python của orchestration layer; tạo worker/queue, quản lý turn và gọi speech/LLM runtime.
- `app/core/`: contract và state không phụ thuộc backend: message, conversation, revision và cancellation.
- `app/backends/`: abstraction cho local/remote LLM backend.
- `app/handlers/`: bridge speech runtime, transcript gate, LLM lifecycle và output/log processing.
- `deps/`: version, provenance, manifest và checksum để tái tạo dependency đã được project chấp nhận; không chứa binary/model thật.
- `patches/`: project-specific delta áp lên upstream đã pin trong `deps/`.
- `scripts/`: operational tooling chạy trên HOST hoặc Jetson; mỗi script phải có mục tiêu và side effect rõ.
- `tests/`: chỉ chứa software unit/regression/parser/state/backend contract tests không cần benchmark hardware thật.
- `benchmarks/`: tracked source và procedure cho hardware/model/performance benchmark chạy trên Jetson.
- `data/`: benchmark/runtime input local, ignored; không chứa source hoặc generated result.
- `docs/`: kiến trúc, reference, setup, benchmark report và roadmap.
- `models/`: model weights local/runtime, ignored và không phải source of truth.
- `runtime/`: third-party source/build/binary local, ignored và không phải source of truth.
- `logs/`: output runtime/benchmark sinh khi chạy; không phải source hoặc benchmark input.

## Kiến trúc tổng quan

Hai runtime C++ được chọn theo `VOICE_ASSISTANT_STT`: Whisper offline hoặc Zipformer streaming. Audio đi qua GTCRN optional, Silero VAD, rồi STT. C++ phát transcript, latency, `[READY]` và `[SPEECH_STARTED]`; Python dùng `SpeechRuntimeHandler` để đưa turn qua transcript gate, revision/cancellation, bounded conversation và `LLMHandler`. Local/remote LLM cùng dùng OpenAI-compatible streaming API.

## Trạng thái phát triển hiện tại

- Whisper Tiny.en: implemented, runtime default, accuracy baseline/fallback.
- Zipformer 2023-06-21: implemented và được benchmark chọn làm primary streaming backend, nhưng chưa là launcher default.
- Zipformer 20M: implemented, experimental lightweight/speed baseline.
- GTCRN, Smart Turn và Speculative Turn: optional; Smart Turn/Speculative chỉ dùng với Whisper runtime.
- Barge-in: mặc định bật và cancel generation khi nhận `[SPEECH_STARTED]`.
- Trọng tâm hiện tại: STT noise robustness với VoiceBank-DEMAND, sau đó mới đến MS-SNSD.

## Quy tắc chỉnh source

- Không thay đổi behavior ngoài scope được yêu cầu.
- Giữ API, event format, queue-drain order và feature-flag default nếu task không cho phép đổi behavior.
- Dùng `git mv` cho tracked file và cập nhật toàn bộ reference.
- Không ghi đè hoặc hoàn tác thay đổi có sẵn trong working tree nếu chưa xác nhận chúng thuộc task.
- Software test phải nằm trong `tests/`; benchmark/hardware measurement source phải nằm trong `benchmarks/`.
- Không tạo `./test.py`, `./benchmark.py`, `~/test.py` hoặc `/tmp/test.py`.

## Software tests

- Test mới phải bảo vệ một contract cụ thể và có thể chạy lại trên HOST nếu không phụ thuộc hardware.
- Không xóa test chỉ vì tên phase cũ. Chỉ xóa khi chứng minh duplicate, target đã mất hoặc test mới bao phủ đầy đủ hơn.
- Chạy `python3 -m pytest tests` khi môi trường hỗ trợ.
- Nhiều regression file hiện là executable script có `main()`; khi sửa contract liên quan, chạy trực tiếp các script đó ngoài pytest.
- Test dùng fake/mocked dependency để bảo vệ parser, queue, state/lifecycle, feature flag hoặc backend request contract tiếp tục thuộc `tests/`.

## Board/hardware benchmarks

- Thay một biến chính mỗi lần; giữ cùng hardware, model, input và config còn lại.
- Benchmark implementation/procedure nằm trong `benchmarks/`; methodology và accepted interpretation nằm trong `docs/`.
- Runtime-generated result phải nằm dưới `logs/benchmarks/<topic>/`; benchmark input local nằm dưới `data/`.
- Không đặt runnable benchmark implementation trong `logs/`.
- Mỗi result cần trace được producer, command/config, input fixture, model/runtime version và thời điểm chạy.
- Hardware-dependent integration measurement thuộc `benchmarks/`, không thuộc `tests/`.

## HOST-first benchmark development

Mọi benchmark hoặc hardware measurement dùng để đưa ra kết luận kỹ thuật phải có tracked source/procedure trên HOST trước khi chạy trên Jetson.

Không được tạo benchmark/test source trực tiếp trên Jetson. Không SSH vào Jetson để viết runner tạm, paste command loop đo chính thức rồi chỉ giữ con số. Workflow bắt buộc:

```text
HOST benchmarks/<topic>/...
→ review/test
→ commit/push dev
→ Jetson git pull
→ chạy exact tracked procedure
```

## Jetson execution-only policy

Jetson chỉ execute benchmark/hardware test đã pull từ GitHub và sinh output dưới `logs/benchmarks/`. Nếu procedure cần sửa, thực hiện thay đổi trên HOST rồi lặp lại workflow Git; không duy trì tracked delta trên Jetson.

## Benchmark source và result

```text
benchmarks/       tracked source/procedure
data/             ignored benchmark/runtime input
logs/benchmarks/  ignored generated output/result
docs/             methodology/accepted report
```

Không ghi generated result vào `benchmarks/`. Benchmark source phải nêu mục tiêu, hardware, model/backend, input, config/env, warmup, sample count, metric, output path, cách chạy và cách tính summary.

## Debug command và accepted measurement

Command tương tác như `ls`, `cat`, `grep`, `top`, `ps`, `free`, `--help` và `aplay` được phép chạy trực tiếp trên Jetson để inspect/debug. Nếu measurement/con số sẽ được dùng cho comparison, architecture decision, README, performance report hoặc model selection thì sampling/measurement procedure phải được track trong `benchmarks/` trước khi chạy.

## Quy tắc runtime data

- Không commit model weights, audio dataset, parquet dataset, download archive, runtime build, conversation log, generated benchmark result, cache hoặc virtual environment.
- Dataset đã chuẩn bị để benchmark nằm dưới `data/<topic>/`; manifest/fixture nhỏ có thể đặt cùng tracked benchmark source khi license/provenance cho phép.
- Không xóa ignored model, runtime build hay prepared dataset nếu chưa chứng minh không còn được dùng.

## Quy tắc dependency

- Candidate mới bắt đầu ở trạng thái EXPERIMENT trong ignored `models/` hoặc `runtime/`.
- Chỉ khi benchmark và quyết định adopt mới chuyển thành OFFICIAL bằng cách cập nhật file phù hợp trong `deps/`, checksum, provisioning script và tài liệu provenance.
- Không đổi commit, version, checksum hoặc model chính thức trong task cleanup/documentation.

## Quy tắc sherpa-onnx patch

- `deps/sherpa-onnx.commit` là upstream base; `patches/sherpa-onnx/*.patch` là ordered project delta trên base đó.
- Đọc actual diff, không suy đoán responsibility từ filename.
- Giữ đúng thứ tự apply được document trong `docs/SOFTWARE_REFERENCE.md` và `deps/runtime-sources.md`.
- Dùng `git apply --check` trên clean tree ở đúng pinned commit trước khi apply; build cả target bị ảnh hưởng và chạy Python parser/config regression liên quan.

## Quy tắc Git

Workflow chuẩn:

```text
HOST edit
→ syntax/unit/regression test
→ git diff --check
→ git status --short
→ commit
→ push origin dev
→ Jetson pull/test/benchmark
```

Agent không commit hoặc push nếu user chưa yêu cầu rõ. Không dùng destructive Git command để xóa thay đổi của user.

## Quy tắc tài liệu

- Tài liệu tạo mới hoặc cập nhật phải viết bằng tiếng Việt.
- Symbol, class, function, environment variable, command, filename và thuật ngữ kỹ thuật có thể giữ tiếng Anh.
- Tài liệu phải phân biệt rõ IMPLEMENTED, SELECTED BY BENCHMARK, RUNTIME DEFAULT, OPTIONAL, EXPERIMENTAL và PLANNED.
- Không copy assumption cũ; đối chiếu source, patch, benchmark và metadata.

## Các thư mục agent không được scan

Không recursive scan hoặc đọc package/dữ liệu trong:

```text
.venv/
venv/
.git/
runtime/
models/
logs/
data/
build/
**/build/
**/__pycache__/
.vscode/
.idea/
downloaded datasets/
model weights/
```

Chỉ inventory một nhánh runtime data cụ thể bằng độ sâu giới hạn khi task yêu cầu audit nhánh đó. Không đọc nội dung `*.onnx`, `*.gguf`, `*.wav`, `*.mp3`, `*.flac`, `*.parquet`, archive hoặc bytecode.

## Trước khi bắt đầu task

1. Xác nhận branch và working tree.
2. Inventory bằng `git ls-files | sort`.
3. Đọc `.gitignore` và tài liệu context liên quan.
4. Ghi nhận thay đổi có sẵn để không ghi đè.
5. Xác định task chạy trên HOST hay cần validation Jetson.

## Trước khi kết thúc task

1. Chạy syntax/unit/regression test phù hợp.
2. Nếu đổi path, dùng `rg` xác minh không còn reference stale.
3. Chạy `git diff --check`.
4. Chạy `git status --short` và báo nguyên văn.
5. Báo phần chưa xác minh trên Jetson hoặc do thiếu runtime/model/dataset.
6. Không commit, push hoặc thay đổi dependency/runtime behavior ngoài authorization.
