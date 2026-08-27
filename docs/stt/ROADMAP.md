# STT / Speech Pipeline Roadmap

> **Vai trò tài liệu:** roadmap học/nghiên cứu và tối ưu speech frontend, không phải source of truth cho runtime default.
>
> **Trạng thái runtime hiện tại:** project hỗ trợ Whisper Tiny.en offline và Zipformer streaming; benchmark lịch sử chọn Zipformer 2023-06-21 làm primary streaming backend, trong khi launcher vẫn default Whisper. GTCRN, Smart Turn và Speculative đều là optional.
>
> Kết quả benchmark đã chấp nhận nằm tại `docs/stt/BENCHMARK.md`. Benchmark source mới phải nằm dưới `benchmarks/`.

> Mục tiêu: hiểu **đầy đủ bản chất kỹ thuật** của pipeline Speech AI đang dùng trong project `jetson-voice-assistant`, để biết mỗi module làm gì, vì sao cần nó, tham số nào ảnh hưởng chất lượng/latency, và nên tối ưu deployment ở đâu.
>
> Đây **không phải roadmap để tự xây model từ đầu**. Trọng tâm là:
>
> **Hiểu nguyên lý → hiểu model/runtime hiện tại → benchmark → tune → deploy trên Jetson.**

---

# 0. Bức tranh tổng thể cần hiểu

Pipeline hiện tại:

```text
Microphone
    ↓
Audio Capture
    ↓
GTCRN
Speech Enhancement
    ↓
Silero VAD
Speech / Non-speech Detection
    ↓
Speech Segmentation
    ↓
Whisper Tiny.en
Speech-to-Text
    ↓
Transcript Gate
    ↓
Conversation / Turn Control
    ↓
LLM Backend
    ↓
Remote / Local LLM
```

Trong giai đoạn nghiên cứu này, trọng tâm là **speech frontend**:

```text
Mic
 ↓
Audio
 ↓
GTCRN
 ↓
VAD
 ↓
Whisper
```

Scope ban đầu:

```text
1 người nói
+
môi trường yên tĩnh
hoặc
noise không phải speech:
- quạt
- điều hòa
- máy tính
- tiếng nền đều
```

Chưa nghiên cứu sâu:

```text
Wake Word
Speaker Verification
Speaker Diarization
Multi-speaker
Echo Cancellation
TTS
```

---

# PHASE 1 — Digital Audio Fundamentals

## Mục tiêu

Hiểu dữ liệu thực sự đi từ microphone vào model là gì.

Không cần tự viết audio driver hay DSP library từ đầu.

## 1.1 PCM Audio

Cần hiểu:

```text
analog sound
    ↓ ADC
digital samples
```

Các khái niệm:

- PCM
- sample
- waveform
- amplitude
- signed integer / float audio
- normalization

Phải trả lời được:

> Một file WAV 16 kHz mono thực chất chứa dữ liệu gì?

## 1.2 Sample Rate

Tìm hiểu:

```text
8 kHz
16 kHz
44.1 kHz
48 kHz
```

Cần hiểu:

- sample rate là gì
- Nyquist frequency
- vì sao speech AI thường dùng 16 kHz
- chuyện gì xảy ra khi mic là 48 kHz nhưng model cần 16 kHz
- resampling là gì

Phải trả lời được:

> Vì sao Whisper/Silero thường nhận 16 kHz?

## 1.3 Bit Depth

Hiểu:

```text
16-bit PCM
24-bit PCM
32-bit float
```

Cần hiểu:

- dynamic range
- quantization
- clipping

Phải nhận biết được:

```text
audio quá nhỏ
audio bình thường
audio clipping
```

## 1.4 Mono / Stereo / Channels

Hiểu:

```text
mono = 1 channel
stereo = 2 channels
```

Cần biết:

- model speech thường cần mono
- downmix stereo → mono
- channel selection

## 1.5 dB và SNR

Khái niệm rất quan trọng.

Hiểu:

```text
SNR = Speech power / Noise power
```

Ý nghĩa:

