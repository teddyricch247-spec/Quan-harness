// Voice typing: record a short clip from the microphone.
//
// The page sends the clip to POST /api/chat/transcribe (api.ts, transcribeAudio)
// and puts the returned text in the message box for the user to edit and send.
// The audio itself is never sent to Kael and never stored; see
// backend/app/transcription.py.
//
// The clip is recorded in whatever format the browser offers (webm/Opus on
// Chrome, Edge, Firefox and Android; mp4/AAC on Safari and iPhone). The server
// judges the format from the bytes.

// Mirrors backend/app/transcription.py (MAX_RECORDING_SECONDS). The server caps
// the upload by size, so this is what keeps a clip under it.
export const VOICE_MAX_SECONDS = 120;
// A tap-and-release shorter than this is not speech.
export const VOICE_MIN_MS = 700;
// Peak loudness (0 to 1) a recording must reach to count as "heard something".
// Room noise sits around 0.01-0.02, speech well above 0.1.
const SPEECH_PEAK = 0.03;

export interface VoiceClip {
  blob: Blob;
  durationMs: number;
  // False when the microphone only picked up silence. Sending silence to a
  // speech model makes it invent words, so the page does not send it.
  heardSpeech: boolean;
}

export interface VoiceRecorder {
  // Ends the recording and resolves with the clip. Safe to call twice.
  stop: () => Promise<VoiceClip>;
  // Throws the recording away and releases the microphone.
  cancel: () => void;
}

export interface VoiceOptions {
  // Called about every 250 ms with the seconds recorded so far.
  onTick?: (seconds: number) => void;
  // Called once when VOICE_MAX_SECONDS is reached; the page should stop().
  onLimit?: () => void;
}

export class VoiceError extends Error {}

// True when this browser can record (needs a secure page, https or localhost).
export const isVoiceSupported = (): boolean =>
  typeof window !== 'undefined' &&
  typeof navigator !== 'undefined' &&
  !!navigator.mediaDevices &&
  typeof navigator.mediaDevices.getUserMedia === 'function' &&
  typeof MediaRecorder !== 'undefined';

const pickMimeType = (): string | undefined => {
  if (typeof MediaRecorder.isTypeSupported !== 'function') return undefined;
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find((t) => MediaRecorder.isTypeSupported(t));
};

const micErrorMessage = (err: unknown): string => {
  const name = err instanceof DOMException || err instanceof Error ? err.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return "Microphone access is blocked. Allow it for this site in your browser's settings, then try again.";
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found on this device.';
  if (name === 'NotReadableError') return 'The microphone is in use by another app. Close it and try again.';
  return "Couldn't start recording. Please try again.";
};

export async function startVoiceRecording(options: VoiceOptions = {}): Promise<VoiceRecorder> {
  if (!isVoiceSupported()) throw new VoiceError("Voice typing isn't available in this browser.");

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (err) {
    throw new VoiceError(micErrorMessage(err));
  }

  const releaseTracks = () => stream.getTracks().forEach((t) => t.stop());

  let recorder: MediaRecorder;
  try {
    const mimeType = pickMimeType();
    // A low bitrate is plenty for speech and keeps a clip small to upload.
    recorder = new MediaRecorder(stream, { ...(mimeType ? { mimeType } : {}), audioBitsPerSecond: 32_000 });
  } catch {
    releaseTracks();
    throw new VoiceError("Couldn't start recording in this browser.");
  }

  // Loudness meter, only to tell speech from silence. If it cannot run, the
  // clip is assumed to contain speech.
  let peak = 0;
  let meterTimer: ReturnType<typeof setInterval> | null = null;
  let audioCtx: AudioContext | null = null;
  try {
    const Ctx: typeof AudioContext | undefined =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (Ctx) {
      audioCtx = new Ctx();
      void audioCtx.resume().catch(() => {});
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      audioCtx.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      meterTimer = setInterval(() => {
        analyser.getByteTimeDomainData(samples);
        for (let i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i] - 128) / 128);
      }, 100);
    }
  } catch {
    audioCtx = null;
  }

  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  const startedAt = performance.now();
  let tickTimer: ReturnType<typeof setInterval> | null = null;
  let finished: Promise<VoiceClip> | null = null;
  let cancelled = false;

  const cleanup = () => {
    if (tickTimer) clearInterval(tickTimer);
    if (meterTimer) clearInterval(meterTimer);
    tickTimer = null;
    meterTimer = null;
    releaseTracks();
    if (audioCtx) void audioCtx.close().catch(() => {});
  };

  let limitFired = false;
  tickTimer = setInterval(() => {
    const seconds = (performance.now() - startedAt) / 1000;
    options.onTick?.(Math.min(seconds, VOICE_MAX_SECONDS));
    if (seconds >= VOICE_MAX_SECONDS && !limitFired) {
      limitFired = true;
      options.onLimit?.();
    }
  }, 250);

  recorder.start();

  return {
    stop: () => {
      if (finished) return finished;
      finished = new Promise<VoiceClip>((resolve, reject) => {
        recorder.onstop = () => {
          const durationMs = performance.now() - startedAt;
          const heard = peak === 0 ? true : peak >= SPEECH_PEAK;
          const type = recorder.mimeType || chunks[0]?.type || 'audio/webm';
          cleanup();
          if (cancelled) {
            reject(new VoiceError('Recording cancelled.'));
            return;
          }
          resolve({ blob: new Blob(chunks, { type }), durationMs, heardSpeech: heard });
        };
        recorder.onerror = () => {
          cleanup();
          reject(new VoiceError('The recording failed. Please try again.'));
        };
        try {
          if (recorder.state !== 'inactive') recorder.stop();
          else recorder.onstop?.(new Event('stop'));
        } catch {
          cleanup();
          reject(new VoiceError('The recording failed. Please try again.'));
        }
      });
      return finished;
    },
    cancel: () => {
      cancelled = true;
      if (finished) return;
      finished = Promise.reject(new VoiceError('Recording cancelled.'));
      finished.catch(() => {}); // nobody awaits a cancelled recording
      try {
        if (recorder.state !== 'inactive') recorder.stop();
      } catch {
        // Already stopped.
      }
      cleanup();
    },
  };
}
