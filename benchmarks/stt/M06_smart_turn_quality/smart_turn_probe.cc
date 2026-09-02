#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

#include "sherpa-onnx/csrc/math.h"
#include "sherpa-onnx/csrc/offline-stream.h"

struct SmartTurnResult {
  bool ok = false;
  bool complete = false;

  float probability = 0.0f;

  double audio_prep_ms = 0.0;
  double feature_ms = 0.0;
  double infer_ms = 0.0;
  double total_ms = 0.0;
};

class SmartTurnRuntime {
 public:
  SmartTurnRuntime(
      const std::string &model_path,
      float threshold,
      int32_t num_threads)
      : threshold_(threshold),
        env_(ORT_LOGGING_LEVEL_WARNING, "smart-turn-m06") {
    session_options_.SetIntraOpNumThreads(num_threads);
    session_options_.SetInterOpNumThreads(1);
    session_options_.SetGraphOptimizationLevel(
        GraphOptimizationLevel::ORT_ENABLE_ALL);

    session_ = std::make_unique<Ort::Session>(
        env_,
        model_path.c_str(),
        session_options_);
  }

  SmartTurnResult Evaluate(
      const std::vector<float> &turn_audio,
      int32_t sample_rate) {
    SmartTurnResult result;

    if (sample_rate != kSampleRate || turn_audio.empty()) {
      std::fprintf(
          stderr,
          "Invalid audio: sample_rate=%d samples=%zu\n",
          sample_rate,
          turn_audio.size());
      return result;
    }

    const auto total_start =
        std::chrono::steady_clock::now();

    // --------------------------------------------------------
    // Audio preparation
    //
    // Smart Turn v3.2:
    // - 16 kHz
    // - use last <= 8 seconds
    // - zero-pad at BEGINNING when shorter than 8 seconds
    // --------------------------------------------------------

    const auto prep_start =
        std::chrono::steady_clock::now();

    std::vector<float> audio(kMaxSamples, 0.0f);

    const size_t copy_count =
        std::min(
            turn_audio.size(),
            static_cast<size_t>(kMaxSamples));

    const size_t src_offset =
        turn_audio.size() - copy_count;

    const size_t dst_offset =
        audio.size() - copy_count;

    std::copy(
        turn_audio.begin() + src_offset,
        turn_audio.end(),
        audio.begin() + dst_offset);

    // Match production runtime:
    // WhisperFeatureExtractor(do_normalize=True)
    // over the complete padded 8-second waveform.

    double sum = 0.0;

    for (float x : audio) {
      sum += x;
    }

    const double mean =
        sum / static_cast<double>(audio.size());

    double variance_sum = 0.0;

    for (float x : audio) {
      const double d =
          static_cast<double>(x) - mean;

      variance_sum += d * d;
    }

    const double variance =
        variance_sum /
        static_cast<double>(audio.size());

    const double inv_std =
        1.0 / std::sqrt(variance + 1.0e-7);

    for (float &x : audio) {
      x = static_cast<float>(
          (static_cast<double>(x) - mean) *
          inv_std);
    }

    const auto prep_end =
        std::chrono::steady_clock::now();

    result.audio_prep_ms =
        std::chrono::duration<double, std::milli>(
            prep_end - prep_start)
            .count();

    // --------------------------------------------------------
    // Whisper feature extraction
    //
    // 8 sec @ 16 kHz
    // -> 800 frames
    // -> 80 mel bins
    // --------------------------------------------------------

    const auto feature_start =
        std::chrono::steady_clock::now();

    sherpa_onnx::WhisperTag whisper_tag;
    whisper_tag.dim = kFeatureDim;

    sherpa_onnx::OfflineStream feature_stream(
        whisper_tag);

    feature_stream.AcceptWaveform(
        kSampleRate,
        audio.data(),
        static_cast<int32_t>(audio.size()));

    std::vector<float> features =
        feature_stream.GetFrames();

    const int32_t num_frames =
        static_cast<int32_t>(
            features.size() / kFeatureDim);

    if (num_frames != kNumFrames) {
      std::fprintf(
          stderr,
          "Expected %d frames, got %d\n",
          kNumFrames,
          num_frames);

      return result;
    }

    sherpa_onnx::NormalizeWhisperFeatures(
        features.data(),
        num_frames,
        kFeatureDim);

    // sherpa-onnx:
    //   [800, 80]
    //
    // Smart Turn ONNX:
    //   [1, 80, 800]

    std::vector<float> model_input(
        kFeatureDim * kNumFrames);

    for (int32_t frame = 0;
         frame != kNumFrames;
         ++frame) {
      for (int32_t bin = 0;
           bin != kFeatureDim;
           ++bin) {
        model_input[
            bin * kNumFrames + frame] =
            features[
                frame * kFeatureDim + bin];
      }
    }

    const auto feature_end =
        std::chrono::steady_clock::now();

    result.feature_ms =
        std::chrono::duration<double, std::milli>(
            feature_end - feature_start)
            .count();

    // --------------------------------------------------------
    // ONNX inference
    // --------------------------------------------------------

    const auto infer_start =
        std::chrono::steady_clock::now();

    std::array<int64_t, 3> input_shape{
        1,
        kFeatureDim,
        kNumFrames,
    };

    auto memory_info =
        Ort::MemoryInfo::CreateCpu(
            OrtArenaAllocator,
            OrtMemTypeDefault);

    Ort::Value input_tensor =
        Ort::Value::CreateTensor<float>(
            memory_info,
            model_input.data(),
            model_input.size(),
            input_shape.data(),
            input_shape.size());

    const char *input_names[] = {
        "input_features",
    };

    const char *output_names[] = {
        "logits",
    };

    auto outputs =
        session_->Run(
            Ort::RunOptions{nullptr},
            input_names,
            &input_tensor,
            1,
            output_names,
            1);

    const auto infer_end =
        std::chrono::steady_clock::now();

    result.infer_ms =
        std::chrono::duration<double, std::milli>(
            infer_end - infer_start)
            .count();

    const float *output =
        outputs[0].GetTensorData<float>();

    result.probability = output[0];

    if (!std::isfinite(result.probability)) {
      std::fprintf(
          stderr,
          "Non-finite model output\n");

      return result;
    }

    // Model output already contains sigmoid probability.
    result.complete =
        result.probability > threshold_;

    result.ok = true;

    const auto total_end =
        std::chrono::steady_clock::now();

    result.total_ms =
        std::chrono::duration<double, std::milli>(
            total_end - total_start)
            .count();

    return result;
  }