```text
SNR cao
→ speech rõ hơn noise

SNR thấp
→ noise gần hoặc lớn hơn speech
```

Không cần tính toán quá sâu, nhưng phải hiểu bản chất để benchmark noise.

## 1.6 Frame và Chunk

Audio streaming không xử lý cả file một lần.

Ví dụ:

```text
16 kHz

10 ms
→ 160 samples

20 ms
→ 320 samples

30 ms
→ 480 samples
```

Hiểu:

- frame
- chunk
- buffer
- streaming audio

Phải trả lời được:

> Vì sao GTCRN/VAD phải xử lý audio theo chunk thay vì đợi cả câu?

## Exit Criteria Phase 1

Bạn phải giải thích được:

```text
Mic
→ PCM samples
→ sample rate
→ frame/chunk
→ model input
```

Và hiểu rõ:

- clipping
- amplitude
- sample rate
- mono
- SNR
- frame size

---

# PHASE 2 — Time-Frequency Analysis

Đây là nền tảng để hiểu speech enhancement.

## 2.1 Time Domain

Waveform:

```text
Amplitude
   |
   |       /\      /\
   |      /  \    /  \
---+----------------------→ time
```

Hiểu:

- waveform cho biết biên độ theo thời gian
- khó nhìn trực tiếp thành phần tần số

## 2.2 Frequency Domain

Tìm hiểu FFT.

Không cần tự code FFT.

Cần hiểu:

```text
time-domain signal
      ↓ FFT
frequency components
```

Ví dụ:

```text
fan noise
→ nhiều năng lượng ở vùng tần số thấp / ổn định

speech
→ cấu trúc phổ thay đổi liên tục
```

## 2.3 STFT

Đây là khái niệm rất quan trọng cho GTCRN.

Pipeline:

```text
waveform
 ↓
split frames
 ↓
window
 ↓
FFT từng frame
 ↓
time-frequency representation
```

Hiểu:

- STFT
- frame length
- hop length
- overlap
- window function

## 2.4 Windowing

Tìm hiểu:

```text
Hann window
Hamming window
```

Không cần học toán quá sâu.

Cần hiểu:

> Vì sao không FFT trực tiếp từng đoạn audio cắt cứng?

## 2.5 Spectrogram

Hiểu:

```text
X-axis → time
Y-axis → frequency
color/value → energy
```

Phải có khả năng nhìn spectrogram và phân biệt sơ bộ:

```text
silence
speech
fan noise
speech + fan
```

## 2.6 ISTFT

Hiểu chiều ngược:

```text
processed spectrum
 ↓
ISTFT
 ↓
waveform
```

Điều này cực quan trọng để hiểu GTCRN:

```text
waveform
 ↓
STFT
 ↓
neural enhancement
 ↓
ISTFT
 ↓
enhanced waveform
```

## Exit Criteria Phase 2

Bạn phải giải thích được:

```text
FFT
STFT
window
hop
spectrogram
ISTFT
```

và trả lời:

> Tại sao speech enhancement thường xử lý trong miền time-frequency?

---

# PHASE 3 — Classical Noise Reduction

Mục tiêu không phải dùng các thuật toán này thay GTCRN.

Mục tiêu là hiểu **GTCRN đang cải tiến bài toán gì**.

## 3.1 Noise Model

Mô hình đơn giản:

```text
y(t) = s(t) + n(t)

y = noisy microphone signal
s = clean speech
n = noise
```

Đây là bản chất bài toán enhancement.

## 3.2 Spectral Subtraction

Ý tưởng:

```text
Noisy spectrum
-
Estimated noise spectrum
=
Estimated clean speech
```

Cần hiểu:

- noise estimation
- subtraction trong miền phổ
- artifacts
- musical noise

Không cần triển khai production.

## 3.3 Wiener Filter

Tìm hiểu bản chất:

```text
ước lượng mức speech/noise
→ attenuate phần có khả năng là noise
→ giữ phần có khả năng là speech
```

Cần hiểu:

- SNR estimation
- frequency-dependent filtering
- giới hạn của classical filtering

