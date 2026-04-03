/**
 * AudioWorklet processor for real-time PCM capture.
 *
 * Runs on a dedicated audio rendering thread. Accumulates 128-sample
 * input buffers into larger chunks, computes RMS, downsamples to the
 * target sample rate, and posts Int16 PCM frames back to the main thread.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const settings = options.processorOptions || {};
    this.targetRate = settings.targetRate || 16000;
    this.chunkSize = settings.chunkSize || 2048;
    this.buffer = new Float32Array(0);
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input || input.length === 0) {
      return true;
    }

    // Accumulate samples
    const merged = new Float32Array(this.buffer.length + input.length);
    merged.set(this.buffer);
    merged.set(input, this.buffer.length);

    if (merged.length < this.chunkSize) {
      this.buffer = merged;
      return true;
    }

    // Process full chunk
    const chunk = merged.subarray(0, this.chunkSize);
    this.buffer = merged.subarray(this.chunkSize);

    // Compute RMS
    let sumSq = 0;
    for (let i = 0; i < chunk.length; i++) {
      sumSq += chunk[i] * chunk[i];
    }
    const rms = Math.sqrt(sumSq / chunk.length);

    // Downsample
    const ratio = sampleRate / this.targetRate;
    const outLen = Math.round(chunk.length / ratio);
    const downsampled = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcStart = Math.round(i * ratio);
      const srcEnd = Math.min(Math.round((i + 1) * ratio), chunk.length);
      let acc = 0;
      let count = 0;
      for (let j = srcStart; j < srcEnd; j++) {
        acc += chunk[j];
        count++;
      }
      downsampled[i] = count > 0 ? acc / count : 0;
    }

    // Convert to Int16
    const pcm16 = new Int16Array(downsampled.length);
    for (let i = 0; i < downsampled.length; i++) {
      const s = Math.max(-1, Math.min(1, downsampled[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    // Post to main thread (transfer buffer to avoid copy)
    this.port.postMessage({ pcm: pcm16, rms }, [pcm16.buffer]);

    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