 private:
  static constexpr int32_t kSampleRate = 16000;
  static constexpr int32_t kFeatureDim = 80;
  static constexpr int32_t kNumFrames = 800;
  static constexpr int32_t kMaxSamples =
      8 * kSampleRate;

  float threshold_;

  Ort::Env env_;
  Ort::SessionOptions session_options_;
  std::unique_ptr<Ort::Session> session_;
};

static uint16_t ReadU16(
    const unsigned char *p) {
  return static_cast<uint16_t>(
      static_cast<uint16_t>(p[0]) |
      (static_cast<uint16_t>(p[1]) << 8));
}

static uint32_t ReadU32(
    const unsigned char *p) {
  return
      static_cast<uint32_t>(p[0]) |
      (static_cast<uint32_t>(p[1]) << 8) |
      (static_cast<uint32_t>(p[2]) << 16) |
      (static_cast<uint32_t>(p[3]) << 24);
}

static std::vector<float> ReadPcm16MonoWav(
    const std::string &path,
    int32_t *sample_rate) {
  std::ifstream is(
      path.c_str(),
      std::ios::binary);

  if (!is) {
    throw std::runtime_error(
        "Cannot open WAV: " + path);
  }

  unsigned char header[12];

  if (!is.read(
          reinterpret_cast<char *>(header),
          sizeof(header))) {
    throw std::runtime_error(
        "Invalid WAV header: " + path);
  }

  if (std::string(
          reinterpret_cast<char *>(header),
          4) != "RIFF" ||
      std::string(
          reinterpret_cast<char *>(header + 8),
          4) != "WAVE") {
    throw std::runtime_error(
        "Not a RIFF/WAVE file: " + path);
  }

  uint16_t audio_format = 0;
  uint16_t channels = 0;
  uint16_t bits_per_sample = 0;
  uint32_t wav_sample_rate = 0;

  std::vector<unsigned char> data;

  while (is) {
    unsigned char chunk_header[8];

    if (!is.read(
            reinterpret_cast<char *>(chunk_header),
            sizeof(chunk_header))) {
      break;
    }

    const std::string chunk_id(
        reinterpret_cast<char *>(chunk_header),
        4);

    const uint32_t chunk_size =
        ReadU32(chunk_header + 4);

    if (chunk_id == "fmt ") {
      std::vector<unsigned char> fmt(
          chunk_size);

      if (!is.read(
              reinterpret_cast<char *>(fmt.data()),
              chunk_size)) {
        throw std::runtime_error(
            "Truncated fmt chunk");
      }

      if (fmt.size() < 16) {
        throw std::runtime_error(
            "Invalid fmt chunk");
      }

      audio_format =
          ReadU16(fmt.data());

      channels =
          ReadU16(fmt.data() + 2);

      wav_sample_rate =
          ReadU32(fmt.data() + 4);

      bits_per_sample =
          ReadU16(fmt.data() + 14);

    } else if (chunk_id == "data") {
      data.resize(chunk_size);

      if (!is.read(
              reinterpret_cast<char *>(data.data()),
              chunk_size)) {
        throw std::runtime_error(
            "Truncated data chunk");
      }

    } else {
      is.seekg(
          static_cast<std::streamoff>(chunk_size),
          std::ios::cur);
    }

    if (chunk_size & 1U) {
      is.seekg(1, std::ios::cur);
    }
  }

  if (audio_format != 1) {
    throw std::runtime_error(
        "Only PCM WAV is supported");
  }

  if (channels != 1) {
    throw std::runtime_error(
        "Only mono WAV is supported");
  }

  if (bits_per_sample != 16) {
    throw std::runtime_error(
        "Only PCM16 WAV is supported");
  }

  if (wav_sample_rate != 16000) {
    throw std::runtime_error(
        "Smart Turn benchmark requires 16 kHz WAV");
  }

  if (data.empty() ||
      data.size() % 2 != 0) {
    throw std::runtime_error(
        "Invalid WAV PCM data");
  }

  std::vector<float> samples(
      data.size() / 2);

  for (size_t i = 0;
       i != samples.size();
       ++i) {
    const uint16_t raw =
        static_cast<uint16_t>(
            static_cast<uint16_t>(data[2 * i]) |
            (static_cast<uint16_t>(
                 data[2 * i + 1])
             << 8));

    const int16_t value =
        static_cast<int16_t>(raw);

    samples[i] =
        static_cast<float>(value) /
        32768.0f;
  }

  *sample_rate =
      static_cast<int32_t>(wav_sample_rate);

  return samples;
}