## 3.4 Vì sao classical method khó?

Các trường hợp:

```text
stationary noise
→ tương đối dễ

non-stationary noise
→ khó hơn

speech-like noise
→ rất khó
```

Phải hiểu vì sao neural enhancement ra đời.

## Exit Criteria Phase 3

Bạn phải giải thích được:

> Spectral Subtraction và Wiener Filter làm gì?

Và:

> Vì sao neural speech enhancement như GTCRN có thể tốt hơn các rule/filter cố định?

---

# PHASE 4 — Neural Speech Enhancement và GTCRN

Đây là phase quan trọng nhất cho model enhancement hiện tại.

## 4.1 Neural Speech Enhancement là gì?

Thay vì viết rule thủ công:

```text
if frequency X looks like noise
→ reduce
```

ta cho neural network học:

```text
noisy audio
→ clean audio
```

hoặc:

```text
noisy spectrum
→ clean spectrum / mask
```

## 4.2 Các kiểu target phổ biến

### Spectral Masking

```text
Noisy spectrum
×
Estimated mask
=
Enhanced spectrum
```

### Spectral Mapping

```text
Noisy spectrum
→ neural network
→ estimated clean spectrum
```

Không cần nhớ toàn bộ công thức.

## 4.3 CRN

Tìm hiểu khái niệm:

```text
Convolution
+
Recurrent Network
```

Convolution:

```text
học local time-frequency patterns
```

Recurrent:

```text
học temporal context
```

## 4.4 GTCRN

GTCRN:

```text
Grouped Temporal
Convolutional Recurrent Network
```

Cần nghiên cứu:

- encoder
- decoder
- temporal modeling
- grouped convolution
- recurrent state
- lightweight architecture
- vì sao phù hợp embedded/edge

Không cần tự train.

## 4.5 Mổ chính model đang dùng

Model hiện tại:

```text
gtcrn_simple.onnx
```

Phải xác định chính xác:

```text
input tensor shape
output tensor shape
sample rate
frame size
FFT size
hop size
state/cache inputs
state/cache outputs
```

Đây là phần cực quan trọng.

## 4.6 Streaming State

Tìm hiểu:

```text
chunk N
 ↓
GTCRN
 ↓
state N
 ↓
chunk N+1
```

Khác với:

```text
mỗi chunk độc lập hoàn toàn
```

Phải hiểu:

- cache
- recurrent state
- context
- state reset

## 4.7 Latency của Enhancement

Phân biệt:

```text
algorithmic latency
processing latency
end-to-end latency
```

Cần biết:

- frame size lớn → có thể tốt hơn nhưng latency tăng
- overlap/hop ảnh hưởng latency
- inference time phải nhỏ hơn thời lượng chunk để realtime

## 4.8 Benchmark GTCRN

Test:

```text
CASE 1:
quiet + speech

CASE 2:
fan low + speech

CASE 3:
fan medium + speech

CASE 4:
fan high + speech

CASE 5:
fan only

CASE 6:
silence
```

So sánh:

```text
RAW
vs
GTCRN
```

Metrics:

```text
STT correctness
speech distortion
false VAD trigger
CPU
RAM
latency
RTF
```

## Exit Criteria Phase 4

Bạn phải trả lời được:

> GTCRN nhận gì?

> Nó xử lý ở miền nào?

> STFT/ISTFT nằm ở đâu?

> State/cache dùng để làm gì?

> Nó cải thiện noise như thế nào?

> Nó thêm bao nhiêu latency trên Jetson?

> Có thực sự giúp Whisper tốt hơn không?

---

# PHASE 5 — Voice Activity Detection Fundamentals

Sau enhancement mới đến speech detection.

## 5.1 VAD là gì?

VAD không làm STT.

Nó chỉ trả lời:

```text
Có speech không?
```

Ví dụ:

```text
silence → NON-SPEECH
fan → NON-SPEECH
human voice → SPEECH
```

## 5.2 Classical VAD

Tìm hiểu ở mức concept:

```text
energy threshold
zero crossing rate
spectral features
```

Ví dụ:

```text
energy > threshold
→ speech?
```

Nhược điểm:

```text
fan / music / impact noise
→ có thể false trigger
```

## 5.3 Neural VAD

Silero VAD:

```text
audio chunk
 ↓
neural model
 ↓
speech probability
```

Ví dụ:

```text
P(speech) = 0.91
```

Nhưng model probability chưa phải quyết định cuối cùng.

## 5.4 Threshold

Ví dụ:

```text
P(speech) >= 0.5
→ candidate speech
```

Nghiên cứu:

```text
threshold thấp
→ detect nhạy hơn
→ false positive nhiều hơn

threshold cao
→ false positive giảm
→ có thể miss speech
```

## 5.5 Speech Start State Machine

Không nên:

```text
1 frame vượt threshold
→ speech immediately
```

Thường phải cần một chuỗi frame.

Khái niệm:

```text
NON-SPEECH
 ↓ enough speech frames
SPEECH
```

## 5.6 Speech End / Endpoint

Cực kỳ quan trọng cho latency.

```text
speech
 ↓
user stops talking
 ↓
wait silence N ms
 ↓
speech end
```

Cần hiểu:

- min silence duration
- endpoint delay
- speech padding

## 5.7 False Positive / False Negative

### False Positive

```text
fan
→ VAD says speech
```

### False Negative

```text
user speaks
→ VAD says non-speech
```

Phải benchmark cả hai.

## Exit Criteria Phase 5

Bạn phải giải thích được:

```text
Silero model probability
+
threshold
+
state machine
+
endpoint logic
=
final speech segment
```

Và hiểu:

> VAD không chỉ là một neural model.

---

# PHASE 6 — Silero VAD trong project hiện tại

## 6.1 Xác định model

Tìm:

```text
silero_vad.onnx
```

Xác định:

```text
input shape
sample rate
state
runtime
ONNX Runtime version
```

## 6.2 Xác định tham số runtime

Phải tìm trong sherpa-onnx:

```text
threshold
min silence
min speech
window size
speech padding
```

## 6.3 VAD + GTCRN interaction

Benchmark:

```text
RAW → VAD

GTCRN → VAD
```

Test:

```text
silence
fan only
speech only
speech + fan
```

Câu hỏi:

> GTCRN có giảm false trigger của VAD không?

## 6.4 Endpoint Optimization

Đo:

```text
T0 = user stops speaking
T1 = VAD finalizes segment
```

Metric:

```text
T0→T1
```

Tune:

```text
500 ms
400 ms
300 ms
```

Nhưng phải kiểm tra không cắt câu.

## Exit Criteria Phase 6

Phải biết chính xác:

```text
VAD threshold hiện tại
endpoint hiện tại
state machine hiện tại
```

và biết tham số nào có thể tune.

---

# PHASE 7 — Speech Recognition Fundamentals

## 7.1 ASR là gì?

```text
speech waveform
 ↓
features
 ↓
acoustic/language modeling
 ↓
tokens
 ↓
text
```

## 7.2 Feature Extraction

Pipeline:

```text
waveform
 ↓
STFT
 ↓
Mel filterbank
 ↓
log
 ↓
log-Mel spectrogram
```

## 7.3 Mel Scale

Hiểu:

- human hearing không tuyến tính theo frequency
- Mel filterbank nén frequency representation

Không cần học công thức sâu.

## 7.4 Log-Mel Spectrogram

Đây là input quan trọng của Whisper.

Phải trả lời:

> GTCRN output cuối cùng được biến thành input Whisper như thế nào?

---

# PHASE 8 — Whisper Architecture

## 8.1 Encoder

```text
log-Mel
 ↓
encoder
 ↓
audio representation
```

Hiểu:

- Transformer encoder
- audio context

## 8.2 Decoder

```text
audio representation
+
previous tokens
 ↓
decoder
 ↓
next token
```

Whisper decoder là autoregressive.

## 8.3 Tokens

Hiểu:

```text
text
→ tokens
```

và:

```text
decoder
→ token sequence
→ transcript
```

## 8.4 Greedy / Beam Search

