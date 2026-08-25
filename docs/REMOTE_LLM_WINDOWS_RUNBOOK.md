# Remote LLM Windows Runbook

> Hướng dẫn chạy tạm thời LLM trên máy Windows RTX 5090 để Jetson gọi từ xa qua Cloudflare Tunnel.
>
> Runtime hiện tại: **Ollama**
> Model hiện tại: **ministral-3:8b**
> GPU: **RTX 5090**
>
> Đây vẫn là cấu hình **thử nghiệm**, chưa phải deployment chính thức.

---

## 1. Trước khi chạy trên Windows

Mở **PowerShell**.

### Kiểm tra GPU

```powershell
nvidia-smi
```

Quan sát:

- GPU Util
- Memory-Usage
- process nào đang dùng GPU

Nếu GPU đang bị dùng nặng thì không nên chạy thêm model.

### Kiểm tra runtime/process AI đang chạy

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "ollama|llama|lmstudio|python|vllm|sglang" } |
    Select-Object ProcessId,Name,CommandLine
```

Không tự ý kill process lạ.

### Kiểm tra các model Ollama đã có

```powershell
ollama list
```

Model chat đang dùng:

```text
ministral-3:8b
```

### Kiểm tra model nào đang được Ollama load để suy luận

```powershell
ollama ps
```

Nếu đang có model khác được load thì cần chú ý vì có thể đang dùng GPU chung.

### Kiểm tra Ollama server

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "ollama" } |
    Select-Object ProcessId,Name,CommandLine
```

Kiểm tra port:

```powershell
Get-NetTCPConnection -LocalPort 11434 |
    Select-Object LocalAddress,LocalPort,State,OwningProcess
```

---

## 2. Chạy Cloudflare Tunnel trên Windows

`cloudflared.exe` hiện nằm tại:

```text
C:\Users\PC\llm-tunnel-test\cloudflared.exe
```

Chạy:

```powershell
$DIR="$env:USERPROFILE\llm-tunnel-test"

& "$DIR\cloudflared.exe" tunnel `
  --url http://127.0.0.1:11434 `
  --no-autoupdate
```

Cloudflare sẽ tạo URL dạng:

```text
https://xxxxx.trycloudflare.com
```

Copy đúng URL nằm trong dòng:

```text
Your quick Tunnel has been created!
```

Giữ nguyên cửa sổ PowerShell đang chạy `cloudflared`.

Luồng:

```text
Jetson
  ↓ HTTPS
Cloudflare public endpoint
  ↓
Cloudflare Tunnel
  ↓
cloudflared trên Windows
  ↓
127.0.0.1:11434
  ↓
Ollama
  ↓
ministral-3:8b
  ↓
RTX 5090
```

---

## 3. Chạy Voice Assistant trên Jetson

Trên Jetson:

```bash
cd ~/jetson-voice-assistant
```

Cấu hình speech pipeline:

```bash
export VOICE_ASSISTANT_GTCRN=1
export VOICE_ASSISTANT_SMART_TURN=0
export VOICE_ASSISTANT_SPECULATIVE=0
```

Cấu hình remote LLM:

```bash
export LLM_MODE=remote
export LLM_BASE_URL="https://xxxxx.trycloudflare.com/v1/chat/completions"
export LLM_MODEL="ministral-3:8b"
unset LLM_API_KEY
```

Thay:

```text
https://xxxxx.trycloudflare.com
```

bằng URL Quick Tunnel mới vừa tạo.

Kiểm tra URL trước khi chạy:

```bash
echo "$LLM_BASE_URL"
```

Phải có dạng:

```text
https://xxxxx.trycloudflare.com/v1/chat/completions
```

Sau đó chạy:

```bash
python3 app/voice_assistant.py
```

---

## 4. Khi dùng xong

### Trên Jetson

Dừng Voice Assistant:

```text
Ctrl+C
```

Nếu trước đó có sửa tạm source trên Jetson:

```bash
cd ~/jetson-voice-assistant
git restore app/config.py
git status --short
```

`git status --short` nên trống.

---

### Trên Windows

Dừng Cloudflare Tunnel:

```text
Ctrl+C
```

Kiểm tra `cloudflared` đã tắt:

```powershell
Get-Process cloudflared -ErrorAction SilentlyContinue
```

Nếu không có output thì tunnel đã tắt.

### Unload model Ministral khỏi Ollama

Chỉ chạy lệnh này khi chắc chắn **không có người khác đang dùng cùng model**:

```powershell
ollama stop ministral-3:8b
```

Lệnh này chỉ unload model khỏi Ollama/VRAM, không stop toàn bộ Ollama server.

Kiểm tra:

```powershell
ollama ps
```

Nếu `ministral-3:8b` không còn xuất hiện thì model đã được unload.

### Kiểm tra GPU sau khi dừng

```powershell
nvidia-smi
```

VRAM nên giảm nếu không còn workload khác.

---

## 5. Checklist ngắn cho lần chạy sau

### Windows

```powershell
nvidia-smi
```

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "ollama|llama|lmstudio|python|vllm|sglang" } |
    Select-Object ProcessId,Name,CommandLine
```

```powershell
ollama list
ollama ps
```

Chạy tunnel:

```powershell
$DIR="$env:USERPROFILE\llm-tunnel-test"

& "$DIR\cloudflared.exe" tunnel `
  --url http://127.0.0.1:11434 `
  --no-autoupdate
```

Copy URL mới.

### Jetson

```bash
cd ~/jetson-voice-assistant

export VOICE_ASSISTANT_GTCRN=1
export VOICE_ASSISTANT_SMART_TURN=0
export VOICE_ASSISTANT_SPECULATIVE=0

export LLM_MODE=remote
export LLM_BASE_URL="https://xxxxx.trycloudflare.com/v1/chat/completions"
export LLM_MODEL="ministral-3:8b"
unset LLM_API_KEY

python3 app/voice_assistant.py
```

### Khi kết thúc

Jetson:

```text
Ctrl+C
```

Windows:

```text
Ctrl+C
```

Sau đó:

```powershell
ollama stop ministral-3:8b
Get-Process cloudflared -ErrorAction SilentlyContinue
ollama ps
nvidia-smi
```

> Chỉ chạy `ollama stop ministral-3:8b` khi chắc chắn model đó không đang được người khác sử dụng.
