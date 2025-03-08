from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import google.generativeai as genai
import os
import tempfile
import uuid
import time
from dotenv import load_dotenv
import asyncio
import logging
from datetime import timedelta

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up Google Gemini API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set")

genai.configure(api_key=GOOGLE_API_KEY)

app = FastAPI(title="Hinglish Transcription Service")

# Create temp directory for storing files
TEMP_DIR = tempfile.mkdtemp()
OUTPUT_DIR = os.path.join(TEMP_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Define system instruction for Gemini
SYSTEM_INSTRUCTION = """
You are a specialized transcription assistant focused on Hindi-English mixed audio (Hinglish).
Your task is to transcribe the audio accurately, preserving the mixed language nature.
Write the transcript in Roman script (not Devanagari), and format as a properly timed SRT file.
Focus on natural Hinglish transcription without attempting to translate either to pure Hindi or English.
"""

# Helper function to convert seconds to SRT timestamp format (HH:MM:SS,mmm)
def seconds_to_srt_timestamp(seconds):
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int(td.microseconds / 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

# Convert text to SRT format
def text_to_srt(transcript_text):
    """Convert raw transcript to SRT format with timestamps"""
    lines = transcript_text.strip().split('\n')
    srt_content = []
    
    # If Gemini already returned SRT format, just clean it up
    if lines and lines[0].isdigit() and '-->' in lines[1]:
        return transcript_text
    
    # Create segments (approximately 5 seconds each)
    segment_length = 5  # in seconds
    total_duration = len(lines) * segment_length  # Rough estimate
    
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
            
        start_time = (i-1) * segment_length
        end_time = i * segment_length
        
        start_timestamp = seconds_to_srt_timestamp(start_time)
        end_timestamp = seconds_to_srt_timestamp(end_time)
        
        srt_content.append(f"{i}\n{start_timestamp} --> {end_timestamp}\n{line}\n")
    
    return "\n".join(srt_content)

# Process audio file and generate SRT
async def process_audio(audio_path, output_path):
    try:
        # Upload file to Gemini
        logger.info(f"Uploading audio file: {audio_path}")
        audio_file = genai.upload_file(path=audio_path)
        
        # Set up the model with system instruction
        model = genai.GenerativeModel(
            model_name="models/gemini-2.0-flash",
            system_instruction=SYSTEM_INSTRUCTION
        )
        
        # Generate transcript
        prompt = "Transcribe this audio file to Hinglish (Hindi-English mix) in SRT format. Use Roman script for Hindi words. Include proper timestamps."
        logger.info("Sending request to Gemini API")
        
        response = model.generate_content(
            [prompt, audio_file],
            request_options={"timeout": 600}
        )
        
        # Process the response
        transcript_text = response.text
        logger.info("Received transcript from Gemini")
        
        # Format as SRT if needed
        srt_content = text_to_srt(transcript_text)
        
        # Write to file with UTF-8 encoding
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        logger.info(f"SRT file created: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error in processing audio: {str(e)}")
        return False

# Status tracking for jobs
job_status = {}

# Define API endpoints
@app.post("/upload")
async def upload_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    # Generate unique ID for this job
    job_id = str(uuid.uuid4())
    
    # Save the uploaded file
    audio_path = os.path.join(TEMP_DIR, f"{job_id}_{file.filename}")
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}.srt")
    
    # Update job status
    job_status[job_id] = {
        "status": "processing",
        "filename": file.filename,
        "output": output_path
    }
    
    # Save uploaded file
    with open(audio_path, "wb") as buffer:
        buffer.write(await file.read())
    
    # Process in background
    background_tasks.add_task(process_audio_background, job_id, audio_path, output_path)
    
    return {"job_id": job_id, "status": "processing"}

async def process_audio_background(job_id, audio_path, output_path):
    """Background task for processing audio"""
    try:
        success = await process_audio(audio_path, output_path)
        if success:
            job_status[job_id]["status"] = "completed"
        else:
            job_status[job_id]["status"] = "failed"
    except Exception as e:
        logger.error(f"Background processing error: {str(e)}")
        job_status[job_id]["status"] = "failed"
    finally:
        # Clean up the audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Check the status of a transcription job"""
    if job_id not in job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job_status[job_id]

@app.get("/download/{job_id}")
async def download_srt(job_id: str):
    """Download the generated SRT file"""
    if job_id not in job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = job_status[job_id]
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Job is {job['status']}, not ready for download")
    
    original_filename = os.path.splitext(job["filename"])[0]
    
    return FileResponse(
        path=job["output"],
        filename=f"{original_filename}.srt",
        media_type="application/x-subrip"
    )

# Main HTML UI
@app.get("/", response_class=HTMLResponse)
async def get_html(request: Request):
    return FileResponse('app/templates/index.html')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)