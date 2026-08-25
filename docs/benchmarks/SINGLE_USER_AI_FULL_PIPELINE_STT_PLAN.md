# SINGLE-USER AI — FULL PIPELINE STT BENCHMARK & DEVELOPMENT PLAN

## 1. Mục tiêu

Giai đoạn hiện tại tập trung đúng yêu cầu:

> **Một người dùng nói chuyện với một AI và đánh giá toàn bộ luồng end-to-end.**

Mục tiêu không chỉ là benchmark STT riêng lẻ. STT standalone chỉ dùng làm **pre-check** để xác nhận model có thể load và chạy trên Jetson.

Benchmark chính phải chạy full pipeline:

```text
Mic
 ↓
ALSA
 ↓
GTCRN optional
 ↓
Silero VAD
 ↓
STT backend
 ↓
SpeechRuntimeHandler
 ↓
Transcript Gate
 ↓
LLM
 ↓
streamed response
```

Phase này vừa là:

```text
validation theo yêu cầu sản phẩm
+
development / optimization có dữ liệu
```

---

# 2. Trạng thái baseline hiện tại

Baseline:

```text
GTCRN          OFF
SMART TURN     OFF
SPECULATIVE    OFF
BARGE-IN       ON
STT            Whisper Tiny.en
LLM            backend hiện tại
```

Các thành phần hiện tại:

```text
VAD / endpointing
→ tương đối ổn định

Noise robustness cơ bản
→ tương đối ổn ngay cả khi GTCRN OFF

Transcript Gate
→ đã loại được nhiều hallucination / annotation không hợp lệ

Barge-in
→ đã hoạt động

STT latency
→ bottleneck nổi bật nhất, đặc biệt với utterance dài
```

Benchmark thực tế đã từng thấy:

```text
VAD endpoint                 ≈ 0.5 s
Whisper STT long utterance   ≈ 6.4 s
Speech → First LLM Token     ≈ 8 s
```

Do đó trong phase này:

> **Freeze VAD/noise baseline và tập trung thay đổi STT backend.**

---

# 3. Nguyên tắc benchmark

Để so sánh công bằng, giữ cố định:

```text
same microphone
same speaker
same room
same speaking distance
same VAD settings
same Transcript Gate
same LLM backend
same LLM model
same test sentences
same feature flags
same Jetson power/performance configuration
```

Chỉ thay:

```text
STT backend
```

Baseline flags:

```bash
export VOICE_ASSISTANT_GTCRN=0
export VOICE_ASSISTANT_SMART_TURN=0
export VOICE_ASSISTANT_SPECULATIVE=0
export VOICE_ASSISTANT_BARGE_IN=1
```

---

# 4. Benchmark chính là FULL PIPELINE

Standalone STT không phải kết quả cuối cùng.

Quy trình cho mỗi candidate:

```text
1. Download model
2. Standalone smoke test
3. Nếu load/decode PASS
4. Tích hợp hoặc chạy qua full pipeline
5. Test 1 user → 1 AI
6. Đo end-to-end latency + accuracy + resource
7. PASS / FAIL
```

Benchmark chính:

```text
User speaks
 ↓
VAD detects end
 ↓
STT final transcript
 ↓
Gate
 ↓
LLM generation
 ↓
first useful response token
```

---

# 5. STT candidates

## Candidate 0 — Baseline

```text
Whisper Tiny.en
Type: Offline ASR
Runtime: sherpa-onnx OfflineRecognizer
```

Vai trò:

```text
baseline accuracy
baseline latency
fallback
comparison reference
```

Không thay đổi source baseline trong experiment.

---

## Candidate 1 — Streaming Zipformer 20M

```text
sherpa-onnx-streaming-zipformer-en-20M-2023-02-17
```

Mục tiêu:

```text
xác định latency floor
đo CPU/RAM/RTF
đánh giá accuracy của streaming model nhỏ
```

Candidate thiên về:

```text
speed
low resource usage
```

---

## Candidate 2 — Streaming Zipformer 2023-06-21

```text
sherpa-onnx-streaming-zipformer-en-2023-06-21
```

Mục tiêu:

```text
accuracy tốt hơn candidate nhỏ
+
vẫn phải realtime trên Jetson Nano
```

Trong vòng đầu trên Jetson:

```text
FP32 encoder
FP32 decoder
FP32 joiner
CPU
```

Không ưu tiên INT8 trước khi compatibility với ONNX Runtime production được xác nhận.

---

# 6. Kiến trúc cần đạt với Streaming ASR

Không dùng:

```text
Mic
 ↓
VAD
 ↓
completed segment
 ↓
Streaming model
```

vì như vậy vẫn đợi speech-end mới bắt đầu ASR.

Kiến trúc mục tiêu:

```text
                         ┌→ Silero VAD
                         │
Mic → ALSA → PCM chunks ─┤
                         │
                         └→ Streaming ASR
```