static void Usage(
    const char *program) {
  std::cerr
      << "Usage:\n"
      << "  " << program
      << " --model MODEL.onnx"
      << " --wav INPUT.wav"
      << " [--threshold 0.5]"
      << " [--threads 4]\n";
}

int main(
    int argc,
    char **argv) {
  std::string model_path;
  std::string wav_path;

  float threshold = 0.5f;
  int32_t threads = 4;

  for (int i = 1;
       i < argc;
       ++i) {
    const std::string arg =
        argv[i];

    if (arg == "--model" &&
        i + 1 < argc) {
      model_path = argv[++i];

    } else if (
        arg == "--wav" &&
        i + 1 < argc) {
      wav_path = argv[++i];

    } else if (
        arg == "--threshold" &&
        i + 1 < argc) {
      threshold =
          static_cast<float>(
              std::atof(argv[++i]));

    } else if (
        arg == "--threads" &&
        i + 1 < argc) {
      threads =
          static_cast<int32_t>(
              std::atoi(argv[++i]));

    } else {
      Usage(argv[0]);
      return 2;
    }
  }

  if (model_path.empty() ||
      wav_path.empty()) {
    Usage(argv[0]);
    return 2;
  }

  if (threshold < 0.0f ||
      threshold > 1.0f) {
    std::cerr
        << "threshold must be in [0, 1]\n";

    return 2;
  }

  if (threads < 1) {
    std::cerr
        << "threads must be >= 1\n";

    return 2;
  }

  try {
    int32_t sample_rate = 0;

    const std::vector<float> audio =
        ReadPcm16MonoWav(
            wav_path,
            &sample_rate);

    const auto load_start =
        std::chrono::steady_clock::now();

    SmartTurnRuntime runtime(
        model_path,
        threshold,
        threads);

    const auto load_end =
        std::chrono::steady_clock::now();

    const double load_ms =
        std::chrono::duration<double, std::milli>(
            load_end - load_start)
            .count();

    const SmartTurnResult result =
        runtime.Evaluate(
            audio,
            sample_rate);

    if (!result.ok) {
      std::cerr
          << "Smart Turn evaluation failed\n";

      return 1;
    }

    std::cout
        << "SMART_TURN_RESULT"
        << " probability="
        << result.probability
        << " decision="
        << (
            result.complete
                ? "COMPLETE"
                : "INCOMPLETE")
        << " threshold="
        << threshold
        << " load_ms="
        << load_ms
        << " audio_prep_ms="
        << result.audio_prep_ms
        << " feature_ms="
        << result.feature_ms
        << " infer_ms="
        << result.infer_ms
        << " total_ms="
        << result.total_ms
        << " samples="
        << audio.size()
        << "\n";

    return 0;

  } catch (
      const std::exception &e) {
    std::cerr
        << "ERROR: "
        << e.what()
        << "\n";

    return 1;
  }
}