### Greedy

```text
chọn token probability cao nhất
```

### Beam

```text
giữ nhiều candidate sequences
```

Tradeoff:

```text
quality
vs
latency / compute
```

## 8.5 Hallucination

Các trường hợp:

```text
(mumbling)
(speaking in foreign language)
[inaudible]

hoặc
model sinh text dù audio không rõ
```

Tìm hiểu:

- low-information audio
- silence/noise hallucination
- decoder behavior

## Exit Criteria Phase 8

Bạn phải giải thích được:

```text
waveform
→ log-Mel
→ Whisper encoder
→ decoder
→ tokens
→ text
```

---

# PHASE 9 — Whisper trong project hiện tại

## 9.1 Mổ model Tiny.en

Xác định:

```text
encoder ONNX
decoder ONNX
tokens.txt
```

Hiểu:

```text
encoder file
≠
decoder file
```

## 9.2 STT Latency

Metric:

```text
T1 = VAD segment complete
T2 = transcript ready

STT latency = T1→T2
```

Benchmark theo audio length:

```text
1 s speech
2 s speech
3 s speech
5 s speech
```

## 9.3 Threading

Tìm hiểu:

```text
num threads
CPU utilization
latency
```

Không mặc định rằng nhiều thread luôn nhanh hơn trên Nano.

## 9.4 GTCRN ON/OFF vs Whisper

```text
speech + fan
 ↓
RAW Whisper

vs

speech + fan
 ↓
GTCRN
 ↓
Whisper
```

Đánh giá:

```text
transcript correctness
latency
CPU/RAM
```

## Exit Criteria Phase 9

Phải trả lời được:

> Whisper đang là bottleneck bao nhiêu?

> GTCRN có giúp Whisper đủ nhiều để đáng giữ không?

---

# PHASE 10 — Transcript Gate

## 10.1 Mục tiêu

```text
Whisper
 ↓
Transcript Gate
 ↓
LLM
```

Dùng để loại:

```text
(mumbling)
[inaudible]
(speaking in foreign language)
```

## 10.2 Rule-based Filtering

Hiểu:

- blacklist patterns
- annotation detection
- empty transcript
- minimum useful content

## 10.3 Vì sao không để LLM xử lý hết?

```text
STT garbage
 ↓
LLM
 ↓
garbage conversation context
```

Có thể gây:

```text
history pollution
wrong responses
unnecessary remote requests
```

## Exit Criteria Phase 10

Phải hiểu:

> Speech pipeline không kết thúc ở Whisper.

> Post-processing vẫn là một phần của hệ thống.

---

# PHASE 11 — Streaming Pipeline Architecture

## 11.1 Streaming vs Offline

### Offline

```text
record whole file
 ↓
process
```

### Streaming

```text
chunk
 ↓
process
 ↓
next chunk
 ↓
process
```

## 11.2 Buffer

Hiểu:

```text
audio samples
→ buffer
→ chunk
```

Cần biết:

- buffer size
- overflow
- underflow

## 11.3 Queue

Project có:

```text
speech_queue
transcript_queue
valid_turn_queue
```

Hiểu:

```text
Producer
 ↓
Queue
 ↓
Consumer
```

## 11.4 Worker

Ví dụ:

```text
VAD producer
 ↓
speech_queue
 ↓
Whisper worker
```

Mục tiêu:

```text
VAD tiếp tục nghe
trong lúc
Whisper decode segment trước
```

## 11.5 Backpressure

Nếu:

```text
producer > consumer
```

thì:

```text
queue depth tăng
latency tăng
```

## 11.6 State

Các model streaming như GTCRN/VAD có state.

Hiểu:

```text
state belongs to stream
```

Không được reset sai thời điểm.

## Exit Criteria Phase 11

Bạn phải nhìn được pipeline và xác định:

```text
producer
consumer
queue
worker
state
critical path
```

---

# PHASE 12 — Latency Engineering

## 12.1 Timeline

```text
T0 = actual speech end
T1 = VAD endpoint
T2 = transcript ready
T3 = LLM generation starts
T4 = first LLM token
T5 = last LLM token
```

