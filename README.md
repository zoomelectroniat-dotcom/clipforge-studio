. Title & Intro
. # ClipForge-Studio 🎬🤖

**ClipForge-Studio** is an advanced, automated AI-powered video clipping engine built in Python. It bridges the gap between long-form content consumption and short-form distribution by automatically ingesting YouTube videos, extracting and chunking transcripts, leveraging high-speed LLMs via Groq to detect viral hooks, and processing high-resolution video cuts via FFmpeg.

---

## 🌟 Architectural Workflow
. **Information Extraction & Transcript Ingestion:**
   * Fetches metadata (title, duration, channel info) using `yt-dlp`.
   * Pulls multilingual transcripts (`youtube-transcript-api`) with smart fallback handling.
. **AI-Driven Viral Moment Analysis (Groq API):**
   * Breaks long videos down into manageable chronological chunks (`WINDOW_SEC`).
   * Feeds transcripts into Groq’s optimized models (`openai/gpt-oss-120b`) using structured JSON prompting.
   * Evaluates content based on hooks, emotional spikes, self-containment, and narrative strength.
   * Automatically handles rate limits with exponential backoff and retries.
. **Smart Boundary Snap & Scoring:**
   * Aligns AI timestamps strictly with sentence and segment boundaries.
   * Enforces strict duration limits (default: 30–90 seconds) tailored for short-form algorithms[cite: 1].
   * Ranks and filters overlapping clips to ensure maximum variety and engagement[cite: 1].
. **Automated High-Performance Rendering (FFmpeg):**
   * Downloads high-resolution source video matching target aspect ratios (up to 4K sources for crop clarity)[cite: 1].
   * Automatically crops and scales content into **9:16 vertical** (TikTok/Reels/Shorts), **1:1 square** (Instagram), or **Original** formats using `lanczos` scaling and denoise filters (`hqdn3d`)[cite: 1].

---

## 🛠️ Prerequisites & Installation

Make sure you have Python installed, then run the following commands in your terminal:

```bash
# Install dependencies
pip install -U yt-dlp youtube-transcript-api groq


Prerequisites & Installation
## 🛠️ Prerequisites & Installation

Make sure you have Python installed, then run the following commands in your terminal:

```bash
# Install dependencies
pip install -U yt-dlp youtube-transcript-api groq

Install FFmpeg
winget install ffmpeg

Run the script
python clipai_free.py

Paste the YouTube link when prompted and select your preferred format and quality
## 📂 Output Structure
All extracted clips are automatically saved in the `clips_output/` directory with clear naming conventions:
* Includes unique video IDs, format type (`vertical`/`square`/`original`), quality tags (`hd`/`sd`), and clean slugified titles.

## 📜 License
This project is open-source under the [MIT License](LICENSE).
