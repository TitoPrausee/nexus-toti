"""
NEXUS z.ai Integration — Vollständige z.ai CLI Anbindung
========================================================
Alle 9 z-ai CLI Befehle als Python-Funktionen verfügbar.

Commands:
  - chat(prompt, system, thinking, stream) → Chat-Antwort
  - vision(prompt, image, thinking) → Bild-Analyse mit VLM
  - tts(text, output, voice, speed, format) → Text zu Sprache
  - asr(file_or_base64) → Sprache zu Text
  - image_generate(prompt, output, size) → Bild generieren
  - image_edit(prompt, image, output, size) → Bild bearbeiten
  - image_search(query, count, gl) → Bildersuche
  - video_generate(prompt, output, ...) → Video generieren
  - function_invoke(name, args) → Function aufrufen (web_search etc.)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ZAI_CLI_CANDIDATES: List[str] = [
    "/usr/local/bin/z-ai",
    "/usr/bin/z-ai",
    os.path.expanduser("~/.local/bin/z-ai"),
]

# Timeouts (seconds)
TIMEOUT_CHAT = 120
TIMEOUT_VISION = 120
TIMEOUT_TTS = 60
TIMEOUT_ASR = 60
TIMEOUT_IMAGE = 60
TIMEOUT_IMAGE_EDIT = 60
TIMEOUT_IMAGE_SEARCH = 60
TIMEOUT_VIDEO = 300
TIMEOUT_FUNCTION = 60

# Valid image generation sizes
VALID_IMAGE_SIZES: List[str] = [
    "1024x1024",
    "768x1344",
    "864x1152",
    "1344x768",
    "1152x864",
    "1440x720",
    "720x1440",
]

# TTS voices
VALID_TTS_VOICES: List[str] = [
    "tongtong",
]

# TTS formats
VALID_TTS_FORMATS: List[str] = [
    "wav",
    "mp3",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ZAIResult:
    """Structured result returned by every z-ai command."""

    success: bool
    command: str
    data: Optional[Any] = None
    output_path: Optional[str] = None
    raw_stdout: Optional[str] = None
    raw_stderr: Optional[str] = None
    returncode: Optional[int] = None
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "command": self.command,
            "data": self.data,
            "output_path": self.output_path,
            "raw_stdout": self.raw_stdout,
            "raw_stderr": self.raw_stderr,
            "returncode": self.returncode,
            "error": self.error,
            "elapsed_seconds": self.elapsed_seconds,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _find_zai_cli() -> Optional[str]:
    """Locate the z-ai CLI binary on the system."""
    # Check explicit candidate paths first
    for candidate in ZAI_CLI_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # Fallback: search PATH
    found = shutil.which("z-ai")
    if found:
        return found

    return None


def _parse_json_output(raw: str) -> Optional[Any]:
    """Attempt to parse stdout as JSON, returning None on failure."""
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _build_result(
    command: str,
    process: subprocess.CompletedProcess,
    start_time: float,
    output_path: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> ZAIResult:
    """Build a ZAIResult from a completed subprocess."""
    elapsed = time.monotonic() - start_time
    stdout = process.stdout or ""
    stderr = process.stderr or ""
    returncode = process.returncode
    success = returncode == 0
    parsed = _parse_json_output(stdout) if success else None

    error = None
    if not success:
        error = stderr.strip() if stderr.strip() else f"z-ai exited with code {returncode}"

    metadata = extra_metadata or {}

    return ZAIResult(
        success=success,
        command=command,
        data=parsed,
        output_path=output_path,
        raw_stdout=stdout,
        raw_stderr=stderr,
        returncode=returncode,
        error=error,
        elapsed_seconds=round(elapsed, 3),
        metadata=metadata,
    )


async def _build_result_async(
    command: str,
    stdout: str,
    stderr: str,
    returncode: int,
    start_time: float,
    output_path: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> ZAIResult:
    """Build a ZAIResult from async process output."""
    elapsed = time.monotonic() - start_time
    success = returncode == 0
    parsed = _parse_json_output(stdout) if success else None

    error = None
    if not success:
        error = stderr.strip() if stderr.strip() else f"z-ai exited with code {returncode}"

    metadata = extra_metadata or {}

    return ZAIResult(
        success=success,
        command=command,
        data=parsed,
        output_path=output_path,
        raw_stdout=stdout,
        raw_stderr=stderr,
        returncode=returncode,
        error=error,
        elapsed_seconds=round(elapsed, 3),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Main integration class
# ---------------------------------------------------------------------------

class ZAIIntegration:
    """
    Comprehensive wrapper around the z-ai CLI exposing all 9 commands.

    Each command has:
      - A synchronous method (uses subprocess.run)
      - An asynchronous method variant (uses asyncio.create_subprocess_exec)

    All methods return a ZAIResult structured dictionary.
    """

    def __init__(self, cli_path: Optional[str] = None):
        self._cli_path: Optional[str] = None
        self._available: Optional[bool] = None

        if cli_path:
            if os.path.isfile(cli_path) and os.access(cli_path, os.X_OK):
                self._cli_path = cli_path
                self._available = True
            else:
                self._available = False
        else:
            self._cli_path = _find_zai_cli()
            self._available = self._cli_path is not None

    # -----------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """Return True if the z-ai CLI was found and is executable."""
        if self._available is None:
            self._cli_path = _find_zai_cli()
            self._available = self._cli_path is not None
        return self._available

    @property
    def cli_path(self) -> Optional[str]:
        """Return the resolved path to z-ai, or None."""
        return self._cli_path

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _require_cli(self) -> str:
        """Return the CLI path or raise RuntimeError if unavailable."""
        if not self.is_available:
            raise RuntimeError(
                "z-ai CLI not found. Ensure '/usr/local/bin/z-ai' exists and is executable."
            )
        return self._cli_path  # type: ignore[return-value]

    def _run_sync(
        self,
        args: List[str],
        timeout: int,
        command_name: str,
        output_path: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ZAIResult:
        """Execute z-ai synchronously via subprocess.run."""
        cli = self._require_cli()
        full_cmd = [cli] + args
        start = time.monotonic()

        try:
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return _build_result(
                command=command_name,
                process=proc,
                start_time=start,
                output_path=output_path,
                extra_metadata=extra_metadata,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return ZAIResult(
                success=False,
                command=command_name,
                error=f"z-ai {command_name} timed out after {timeout}s",
                elapsed_seconds=round(elapsed, 3),
                metadata=extra_metadata or {},
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return ZAIResult(
                success=False,
                command=command_name,
                error=str(exc),
                elapsed_seconds=round(elapsed, 3),
                metadata=extra_metadata or {},
            )

    async def _run_async(
        self,
        args: List[str],
        timeout: int,
        command_name: str,
        output_path: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ZAIResult:
        """Execute z-ai asynchronously via asyncio.create_subprocess_exec."""
        cli = self._require_cli()
        full_cmd = [cli] + args
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = time.monotonic() - start
                return ZAIResult(
                    success=False,
                    command=command_name,
                    error=f"z-ai {command_name} timed out after {timeout}s",
                    elapsed_seconds=round(elapsed, 3),
                    metadata=extra_metadata or {},
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            returncode = proc.returncode if proc.returncode is not None else -1

            return await _build_result_async(
                command=command_name,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                start_time=start,
                output_path=output_path,
                extra_metadata=extra_metadata,
            )

        except Exception as exc:
            elapsed = time.monotonic() - start
            return ZAIResult(
                success=False,
                command=command_name,
                error=str(exc),
                elapsed_seconds=round(elapsed, 3),
                metadata=extra_metadata or {},
            )

    @staticmethod
    def _temp_path(suffix: str) -> str:
        """Create a temporary file path with the given suffix."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        return tmp.name

    # =================================================================
    # 1. CHAT — Chat completion
    # =================================================================

    def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        thinking: bool = False,
        stream: bool = False,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """
        Synchronous chat completion.

        Args:
            prompt:   The user prompt text.
            system:   Optional system prompt.
            thinking: Enable extended thinking / reasoning.
            stream:   Stream the response (output only meaningful with --output).
            output:   Path to write JSON output.

        Returns:
            ZAIResult with parsed JSON data when available.
        """
        args = ["chat", "--prompt", prompt]
        if system:
            args += ["--system", system]
        if thinking:
            args.append("--thinking")
        if stream:
            args.append("--stream")
        if output:
            args += ["--output", output]

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_CHAT,
            command_name="chat",
            output_path=output,
            extra_metadata={"prompt_length": len(prompt), "thinking": thinking, "stream": stream},
        )

    async def chat_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        thinking: bool = False,
        stream: bool = False,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """Asynchronous variant of chat()."""
        args = ["chat", "--prompt", prompt]
        if system:
            args += ["--system", system]
        if thinking:
            args.append("--thinking")
        if stream:
            args.append("--stream")
        if output:
            args += ["--output", output]

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_CHAT,
            command_name="chat",
            output_path=output,
            extra_metadata={"prompt_length": len(prompt), "thinking": thinking, "stream": stream},
        )

    # =================================================================
    # 2. VISION — Vision chat (image analysis)
    # =================================================================

    def vision(
        self,
        prompt: str,
        image: str,
        thinking: bool = False,
        stream: bool = False,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """
        Synchronous vision chat — analyze an image with a prompt.

        Args:
            prompt:   Text prompt describing what to analyze.
            image:    URL or file path to the image.
            thinking: Enable extended thinking / reasoning.
            stream:   Stream the response.
            output:   Path to write JSON output.

        Returns:
            ZAIResult with parsed JSON data when available.
        """
        args = ["vision", "--prompt", prompt, "--image", image]
        if thinking:
            args.append("--thinking")
        if stream:
            args.append("--stream")
        if output:
            args += ["--output", output]

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_VISION,
            command_name="vision",
            output_path=output,
            extra_metadata={"image_source": image, "thinking": thinking},
        )

    async def vision_async(
        self,
        prompt: str,
        image: str,
        thinking: bool = False,
        stream: bool = False,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """Asynchronous variant of vision()."""
        args = ["vision", "--prompt", prompt, "--image", image]
        if thinking:
            args.append("--thinking")
        if stream:
            args.append("--stream")
        if output:
            args += ["--output", output]

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_VISION,
            command_name="vision",
            output_path=output,
            extra_metadata={"image_source": image, "thinking": thinking},
        )

    # =================================================================
    # 3. TTS — Text to speech
    # =================================================================

    def tts(
        self,
        text: str,
        output: Optional[str] = None,
        voice: str = "tongtong",
        speed: float = 1.0,
        format: str = "wav",
    ) -> ZAIResult:
        """
        Synchronous text-to-speech.

        Args:
            text:   The text to synthesize.
            output: Path for the output audio file. If None, a temp file is used.
            voice:  Voice name (default: "tongtong").
            speed:  Speech speed multiplier (default: 1.0).
            format: Audio format — "wav" or "mp3" (default: "wav").

        Returns:
            ZAIResult with output_path pointing to the generated audio file.
        """
        if output is None:
            ext = f".{format}" if format in VALID_TTS_FORMATS else ".wav"
            output = self._temp_path(ext)

        args = [
            "tts",
            "--input", text,
            "--output", output,
            "--voice", voice,
            "--speed", str(speed),
            "--format", format,
        ]

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_TTS,
            command_name="tts",
            output_path=output,
            extra_metadata={"voice": voice, "speed": speed, "format": format, "text_length": len(text)},
        )

    async def tts_async(
        self,
        text: str,
        output: Optional[str] = None,
        voice: str = "tongtong",
        speed: float = 1.0,
        format: str = "wav",
    ) -> ZAIResult:
        """Asynchronous variant of tts()."""
        if output is None:
            ext = f".{format}" if format in VALID_TTS_FORMATS else ".wav"
            output = self._temp_path(ext)

        args = [
            "tts",
            "--input", text,
            "--output", output,
            "--voice", voice,
            "--speed", str(speed),
            "--format", format,
        ]

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_TTS,
            command_name="tts",
            output_path=output,
            extra_metadata={"voice": voice, "speed": speed, "format": format, "text_length": len(text)},
        )

    # =================================================================
    # 4. ASR — Speech to text
    # =================================================================

    def asr(
        self,
        file: Optional[str] = None,
        base64: Optional[str] = None,
        output: Optional[str] = None,
        stream: bool = False,
    ) -> ZAIResult:
        """
        Synchronous speech-to-text (automatic speech recognition).

        Provide *either* ``file`` (path to audio) *or* ``base64`` (raw base64 data).

        Args:
            file:    Path to the audio file.
            base64:  Base64-encoded audio data.
            output:  Path to write JSON result. If None, a temp file is used.
            stream:  Stream the ASR result.

        Returns:
            ZAIResult with parsed transcription data.
        """
        if file is None and base64 is None:
            return ZAIResult(
                success=False,
                command="asr",
                error="Either 'file' or 'base64' must be provided for ASR.",
            )

        if output is None:
            output = self._temp_path(".json")

        args = ["asr", "--output", output]
        if file:
            args += ["--file", file]
        if base64:
            args += ["--base64", base64]
        if stream:
            args.append("--stream")

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_ASR,
            command_name="asr",
            output_path=output,
            extra_metadata={"input_type": "file" if file else "base64"},
        )

    async def asr_async(
        self,
        file: Optional[str] = None,
        base64: Optional[str] = None,
        output: Optional[str] = None,
        stream: bool = False,
    ) -> ZAIResult:
        """Asynchronous variant of asr()."""
        if file is None and base64 is None:
            return ZAIResult(
                success=False,
                command="asr",
                error="Either 'file' or 'base64' must be provided for ASR.",
            )

        if output is None:
            output = self._temp_path(".json")

        args = ["asr", "--output", output]
        if file:
            args += ["--file", file]
        if base64:
            args += ["--base64", base64]
        if stream:
            args.append("--stream")

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_ASR,
            command_name="asr",
            output_path=output,
            extra_metadata={"input_type": "file" if file else "base64"},
        )

    # =================================================================
    # 5. IMAGE GENERATE — Generate image from prompt
    # =================================================================

    def image_generate(
        self,
        prompt: str,
        output: Optional[str] = None,
        size: str = "1024x1024",
    ) -> ZAIResult:
        """
        Synchronous image generation.

        Args:
            prompt: Description of the desired image.
            output: Path for the output image. If None, a temp file is used.
            size:   Image size (default: "1024x1024").
                    Valid: 1024x1024, 768x1344, 864x1152, 1344x768,
                           1152x864, 1440x720, 720x1440.

        Returns:
            ZAIResult with output_path pointing to the generated image.
        """
        if size not in VALID_IMAGE_SIZES:
            return ZAIResult(
                success=False,
                command="image_generate",
                error=f"Invalid size '{size}'. Valid sizes: {', '.join(VALID_IMAGE_SIZES)}",
            )

        if output is None:
            output = self._temp_path(".png")

        args = [
            "image",
            "--prompt", prompt,
            "--output", output,
            "--size", size,
        ]

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_IMAGE,
            command_name="image_generate",
            output_path=output,
            extra_metadata={"size": size, "prompt_length": len(prompt)},
        )

    async def image_generate_async(
        self,
        prompt: str,
        output: Optional[str] = None,
        size: str = "1024x1024",
    ) -> ZAIResult:
        """Asynchronous variant of image_generate()."""
        if size not in VALID_IMAGE_SIZES:
            return ZAIResult(
                success=False,
                command="image_generate",
                error=f"Invalid size '{size}'. Valid sizes: {', '.join(VALID_IMAGE_SIZES)}",
            )

        if output is None:
            output = self._temp_path(".png")

        args = [
            "image",
            "--prompt", prompt,
            "--output", output,
            "--size", size,
        ]

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_IMAGE,
            command_name="image_generate",
            output_path=output,
            extra_metadata={"size": size, "prompt_length": len(prompt)},
        )

    # =================================================================
    # 6. IMAGE EDIT — Edit an existing image
    # =================================================================

    def image_edit(
        self,
        prompt: str,
        image: str,
        output: Optional[str] = None,
        size: str = "1024x1024",
    ) -> ZAIResult:
        """
        Synchronous image editing.

        Args:
            prompt: Edit description / instruction.
            image:  URL or file path to the source image.
            output: Path for the output image. If None, a temp file is used.
            size:   Output image size (default: "1024x1024").

        Returns:
            ZAIResult with output_path pointing to the edited image.
        """
        if size not in VALID_IMAGE_SIZES:
            return ZAIResult(
                success=False,
                command="image_edit",
                error=f"Invalid size '{size}'. Valid sizes: {', '.join(VALID_IMAGE_SIZES)}",
            )

        if output is None:
            output = self._temp_path(".png")

        args = [
            "image-edit",
            "--prompt", prompt,
            "--image", image,
            "--output", output,
            "--size", size,
        ]

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_IMAGE_EDIT,
            command_name="image_edit",
            output_path=output,
            extra_metadata={"image_source": image, "size": size},
        )

    async def image_edit_async(
        self,
        prompt: str,
        image: str,
        output: Optional[str] = None,
        size: str = "1024x1024",
    ) -> ZAIResult:
        """Asynchronous variant of image_edit()."""
        if size not in VALID_IMAGE_SIZES:
            return ZAIResult(
                success=False,
                command="image_edit",
                error=f"Invalid size '{size}'. Valid sizes: {', '.join(VALID_IMAGE_SIZES)}",
            )

        if output is None:
            output = self._temp_path(".png")

        args = [
            "image-edit",
            "--prompt", prompt,
            "--image", image,
            "--output", output,
            "--size", size,
        ]

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_IMAGE_EDIT,
            command_name="image_edit",
            output_path=output,
            extra_metadata={"image_source": image, "size": size},
        )

    # =================================================================
    # 7. IMAGE SEARCH — Search for images
    # =================================================================

    def image_search(
        self,
        query: str,
        count: int = 10,
        gl: str = "cn",
        no_rank: bool = False,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """
        Synchronous image search.

        Args:
            query:   Search query string.
            count:   Number of results to return (default: 10).
            gl:      Geographic locale (default: "cn").
            no_rank: Disable ranking of results.
            output:  Path to write JSON results. If None, a temp file is used.

        Returns:
            ZAIResult with parsed search results.
        """
        if output is None:
            output = self._temp_path(".json")

        args = [
            "image-search",
            "--query", query,
            "--count", str(count),
            "--gl", gl,
            "--output", output,
        ]
        if no_rank:
            args.append("--no-rank")

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_IMAGE_SEARCH,
            command_name="image_search",
            output_path=output,
            extra_metadata={"query": query, "count": count, "gl": gl, "no_rank": no_rank},
        )

    async def image_search_async(
        self,
        query: str,
        count: int = 10,
        gl: str = "cn",
        no_rank: bool = False,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """Asynchronous variant of image_search()."""
        if output is None:
            output = self._temp_path(".json")

        args = [
            "image-search",
            "--query", query,
            "--count", str(count),
            "--gl", gl,
            "--output", output,
        ]
        if no_rank:
            args.append("--no-rank")

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_IMAGE_SEARCH,
            command_name="image_search",
            output_path=output,
            extra_metadata={"query": query, "count": count, "gl": gl, "no_rank": no_rank},
        )

    # =================================================================
    # 8. VIDEO GENERATE — Generate video from prompt
    # =================================================================

    def video_generate(
        self,
        prompt: str,
        output: Optional[str] = None,
        image_url: Optional[str] = None,
        quality: str = "speed",
        with_audio: bool = False,
        size: str = "1920x1080",
        fps: int = 30,
        duration: int = 5,
        poll: bool = True,
        poll_interval: int = 5,
        max_polls: int = 60,
    ) -> ZAIResult:
        """
        Synchronous video generation.

        By default uses ``--poll`` mode to wait for completion.

        Args:
            prompt:        Video description.
            output:        Path for the JSON result. If None, a temp file is used.
            image_url:     Optional reference image URL.
            quality:       Generation quality — "speed" or "quality" (default: "speed").
            with_audio:    Include audio in the video.
            size:          Video resolution (default: "1920x1080").
            fps:           Frames per second (default: 30).
            duration:      Video duration in seconds (default: 5).
            poll:          Enable polling to wait for completion (default: True).
            poll_interval: Seconds between polls (default: 5).
            max_polls:     Maximum number of polls (default: 60).

        Returns:
            ZAIResult with video generation data.
        """
        if output is None:
            output = self._temp_path(".json")

        args = [
            "video",
            "--prompt", prompt,
            "--output", output,
            "--quality", quality,
            "--size", size,
            "--fps", str(fps),
            "--duration", str(duration),
        ]
        if image_url:
            args += ["--image-url", image_url]
        if with_audio:
            args.append("--with-audio")
        if poll:
            args.append("--poll")
            args += ["--poll-interval", str(poll_interval)]
            args += ["--max-polls", str(max_polls)]

        return self._run_sync(
            args=args,
            timeout=TIMEOUT_VIDEO,
            command_name="video_generate",
            output_path=output,
            extra_metadata={
                "quality": quality,
                "size": size,
                "fps": fps,
                "duration": duration,
                "poll": poll,
                "poll_interval": poll_interval,
                "max_polls": max_polls,
                "with_audio": with_audio,
            },
        )

    async def video_generate_async(
        self,
        prompt: str,
        output: Optional[str] = None,
        image_url: Optional[str] = None,
        quality: str = "speed",
        with_audio: bool = False,
        size: str = "1920x1080",
        fps: int = 30,
        duration: int = 5,
        poll: bool = True,
        poll_interval: int = 5,
        max_polls: int = 60,
    ) -> ZAIResult:
        """Asynchronous variant of video_generate()."""
        if output is None:
            output = self._temp_path(".json")

        args = [
            "video",
            "--prompt", prompt,
            "--output", output,
            "--quality", quality,
            "--size", size,
            "--fps", str(fps),
            "--duration", str(duration),
        ]
        if image_url:
            args += ["--image-url", image_url]
        if with_audio:
            args.append("--with-audio")
        if poll:
            args.append("--poll")
            args += ["--poll-interval", str(poll_interval)]
            args += ["--max-polls", str(max_polls)]

        return await self._run_async(
            args=args,
            timeout=TIMEOUT_VIDEO,
            command_name="video_generate",
            output_path=output,
            extra_metadata={
                "quality": quality,
                "size": size,
                "fps": fps,
                "duration": duration,
                "poll": poll,
                "poll_interval": poll_interval,
                "max_polls": max_polls,
                "with_audio": with_audio,
            },
        )

    # =================================================================
    # 9. FUNCTION INVOKE — Call external functions (web_search etc.)
    # =================================================================

    def function_invoke(
        self,
        name: str,
        args: Optional[Union[Dict[str, Any], str]] = None,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """
        Synchronous function invocation via z-ai.

        Args:
            name:   Function name, e.g. "web_search".
            args:   Function arguments as dict or JSON string.
            output: Path to write JSON result. If None, a temp file is used.

        Returns:
            ZAIResult with parsed function output.
        """
        if output is None:
            output = self._temp_path(".json")

        cli_args = [
            "function",
            "--name", name,
            "--output", output,
        ]

        if args is not None:
            if isinstance(args, dict):
                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = str(args)
            cli_args += ["--args", args_str]

        return self._run_sync(
            args=cli_args,
            timeout=TIMEOUT_FUNCTION,
            command_name="function_invoke",
            output_path=output,
            extra_metadata={"function_name": name},
        )

    async def function_invoke_async(
        self,
        name: str,
        args: Optional[Union[Dict[str, Any], str]] = None,
        output: Optional[str] = None,
    ) -> ZAIResult:
        """Asynchronous variant of function_invoke()."""
        if output is None:
            output = self._temp_path(".json")

        cli_args = [
            "function",
            "--name", name,
            "--output", output,
        ]

        if args is not None:
            if isinstance(args, dict):
                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = str(args)
            cli_args += ["--args", args_str]

        return await self._run_async(
            args=cli_args,
            timeout=TIMEOUT_FUNCTION,
            command_name="function_invoke",
            output_path=output,
            extra_metadata={"function_name": name},
        )

    # =================================================================
    # Capabilities
    # =================================================================

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return a dictionary describing all available z-ai capabilities.

        This inspects the current environment and reports which commands
        are available, along with their supported parameters.
        """
        available = self.is_available

        capabilities: Dict[str, Any] = {
            "cli_available": available,
            "cli_path": self._cli_path,
            "commands": {},
        }

        if not available:
            capabilities["error"] = (
                "z-ai CLI not found. Expected at /usr/local/bin/z-ai or in PATH."
            )
            return capabilities

        # Describe each command
        capabilities["commands"] = {
            "chat": {
                "description": "Chat completion with LLM",
                "params": {
                    "prompt": {"type": "str", "required": True},
                    "system": {"type": "str", "required": False},
                    "thinking": {"type": "bool", "default": False},
                    "stream": {"type": "bool", "default": False},
                    "output": {"type": "str", "required": False},
                },
                "timeout_seconds": TIMEOUT_CHAT,
                "sync": True,
                "async": True,
            },
            "vision": {
                "description": "Vision chat — analyze images with VLM",
                "params": {
                    "prompt": {"type": "str", "required": True},
                    "image": {"type": "str", "required": True, "note": "URL or file path"},
                    "thinking": {"type": "bool", "default": False},
                    "stream": {"type": "bool", "default": False},
                    "output": {"type": "str", "required": False},
                },
                "timeout_seconds": TIMEOUT_VISION,
                "sync": True,
                "async": True,
            },
            "tts": {
                "description": "Text to speech synthesis",
                "params": {
                    "text": {"type": "str", "required": True},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                    "voice": {"type": "str", "default": "tongtong", "options": VALID_TTS_VOICES},
                    "speed": {"type": "float", "default": 1.0},
                    "format": {"type": "str", "default": "wav", "options": VALID_TTS_FORMATS},
                },
                "timeout_seconds": TIMEOUT_TTS,
                "sync": True,
                "async": True,
            },
            "asr": {
                "description": "Automatic speech recognition",
                "params": {
                    "file": {"type": "str", "required": False, "note": "audio file path"},
                    "base64": {"type": "str", "required": False, "note": "base64 audio data"},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                    "stream": {"type": "bool", "default": False},
                },
                "note": "Exactly one of 'file' or 'base64' is required",
                "timeout_seconds": TIMEOUT_ASR,
                "sync": True,
                "async": True,
            },
            "image_generate": {
                "description": "Generate image from text prompt",
                "params": {
                    "prompt": {"type": "str", "required": True},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                    "size": {
                        "type": "str",
                        "default": "1024x1024",
                        "options": VALID_IMAGE_SIZES,
                    },
                },
                "timeout_seconds": TIMEOUT_IMAGE,
                "sync": True,
                "async": True,
            },
            "image_edit": {
                "description": "Edit an existing image with instructions",
                "params": {
                    "prompt": {"type": "str", "required": True},
                    "image": {"type": "str", "required": True, "note": "URL or file path"},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                    "size": {
                        "type": "str",
                        "default": "1024x1024",
                        "options": VALID_IMAGE_SIZES,
                    },
                },
                "timeout_seconds": TIMEOUT_IMAGE_EDIT,
                "sync": True,
                "async": True,
            },
            "image_search": {
                "description": "Search for images by query",
                "params": {
                    "query": {"type": "str", "required": True},
                    "count": {"type": "int", "default": 10},
                    "gl": {"type": "str", "default": "cn"},
                    "no_rank": {"type": "bool", "default": False},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                },
                "timeout_seconds": TIMEOUT_IMAGE_SEARCH,
                "sync": True,
                "async": True,
            },
            "video_generate": {
                "description": "Generate video from text prompt",
                "params": {
                    "prompt": {"type": "str", "required": True},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                    "image_url": {"type": "str", "required": False, "note": "reference image URL"},
                    "quality": {"type": "str", "default": "speed", "options": ["speed", "quality"]},
                    "with_audio": {"type": "bool", "default": False},
                    "size": {"type": "str", "default": "1920x1080"},
                    "fps": {"type": "int", "default": 30},
                    "duration": {"type": "int", "default": 5},
                    "poll": {"type": "bool", "default": True},
                    "poll_interval": {"type": "int", "default": 5},
                    "max_polls": {"type": "int", "default": 60},
                },
                "timeout_seconds": TIMEOUT_VIDEO,
                "sync": True,
                "async": True,
            },
            "function_invoke": {
                "description": "Invoke external functions (web_search, etc.)",
                "params": {
                    "name": {"type": "str", "required": True, "examples": ["web_search"]},
                    "args": {"type": "dict|str", "required": False, "note": "JSON object or string"},
                    "output": {"type": "str", "required": False, "note": "temp file if None"},
                },
                "timeout_seconds": TIMEOUT_FUNCTION,
                "sync": True,
                "async": True,
            },
        }

        return capabilities


# ---------------------------------------------------------------------------
# Module-level convenience singleton
# ---------------------------------------------------------------------------

_default_instance: Optional[ZAIIntegration] = None


def get_zai() -> ZAIIntegration:
    """Return a module-level default ZAIIntegration singleton."""
    global _default_instance
    if _default_instance is None:
        _default_instance = ZAIIntegration()
    return _default_instance


# ---------------------------------------------------------------------------
# Quick-access module-level functions
# ---------------------------------------------------------------------------

def chat(prompt: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai chat."""
    return get_zai().chat(prompt=prompt, **kwargs)


def vision(prompt: str, image: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai vision."""
    return get_zai().vision(prompt=prompt, image=image, **kwargs)


def tts(text: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai tts."""
    return get_zai().tts(text=text, **kwargs)


def asr(file: Optional[str] = None, base64: Optional[str] = None, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai asr."""
    return get_zai().asr(file=file, base64=base64, **kwargs)


def image_generate(prompt: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai image generate."""
    return get_zai().image_generate(prompt=prompt, **kwargs)


def image_edit(prompt: str, image: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai image-edit."""
    return get_zai().image_edit(prompt=prompt, image=image, **kwargs)


def image_search(query: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai image-search."""
    return get_zai().image_search(query=query, **kwargs)


def video_generate(prompt: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai video generate."""
    return get_zai().video_generate(prompt=prompt, **kwargs)


def function_invoke(name: str, **kwargs) -> ZAIResult:
    """Module-level shortcut: z-ai function invoke."""
    return get_zai().function_invoke(name=name, **kwargs)