## 12.2 Metrics

```text
T0→T1
VAD endpoint delay

T1→T2
STT path

T0→T2
speech frontend

T2→T3
Python orchestration

T3→T4
LLM TTFT

T4→T5
generation

T0→T4
perceived response latency
```

## 12.3 Critical Path

Ví dụ:

```text
GTCRN      40 ms
VAD       500 ms
STT      1800 ms
Python      1 ms
LLM       400 ms
```

Ưu tiên:

```text
STT
→ VAD
→ LLM
→ GTCRN
```

## Exit Criteria Phase 12

Phải trả lời được:

> Module nào đang làm user phải chờ lâu nhất?

---

# PHASE 13 — Resource Engineering trên Jetson Nano

## 13.1 CPU

Đo:

```text
CPU usage
per-process CPU
threads
```

## 13.2 RAM

Đo:

```text
RSS
system available memory
swap
```

## 13.3 Model Residency

Hiểu:

```text
model weights
runtime memory
buffers
state/cache
```

## 13.4 Realtime Factor

```text
RTF = processing time / audio duration
```

Ví dụ:

```text
1 second audio
processed in 0.1 second

RTF = 0.1
```

## Exit Criteria Phase 13

Phải biết:

```text
GTCRN CPU/RAM
Silero CPU/RAM
Whisper CPU/RAM
combined pipeline RAM
```

---

# PHASE 14 — Benchmark Methodology

## 14.1 Test Dataset cố định

```text
quiet/
  q01.wav
  q02.wav
  q03.wav

fan_low/
  f01.wav
  f02.wav
  f03.wav

fan_medium/
  ...

fan_high/
  ...

fan_only/
  ...

silence/
  ...
```

Cùng speaker, cùng microphone, cùng khoảng cách.

## 14.2 Ground Truth

Mỗi speech file phải có transcript đúng.

Ví dụ:

```text
f01.wav
"What is Linux?"
```

## 14.3 Compare Configurations

```text
A:
GTCRN OFF
VAD current
Whisper

B:
GTCRN ON
VAD current
Whisper

C:
GTCRN ON
VAD tuned
Whisper
```

## 14.4 Metrics

### Accuracy

- exact sentence correctness
- WER nếu cần

### VAD

- false positive
- false negative
- endpoint latency

### Runtime

- CPU
- RAM
- latency
- RTF

## Exit Criteria Phase 14

Có bảng kiểu:

| Config | Quiet | Fan | False VAD | STT latency | CPU | RAM |
|---|---:|---:|---:|---:|---:|---:|
| RAW | ... | ... | ... | ... | ... | ... |
| GTCRN | ... | ... | ... | ... | ... | ... |

---

# PHASE 15 — Optimization Workflow

## Step 1 — Measure

```text
không sửa gì
→ đo baseline
```

## Step 2 — Identify Bottleneck

Ví dụ:

```text
STT dominates
```

thì tập trung Whisper.

## Step 3 — Change One Variable

Ví dụ:

```text
VAD silence duration
500 ms
→
350 ms
```

Không đổi cùng lúc nhiều module.

## Step 4 — Re-run Same Dataset

Cùng audio, cùng benchmark, cùng metrics.

## Step 5 — Compare

```text
quality
latency
CPU
RAM
```

## Step 6 — Keep or Revert

```text
PASS
→ giữ

FAIL
→ revert
```

---

# PHASE 16 — Laptop vs Jetson Workflow

## Laptop = Research Machine

Dùng laptop để:

```text
đọc source
đọc paper
inspect ONNX
plot waveform
plot spectrogram
offline inference
parameter experiments
benchmark scripts
unit tests
source modifications
```

## Jetson = Deployment Target

Dùng Jetson để:

```text
hardware microphone test
real ONNX runtime
CPU benchmark
RAM benchmark
latency benchmark
realtime behavior
long-run stability
```

## Workflow chuẩn