Hai nhánh cùng nhận audio trong lúc người dùng đang nói.

Vai trò:

```text
VAD
→ xác định speech start / speech end

Streaming ASR
→ xử lý audio liên tục
```

Khi speech-end xảy ra:

```text
Streaming ASR
→ finalize phần cuối
→ final transcript
→ Gate
→ LLM
```

---

# 7. Test set chính

Mỗi backend phải chạy cùng bộ câu.

## T1 — Short utterance

Duration:

```text
~2–3 s
```

Đo:

```text
transcript accuracy
Speech End → Final Transcript
Speech End → First LLM Token
```

---

## T2 — Medium utterance

Duration:

```text
~5–7 s
```

Mục tiêu:

```text
so sánh offline vs streaming khi câu dài hơn
```

---

## T3 — Long utterance

Duration:

```text
~10–15 s
```

Đây là testcase quan trọng nhất.

Whisper offline:

```text
User speaks
████████████████████████

speech end
                        ↓
Whisper decode          ███████████
```

Streaming candidate mong muốn:

```text
User speaks
████████████████████████

Streaming STT
████████████████████████
                       ↓
                 final transcript
                       ↓
                      LLM
```

---

# 8. Full conversation test

Sau khi T1–T3 PASS:

```text
10–20 turns liên tục
```

Ví dụ:

```text
User → AI
User → AI
User → AI
...
```

Kiểm tra:

```text
turn reset
stream reset
queue backlog
memory growth
context correctness
stale transcript
stale LLM response
latency drift
barge-in behavior
```

Một câu chạy tốt chưa đủ.

Candidate chỉ đáng tích hợp nếu full conversation chạy ổn.

---

# 9. Noise regression test

Noise không phải trọng tâm chính của phase này nhưng vẫn phải giữ regression test để đảm bảo model mới không làm hệ thống kém đi.

Test:

```text
Quiet
Keyboard typing
Fan / AC
General room noise
```

Ban đầu:

```text
GTCRN OFF
```

Nếu candidate chỉ fail trong noise:

```text
Candidate + GTCRN OFF
vs
Candidate + GTCRN ON
```

Lúc đó mới đánh giá enhancement.

Không tune GTCRN trước khi có failure thực tế.

---

# 10. Endpointing regression test

VAD hiện tại được freeze nhưng vẫn cần kiểm tra model mới không phá conversation timing.

Test:

```text
normal sentence
short natural pause
medium natural pause
true end-of-turn
```

Mục tiêu:

```text
natural pause
→ không split sai quá thường xuyên

true end
→ final transcript xuất hiện nhanh
```

---

# 11. Metric timestamp chuẩn

## Offline Whisper

```text
T0 = actual speech end
T1 = VAD completed segment
T2 = final transcript
T3 = first non-empty LLM token
T4 = last useful LLM token
```

Đo:

```text
VAD endpoint             = T1 - T0
STT after VAD            = T2 - T1
Speech End → Transcript  = T2 - T0
Speech End → LLM First   = T3 - T0
LLM generation           = T4 - T3
```

---

## Streaming ASR

```text
S0 = speech start
P0 = first meaningful partial transcript
S1 = actual speech end
F0 = final transcript
L0 = first non-empty LLM token
L1 = last useful LLM token
```

Đo:

```text
Speech Start → First Partial    = P0 - S0
Speech End   → Final Transcript = F0 - S1
Speech End   → First LLM Token  = L0 - S1
LLM generation                  = L1 - L0
```

Metric chính:

```text
Speech End → First LLM Token
```

Metric STT chính:

```text
Speech End → Final Transcript
```

Sau này khi có TTS:

```text
Speech End → First Audible Audio
```

---

# 12. Accuracy đánh giá ở full pipeline

Không chỉ hỏi:

```text
STT transcript có đúng chữ không?
```

Mà còn hỏi:

```text
LLM có hiểu đúng ý người dùng không?
AI có trả lời đúng câu hỏi không?
```

Ví dụ:

```text
STT nhanh hơn 4 s
nhưng transcript làm LLM hiểu sai
→ FAIL
```

Ngược lại:

```text
STT nhanh rõ rệt
transcript đủ chính xác
LLM trả lời đúng
→ PASS
```

---

# 13. Resource metrics

Mỗi candidate ghi:

```text
model size
model load time
steady-state RAM
peak RAM
average CPU
peak CPU
RTF
```

RTF:

```text
RTF = processing_time / audio_duration
```

Yêu cầu tối thiểu:

```text
RTF < 1
```

Nhưng cần headroom cho:

```text
VAD
Python orchestration
LLM
GTCRN optional
TTS future
```

---

# 14. Thư mục benchmark

Đề xuất:

```text
jetson-voice-assistant/
├── docs/
│   └── benchmarks/
│       └── SINGLE_USER_AI_FULL_PIPELINE_STT_PLAN.md
│
├── scripts/
│   └── benchmarks/
│       └── stt/
│
└── logs/
    └── benchmarks/
        └── single_user_ai/
            ├── whisper_tiny_en/
            ├── zipformer_20m/
            └── zipformer_2023_06_21/
```

Git track:

```text
docs/
scripts/benchmarks/
test definitions
model metadata sau khi candidate OFFICIAL
```

Không commit:

```text
model weights
*.onnx
*.tar.bz2
recordings
runtime logs
temporary benchmark artifacts
```

---

# 15. Format một test run

Mỗi run nên lưu tối thiểu:

```text
timestamp
backend
model
feature flags
test case
expected text
actual transcript
LLM response
VAD latency
STT latency / streaming finalization latency
Speech End → Final Transcript
Speech End → First LLM Token
LLM generation time
RAM
CPU
PASS / FAIL
notes
```

Ví dụ:

```text
backend: whisper
case: long_quiet_01

expected:
Today I want to understand ...

actual:
Today I want to understand ...

Speech End → Final Transcript: 6.41 s
Speech End → First LLM Token: 8.02 s

result: PASS accuracy / FAIL latency target
```

---

# 16. PASS / FAIL của STT candidate

## PASS

Candidate PASS khi:

```text
model load ổn
full pipeline chạy được
accuracy đủ tốt
LLM hiểu đúng
Speech End → Final Transcript giảm rõ
Speech End → First LLM Token giảm rõ
RTF < 1
RAM phù hợp
CPU còn headroom
không backlog
multi-turn ổn định
```

---

## FAIL

Candidate FAIL khi:

```text
accuracy kém rõ
LLM hiểu sai thường xuyên
RTF >= 1 thường xuyên
RAM/CPU quá cao
stream backlog
multi-turn lỗi
latency không cải thiện đủ đáng kể
```

---

# 17. Thứ tự thực hiện

## STEP 1 — Re-run Whisper full-pipeline baseline

```text
short
medium
long
```

Đây là mốc chuẩn.

---

## STEP 2 — Zipformer 20M pre-check

```text
download
model load
standalone decode
microphone stream
```

Nếu FAIL:

```text
stop candidate
```

Nếu PASS:

```text
→ full pipeline
```

---

## STEP 3 — Zipformer 20M full-pipeline test

Chạy cùng:

```text
short
medium
long
noise regression
multi-turn
```

Ghi đầy đủ end-to-end metrics.

---

## STEP 4 — Zipformer 2023-06-21 pre-check

Tương tự Candidate 1.

---

## STEP 5 — Zipformer 2023-06-21 full-pipeline test

Tương tự Candidate 1.

---

## STEP 6 — So sánh

```text
Whisper Tiny.en
vs
Zipformer 20M
vs
Zipformer 2023-06-21
```

Theo:

```text
accuracy
LLM response correctness
Speech End → Final Transcript
Speech End → First LLM Token
CPU
RAM
RTF
multi-turn stability
```

---

# 18. Integration strategy

Không sửa đè baseline Whisper.

Giữ:

```text
sherpa-onnx-vad-alsa-offline-asr.cc
```

Nếu streaming candidate PASS, tạo:

```text
sherpa-onnx-vad-alsa-streaming-asr.cc
```

Mục tiêu:

```text
                         ┌→ VAD
                         │
Mic → ALSA → PCM chunks ─┤
                         │
                         └→ OnlineRecognizer
```

Sau đó thêm backend switch:

```text
VOICE_ASSISTANT_STT=whisper
VOICE_ASSISTANT_STT=zipformer
```

---

# 19. Những thứ freeze trong phase này

Không ưu tiên thay đổi:

```text
VAD threshold
min silence
Smart Turn
Speculative flow
Speaker Verification
Target Speaker Extraction
TTS
```

Mỗi lần chỉ thay một biến lớn:

```text
STT backend
```

---

# 20. Kết luận của phase

Phase này không phải:

```text
"test cho đủ"
```

mà là:

```text
test full pipeline
        ↓
xác định bottleneck
        ↓
thay STT candidate
        ↓
benchmark lại full pipeline
        ↓
giữ hoặc loại bằng dữ liệu
```

Yêu cầu của sản phẩm và hướng tối ưu hiện tại là cùng một bài toán.

---

# 21. Điểm bắt đầu ngay

```text
1. Whisper full-pipeline baseline
2. Zipformer 20M pre-check
3. Zipformer 20M full pipeline
4. Zipformer 2023-06-21 pre-check
5. Zipformer 2023-06-21 full pipeline
6. Compare
7. Chọn backend
```

**Benchmark chính luôn là full pipeline tới LLM.**
Standalone chỉ là pre-check để tránh tích hợp một model chưa chạy ổn.
