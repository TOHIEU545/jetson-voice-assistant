# Architecture

Tài liệu này mô tả **bản chất kiến trúc hiện tại** của Jetson Voice Assistant. Mục tiêu là đọc một lần có thể hiểu hệ thống đang làm gì, dữ liệu đi đâu và vì sao các khối tồn tại.

---

## 1. Bài toán hệ thống

Project biến giọng nói thành text response từ LLM:

```text
User speech
   ↓
Audio frontend
   ↓
Speech-to-Text
   ↓
Turn / conversation control
   ↓
LLM
   ↓
Streaming text response
```

Ba mục tiêu chính:

```text
Nghe đúng      → enhancement + VAD + STT
Hiểu đúng turn → transcript gate + turn state
Phản hồi nhanh → queues + workers + cancellation
```

Điểm quan trọng: **audio capture, STT và LLM không chạy như một chuỗi blocking duy nhất**. Chúng được tách bằng worker/queue để microphone vẫn hoạt động khi Whisper hoặc LLM đang xử lý.

---

## 2. Kiến trúc tổng thể

```text
                              JETSON NANO

 Microphone / ALSA
        │
        ▼
 ┌──────────────────┐
 │ GTCRN            │ optional
 │ noise reduction  │
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ Silero VAD       │
 └──────┬───────┬───┘
        │       │
        │       └── speech started ──────────────────────┐
        │                                                │
        ▼                                                │
   speech segment                                        │
        │                                                │
        ▼                                                │
 ┌──────────────────┐                                    │
 │ Smart Turn       │ optional                           │
 └────────┬─────────┘                                    │
          ▼                                              │
 ┌──────────────────┐                                    │
 │ Whisper Tiny.en  │                                    │
 └────────┬─────────┘                                    │
          │ transcript                                   │
          ▼                                              │
 SpeechRuntimeHandler                                    │
          │                                              │
          ▼                                              │
   transcript_queue                                      │
          │                                              │
          ▼                                              │
 TranscriptGateHandler                                   │
          │                                              │
          ▼                                              │
   valid_turn_queue                                      │
          │                                              │
          ▼                                              │
 ┌──────────────────┐   barge-in cancel ◄───────────────┘
 │ LLMHandler       │
 └────────┬─────────┘
          │
          ├── ConversationManager
          │
          └── LLMBackend
                 │
                 ▼
           llama.cpp server
                 │
                 ▼
          streamed response
```

Có hai vùng rõ ràng:

```text
C++ speech runtime
→ audio, VAD, Smart Turn, Whisper

Python orchestration
→ transcript, turn, history, cancellation, LLM
```

---

## 3. Vì sao cần queue và worker?

Kiến trúc đơn giản nhưng sai cho realtime:

```text
capture
 ↓
Whisper
 ↓
LLM
 ↓
quay lại capture
```

Trong lúc Whisper hoặc LLM chạy, microphone có thể không được phục vụ đúng cách.

Kiến trúc hiện tại:

```text
Audio/VAD producer
       │
       ▼
  speech_queue
       │
       ▼
Whisper worker
       │
       ▼
transcript_queue
       │
       ▼
Python workers
```

Bản chất:

> Queue tách tốc độ xử lý của các stage và ngăn một model chậm block toàn pipeline.

---

## 4. GTCRN

GTCRN nằm trước VAD:

```text
Raw microphone
      ↓
    GTCRN
      ↓
cleaner waveform
      ↓
     VAD
```

Mục tiêu là giảm ảnh hưởng của noise trước khi VAD/STT xử lý.

GTCRN là optional vì nó thêm compute và hiệu quả phụ thuộc loại noise.

---

## 5. Silero VAD

VAD trả lời:

> **Có speech hay không, và speech segment kết thúc khi nào?**

Nó chỉ nhìn tín hiệu audio, không hiểu ngữ nghĩa.

Ví dụ:

```text
"Can you explain..."
                  ↑
              user pause
```

VAD có thể coi pause này là endpoint.

VAD hiện có hai output quan trọng:

```text
speech start
   ↓
[SPEECH_STARTED]
   ↓
barge-in cancellation

speech end
   ↓
speech segment
   ↓
Smart Turn / Whisper
```

---

## 6. Smart Turn

Smart Turn giải bài toán khác VAD:

```text
VAD:
"User đã ngừng phát âm chưa?"

Smart Turn:
"Câu của user đã thực sự hoàn chỉnh chưa?"
```

Flow:

```text
             VAD endpoint
                  │
                  ▼
              Smart Turn
             /          \
      COMPLETE          INCOMPLETE
         │                  │
         ▼                  ▼
      Whisper            hold audio
                            │
                       user nói tiếp
                            │
                            ▼
                       merge audio
                            │
                            └── evaluate lại
```

Ví dụ:

```text
"Can you explain..."
        ↓
Smart Turn = INCOMPLETE
        ↓
hold

"...how UART works?"
        ↓
merge
        ↓
COMPLETE
        ↓
Whisper → LLM
```

### Trạng thái hiện tại

Smart Turn đã chạy được trên Jetson nhưng vẫn optional vì:

- feature extraction tương đối nặng;
- môi trường noise có thể gây false `INCOMPLETE`;
- latency tăng đáng kể so với baseline.

---

## 7. Whisper STT

Whisper biến speech waveform thành transcript:

```text
audio
 ↓
Whisper Tiny.en
 ↓
"What is an MCU?"
```

Whisper chạy theo kiểu resident worker:

```text
startup
 ↓
load model một lần
 ↓
segment 1
segment 2
segment 3
...
```

Không reload model mỗi turn.

---

## 8. Transcript Gate

Noise/STT có thể tạo transcript không đáng gửi vào LLM:

```text
""
"."
"[Music]"
"(noise)"
```

Gate nằm giữa STT và LLM:

```text
Whisper
   │
   ▼
Transcript Gate
   /       \
PASS       DROP
 │
 ▼
LLM queue
```

Ý nghĩa:

> Lỗi speech frontend nên được chặn trước khi làm bẩn conversation history hoặc prompt của LLM.

---

## 9. Turn và revision

Mỗi logical user turn có:

```text
turn_id
revision
```

Ví dụ cùng một câu được cập nhật:

```text
turn 15 rev0
      ↓
user nói tiếp
      ↓
turn 15 rev1
```

RevisionTracker giữ revision mới nhất:

```text
rev0 ───────────┐
                │ rev1 arrives
                ▼
             rev0 stale
```

Stale generation không được phép commit vào history.

---

## 10. ConversationManager

ConversationManager giữ:

```text
bounded history
user turns
assistant responses
turn/revision state
abort/cancel state
```

History là bounded để RAM/prompt không tăng vô hạn.

---

## 11. Speculative turn

Speculative cho phép xử lý một turn trước khi nó chắc chắn final:

```text
rev0 provisional
       │
       ├── có thể bắt đầu Whisper/LLM sớm
       │
       └── nếu user nói tiếp
                ↓
              rev1
                ↓
             cancel rev0
```

Infrastructure revision/cancellation đã hoạt động.

Nhưng trên Jetson Nano hiện tại, revision mới có thể đến quá muộn và provisional work có thể:

```text
tạo response lặp
hoặc
tăng compute/latency
```

Do đó:

```text
VOICE_ASSISTANT_SPECULATIVE=0
```

là lựa chọn hiện tại.

Revision infrastructure vẫn được giữ vì có ích cho quản lý turn và cancellation.

---

## 12. Barge-in

Barge-in là bài toán khác speculative.

Ví dụ:

```text
Assistant:
"Linux is an operating system that..."

User:
"What is an MCU?"
```

Flow:

```text
LLM đang generate
       │
User bắt đầu nói
       │
       ▼
Silero VAD
IsSpeechDetected()
       │
       ▼
[SPEECH_STARTED]
       │
       ▼
SpeechRuntimeHandler
       │
       ▼
GenerationCancellationController
       │
       ▼
cancel current generation
       │
       ├── response dở không commit history
       └── active generation scope được giải phóng
       │
       ▼
Whisper xử lý câu mới
       │
       ▼
LLM xử lý turn mới
```

Tại sao cancel ngay ở speech start?

```text
Nếu đợi:
speech end → Whisper → transcript → cancel

thì assistant có thể nói thêm vài giây.
```

Barge-in đã test PASS trên Jetson thật.

---

## 13. Python orchestration

```text
SpeechRuntimeHandler
        │
        ▼
transcript_queue
        │
        ▼
TranscriptGateHandler
        │
        ▼
valid_turn_queue
        │
        ▼
LLMHandler
        │
        ├── RevisionTracker
        ├── CancellationController
        └── ConversationManager
        │
        ▼
LLMBackend
        │
        ▼
response
```

Python chịu trách nhiệm về **state và orchestration**, không phải DSP/audio inference.

---

## 14. LLM backend

LLMHandler dùng abstraction:

```text
             LLMHandler
                 │
             LLMBackend
              /      \
             /        \
       local llama   remote compatible
```

Local backend hiện gọi:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Nhờ vậy speech pipeline không cần sửa khi đổi LLM.

---

## 15. Concurrency model

```text
WORKER A
ALSA → GTCRN → VAD
                 │
                 ▼
            speech_queue

WORKER B
speech_queue → Smart Turn optional → Whisper
                                      │
                                      ▼
                               transcript_queue

PYTHON
SpeechRuntimeHandler
      ↓
TranscriptGateHandler
      ↓
LLMHandler
      ↓
response
```

Đường interruption:

```text
VAD speech start
      ↓
[SPEECH_STARTED]
      ↓
cancel active LLM
```

Đây là điểm phân biệt hệ thống này với một script kiểu:

```text
record.wav → whisper → llm
```

---

## 16. Flow bình thường hiện tại

Cấu hình ổn định:

```text
GTCRN       ON
SMART_TURN  OFF
SPECULATIVE OFF
```

Flow:

```text
User speaks
   ↓
GTCRN
   ↓
VAD
   ↓
Whisper
   ↓
Transcript Gate
   ↓
ConversationManager
   ↓
LLM
   ↓
stream response
```

Trong lúc LLM generate:

```text
user speech start
   ↓
barge-in
   ↓
cancel LLM cũ
```

---

## 17. Bottleneck hiện tại

Nếu bật Smart Turn:

```text
feature extraction  ~1.3 s
model inference     ~0.32 s
total               ~1.65–1.8 s
```

Do đó bottleneck chính không phải model inference mà là feature preparation.

Hướng tối ưu hợp lý:

```text
Mic stream
   ├── VAD
   └── incremental feature extraction
             ↓
         feature cache

VAD endpoint
   ↓
feature đã có
   ↓
Smart Turn inference
```

Mục tiêu: đưa feature extraction ra khỏi critical path thay vì thêm nhiều heuristic `if/else`.

---

## 18. Tóm tắt bản chất

Nếu chỉ nhớ 5 ý:

```text
1. GTCRN làm sạch audio trước VAD.
2. VAD xác định acoustic speech boundary.
3. Whisper chuyển speech thành text.
4. Queue/worker tách capture, STT và LLM để hệ thống realtime.
5. Speech-start có thể hủy LLM ngay để hỗ trợ barge-in.
```

Một câu mô tả project:

> **Jetson Voice Assistant là local realtime speech-to-LLM pipeline trên Jetson Nano, tách audio/STT/LLM bằng queue và worker, có bounded conversation state, revision protection và real barge-in cancellation.**