```text
LAPTOP
  ↓
Research
  ↓
Develop
  ↓
Offline benchmark
  ↓
Commit
  ↓
GitHub
  ↓
Jetson git pull
  ↓
Runtime benchmark
  ↓
PASS / FAIL
```

---

# PHASE 17 — Sau khi 1 Speaker + Noise ổn định

Chỉ sau khi:

```text
1 speaker
+
fan / environmental noise
```

ổn định, mới chuyển sang:

```text
background speech
multiple people
```

Lúc đó nghiên cứu:

```text
Wake Word
Speaker Verification
Direction of Arrival
Beamforming
Speaker Diarization
```

Đây là bài toán khác với noise suppression.

---

# Checklist kiến thức cuối cùng

## Audio

- PCM là gì?
- Sample rate là gì?
- Vì sao dùng 16 kHz?
- Clipping là gì?
- SNR là gì?
- Frame/chunk khác nhau thế nào?

## DSP

- FFT làm gì?
- STFT làm gì?
- Windowing để làm gì?
- Spectrogram biểu diễn gì?
- ISTFT để làm gì?

## Enhancement

- Noise suppression giải bài toán gì?
- Spectral subtraction hoạt động thế nào?
- Wiener filter làm gì?
- Neural enhancement khác classical enhancement thế nào?
- GTCRN là gì?
- GTCRN dùng state/cache để làm gì?
- GTCRN thêm bao nhiêu latency?

## VAD

- VAD khác STT thế nào?
- Silero output là gì?
- Threshold có ý nghĩa gì?
- Speech start được quyết định thế nào?
- Speech end được quyết định thế nào?
- Endpoint latency là gì?
- False positive/negative là gì?

## Whisper

- Whisper input là gì?
- Log-Mel là gì?
- Encoder làm gì?
- Decoder làm gì?
- Token decoding hoạt động thế nào?
- Hallucination xảy ra khi nào?
- STT latency phụ thuộc gì?

## Streaming

- Buffer là gì?
- Queue là gì?
- Worker là gì?
- Backpressure là gì?
- State/cache là gì?
- Vì sao VAD và Whisper nên decouple?

## Deployment

- CPU/RAM của từng model?
- RTF là gì?
- Critical path là gì?
- Model nào thật sự là bottleneck?
- Khi nào nên đổi model?
- Khi nào chỉ nên tune parameter?

---

# Thứ tự học thực tế đề xuất

```text
BLOCK 1
Audio Fundamentals
↓
FFT / STFT / Spectrogram
↓
Classical Noise Reduction

BLOCK 2
Neural Enhancement
↓
GTCRN architecture
↓
Mổ gtcrn_simple.onnx
↓
GTCRN benchmark

BLOCK 3
VAD fundamentals
↓
Silero VAD
↓
Mổ current VAD config
↓
VAD benchmark / endpoint tuning

BLOCK 4
Whisper fundamentals
↓
Tiny.en architecture
↓
ONNX encoder/decoder
↓
STT benchmark

BLOCK 5
Streaming architecture
↓
Queue / worker / state
↓
Latency engineering
↓
Resource benchmark

BLOCK 6
Full pipeline benchmark
↓
Bottleneck analysis
↓
Optimization
↓
Stable baseline
```

---

# Definition of Done

Roadmap hoàn thành khi bạn nhìn pipeline:

```text
Mic
 ↓
GTCRN
 ↓
Silero VAD
 ↓
Whisper
 ↓
Transcript Gate
 ↓
LLM
```

và với từng mũi tên đều trả lời được:

```text
dữ liệu đang ở format gì?
module tiếp theo nhận gì?
module đó xử lý theo nguyên lý gì?
output là gì?
state/cache ở đâu?
latency bao nhiêu?
CPU/RAM bao nhiêu?
parameter nào đáng tune?
nếu module này lỗi thì biểu hiện thế nào?
```

Khi đạt mức đó, bạn không chỉ còn là người “ghép model chạy được”, mà đã hiểu đủ pipeline để:

```text
debug
benchmark
tune
replace model
optimize deployment
giải thích kiến trúc
```

một cách có cơ sở kỹ thuật.
