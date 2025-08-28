#!/usr/bin/env python3
"""
Business Idea Refinement Agent

A CLI tool that analyzes business ideas using Gemini Pro 2.5, generates audio feedback
using Gemini TTS, and delivers results via email using Resend API.
"""

import argparse
import os
import sys
import json
import base64
import mimetypes
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from google import genai
from google.genai import types
import requests
from dotenv import load_dotenv
import markdown
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Load environment variables
load_dotenv()

class BusinessIdeaAgent:
    """Main agent class for business idea refinement"""
    
    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.resend_api_key = os.getenv("RESEND_API_KEY")
        self.user_email = os.getenv("USER_EMAIL", "daniel@danielrosehill.com")
        
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        self.client = genai.Client(api_key=self.gemini_api_key)
        
        # Create output directories
        self.output_dir = Path("agent/feedback")
        self.output_dir.mkdir(exist_ok=True)
        
        # Set up user ideas directories
        self.pending_dir = Path("agent/user-ideas/pending")
        self.evaluated_dir = Path("agent/user-ideas/evaluated")
        self.evaluated_dir.mkdir(exist_ok=True)
        
    def load_system_prompt(self) -> str:
        """Load the system prompt from the design file"""
        prompt_file = Path("design/system-prompt.md")
        if prompt_file.exists():
            return prompt_file.read_text().strip()
        else:
            # Fallback system prompt
            return """Your purpose is to act as a friendly and helpful business refinement agent. 
            Your task is to assist the user by providing analysis, evaluation and feedback upon a business idea.
            Write in a conversational style as Herman Poppleberry, addressing Daniel directly."""
    
    def generate_filename_suggestion(self, business_idea: str) -> str:
        """Generate a filename suggestion based on the business idea"""
        print("🤖 Generating filename suggestion...")
        
        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=f"""Based on this business idea, suggest a short, descriptive filename (2-4 words, kebab-case) that captures the essence of the idea:

{business_idea}

Respond with ONLY the filename suggestion, no explanation. Examples: "ai-fitness-coach", "smart-plant-monitor", "crypto-learning-app".""")]
                )
            ]
            
            config = types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=50
            )
            
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=contents,
                config=config
            )
            
            if response.text:
                # Clean and validate the suggestion
                suggestion = response.text.strip().lower()
                suggestion = suggestion.replace(' ', '-').replace('_', '-')
                # Remove any non-alphanumeric characters except hyphens
                suggestion = ''.join(c for c in suggestion if c.isalnum() or c == '-')
                print(f"💡 Suggested filename: {suggestion}")
                return suggestion
            else:
                return "business-idea"
                
        except Exception as e:
            print(f"⚠️ Error generating filename suggestion: {e}")
            return "business-idea"
    
    def analyze_business_idea(self, business_idea: str) -> str:
        """Analyze the business idea using Gemini Pro 2.5"""
        print("🧠 Analyzing business idea with Gemini Pro 2.5...")
        
        system_prompt = self.load_system_prompt()
        
        # Use the system prompt exactly as written, with the business idea appended
        full_prompt = f"""{system_prompt}

Here is the business idea for you to analyze:

{business_idea}"""
        
        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=full_prompt)]
                )
            ]
            
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=2048
            )
            
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",  # Using latest available model
                contents=contents,
                config=config
            )
            
            if response.text:
                print("✅ Business idea analysis completed")
                return response.text
            else:
                raise Exception("No text response received from Gemini")
                
        except Exception as e:
            print(f"❌ Error analyzing business idea: {e}")
            raise
    
    def generate_audio_feedback(self, analysis_text: str, voice_style: str = "upbeat") -> str:
        """Generate audio feedback using Gemini TTS"""
        print("🎵 Generating audio feedback with Gemini TTS...")
        
        # Voice instruction based on style
        voice_instructions = {
            "serious": "Read this text in a stern and authoritative voice. Emulate the cadence and tone of voice of a judge delivering a verdict.",
            "flippant": "Read this text with a sense of sadness and defeatism as if you are delivering hopeless news to somebody.",
            "upbeat": "Read this text in a highly encouraging and upbeat tone of voice - the kind that you might hear in a cheesy radio informercial"
        }
        
        instruction = voice_instructions.get(voice_style, voice_instructions["upbeat"])
        tts_prompt = f"{instruction}\n\n{analysis_text}"
        
        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=tts_prompt)]
                )
            ]
            
            config = types.GenerateContentConfig(
                temperature=1,
                response_modalities=["audio"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Charon"
                        )
                    )
                )
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_filename = f"business_analysis_{timestamp}.wav"
            audio_path = self.output_dir / audio_filename
            
            file_index = 0
            for chunk in self.client.models.generate_content_stream(
                model="gemini-2.5-flash-preview-tts",
                contents=contents,
                config=config
            ):
                if (chunk.candidates and 
                    chunk.candidates[0].content and 
                    chunk.candidates[0].content.parts):
                    
                    part = chunk.candidates[0].content.parts[0]
                    if part.inline_data and part.inline_data.data:
                        inline_data = part.inline_data
                        data_buffer = inline_data.data
                        
                        file_extension = mimetypes.guess_extension(inline_data.mime_type)
                        if file_extension is None:
                            file_extension = ".wav"
                            data_buffer = self._convert_to_wav(inline_data.data, inline_data.mime_type)
                        
                        final_path = self.output_dir / f"{audio_filename.replace('.wav', '')}{file_extension}"
                        self._save_binary_file(str(final_path), data_buffer)
                        print(f"✅ Audio feedback generated: {final_path}")
                        return str(final_path)
            
            raise Exception("No audio data received from TTS")
            
        except Exception as e:
            print(f"❌ Error generating audio feedback: {e}")
            raise
    
    def generate_markdown_file(self, analysis_text: str, business_idea: str, filename_base: str, output_folder: Path) -> str:
        """Generate markdown file from analysis"""
        markdown_filename = f"{filename_base}.md"
        markdown_path = output_folder / markdown_filename
        
        markdown_content = f"""# Business Idea Analysis
**Date**: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}  
**Analyst**: Herman Poppleberry

## Original Business Idea

{business_idea}

## Analysis & Feedback

{analysis_text}

---
*Generated by Business Idea Refinement Agent*
"""
        
        markdown_path.write_text(markdown_content)
        print(f"📄 Markdown analysis saved: {markdown_path}")
        return str(markdown_path)
    
    def generate_pdf_file(self, analysis_text: str, business_idea: str, filename_base: str, output_folder: Path) -> str:
        """Generate PDF file from analysis"""
        pdf_filename = f"{filename_base}.pdf"
        pdf_path = output_folder / pdf_filename
        
        # Create PDF document
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            textColor='#2c3e50'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=20,
            spaceAfter=10,
            textColor='#34495e'
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=12,
            leading=16
        )
        
        # Build PDF content
        story = []
        
        # Title
        story.append(Paragraph("Business Idea Analysis", title_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Metadata
        story.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", body_style))
        story.append(Paragraph("<b>Analyst:</b> Herman Poppleberry", body_style))
        story.append(Spacer(1, 0.3*inch))
        
        # Original idea
        story.append(Paragraph("Original Business Idea", heading_style))
        story.append(Paragraph(business_idea.replace('\n', '<br/>'), body_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Analysis
        story.append(Paragraph("Analysis & Feedback", heading_style))
        
        # Split analysis into paragraphs for better formatting
        paragraphs = analysis_text.split('\n\n')
        for para in paragraphs:
            if para.strip():
                story.append(Paragraph(para.strip().replace('\n', '<br/>'), body_style))
        
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph("<i>Generated by Business Idea Refinement Agent</i>", body_style))
        
        # Build PDF
        doc.build(story)
        print(f"📄 PDF analysis saved: {pdf_path}")
        return str(pdf_path)
    
    def send_email_with_attachments(self, analysis_text: str, audio_file_path: str, 
                                   markdown_file_path: str, pdf_file_path: str) -> bool:
        """Send email with analysis and audio attachment using Resend API"""
        if not self.resend_api_key:
            print("⚠️  RESEND_API_KEY not set, skipping email delivery")
            return False
            
        print("📧 Sending email with feedback...")
        
        try:
            # Read all files
            with open(audio_file_path, 'rb') as f:
                audio_data = f.read()
            with open(markdown_file_path, 'rb') as f:
                markdown_data = f.read()
            with open(pdf_file_path, 'rb') as f:
                pdf_data = f.read()
            
            # Create email summary (first 200 chars of analysis)
            summary = analysis_text[:200] + "..." if len(analysis_text) > 200 else analysis_text
            
            # Prepare email data
            email_data = {
                "from": "Herman Poppleberry <noreply@danielrosehill.co.il>",
                "to": [self.user_email],
                "subject": "Your Business Idea Analysis from Herman Poppleberry",
                "html": f"""
                <h2>Business Idea Analysis Complete!</h2>
                <p>Hi Daniel!</p>
                <p>Herman Poppleberry here with your latest business idea analysis. I've prepared three formats for your convenience:</p>
                
                <ul>
                    <li><strong>🎵 Audio Feedback</strong> - Listen to my complete analysis</li>
                    <li><strong>📄 Markdown File</strong> - Easy to read and edit digitally</li>
                    <li><strong>📄 PDF Report</strong> - Professional printable format</li>
                </ul>
                
                <h3>Quick Summary:</h3>
                <p>{summary}</p>
                
                <p>All three formats contain the same comprehensive analysis and recommendations.</p>
                
                <p>Best regards,<br>
                Herman Poppleberry<br>
                Your AI Business Plan Review Assistant</p>
                """,
                "attachments": [
                    {
                        "filename": Path(audio_file_path).name,
                        "content": base64.b64encode(audio_data).decode(),
                        "content_type": "audio/wav"
                    },
                    {
                        "filename": Path(markdown_file_path).name,
                        "content": base64.b64encode(markdown_data).decode(),
                        "content_type": "text/markdown"
                    },
                    {
                        "filename": Path(pdf_file_path).name,
                        "content": base64.b64encode(pdf_data).decode(),
                        "content_type": "application/pdf"
                    }
                ]
            }
            
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json"
                },
                json=email_data
            )
            
            if response.status_code == 200:
                print("✅ Email sent successfully!")
                return True
            else:
                print(f"❌ Failed to send email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Error sending email: {e}")
            return False
    
    def move_idea_to_evaluated(self, input_file_path: str) -> str:
        """Move processed idea file from pending to evaluated"""
        input_path = Path(input_file_path)
        if input_path.exists() and "pending" in str(input_path):
            # Create new path in evaluated directory
            evaluated_path = self.evaluated_dir / input_path.name
            
            # Move the file
            input_path.rename(evaluated_path)
            print(f"📁 Moved {input_path.name} to evaluated directory")
            return str(evaluated_path)
        return input_file_path
    
    def get_pending_ideas(self) -> list:
        """Get list of pending idea files for autocompletion"""
        if self.pending_dir.exists():
            return [f.name for f in self.pending_dir.glob("*.md")]
        return []
    
    def process_business_idea(self, business_idea: str, voice_style: str = "upbeat", 
                            send_email: bool = True, input_file_path: Optional[str] = None) -> Dict[str, Any]:
        """Complete workflow: analyze, generate audio, and optionally send email"""
        print(f"🚀 Starting business idea refinement process...")
        print(f"📝 Business idea length: {len(business_idea)} characters")
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "business_idea": business_idea,
            "voice_style": voice_style,
            "analysis_text": None,
            "audio_file": None,
            "email_sent": False
        }
        
        try:
            # Step 1: Analyze business idea
            analysis_text = self.analyze_business_idea(business_idea)
            results["analysis_text"] = analysis_text
            
            # Step 2: Generate filename suggestion and create output folder
            filename_suggestion = self.generate_filename_suggestion(business_idea)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = f"{timestamp}_{filename_suggestion}"
            output_folder = self.output_dir / folder_name
            output_folder.mkdir(exist_ok=True)
            print(f"📁 Created output folder: {output_folder}")
            
            # Step 3: Generate audio feedback
            audio_file = self.generate_audio_feedback(analysis_text, voice_style)
            # Move audio file to the new folder
            audio_filename = f"{filename_suggestion}_audio.wav"
            new_audio_path = output_folder / audio_filename
            Path(audio_file).rename(new_audio_path)
            audio_file = str(new_audio_path)
            results["audio_file"] = audio_file
            
            # Step 4: Generate markdown and PDF files
            markdown_file = self.generate_markdown_file(analysis_text, business_idea, f"{filename_suggestion}_analysis", output_folder)
            pdf_file = self.generate_pdf_file(analysis_text, business_idea, f"{filename_suggestion}_analysis", output_folder)
            results["markdown_file"] = markdown_file
            results["pdf_file"] = pdf_file
            
            # Also save text analysis in the folder
            text_file = output_folder / f"{filename_suggestion}_analysis.txt"
            text_file.write_text(analysis_text)
            print(f"💾 Text analysis saved to: {text_file}")
            results["text_file"] = str(text_file)
            
            # Step 5: Send email (optional)
            if send_email:
                email_success = self.send_email_with_attachments(analysis_text, audio_file, markdown_file, pdf_file)
                results["email_sent"] = email_success
            
            # Move file from pending to evaluated if it was loaded from pending
            if input_file_path:
                moved_path = self.move_idea_to_evaluated(input_file_path)
                results["moved_to_evaluated"] = moved_path
            
            print("🎉 Business idea refinement process completed successfully!")
            return results
            
        except Exception as e:
            print(f"💥 Error in business idea refinement process: {e}")
            raise
    
    def _save_binary_file(self, file_path: str, data: bytes):
        """Save binary data to file"""
        with open(file_path, "wb") as f:
            f.write(data)
    
    def _convert_to_wav(self, audio_data: bytes, mime_type: str) -> bytes:
        """Convert audio data to WAV format"""
        parameters = self._parse_audio_mime_type(mime_type)
        bits_per_sample = parameters["bits_per_sample"]
        sample_rate = parameters["rate"]
        num_channels = 1
        data_size = len(audio_data)
        bytes_per_sample = bits_per_sample // 8
        block_align = num_channels * bytes_per_sample
        byte_rate = sample_rate * block_align
        chunk_size = 36 + data_size
        
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", chunk_size, b"WAVE", b"fmt ", 16, 1,
            num_channels, sample_rate, byte_rate, block_align,
            bits_per_sample, b"data", data_size
        )
        return header + audio_data
    
    def _parse_audio_mime_type(self, mime_type: str) -> Dict[str, int]:
        """Parse audio MIME type for conversion parameters"""
        bits_per_sample = 16
        rate = 24000
        
        parts = mime_type.split(";")
        for param in parts:
            param = param.strip()
            if param.lower().startswith("rate="):
                try:
                    rate_str = param.split("=", 1)[1]
                    rate = int(rate_str)
                except (ValueError, IndexError):
                    pass
            elif param.startswith("audio/L"):
                try:
                    bits_per_sample = int(param.split("L", 1)[1])
                except (ValueError, IndexError):
                    pass
        
        return {"bits_per_sample": bits_per_sample, "rate": rate}


def main():
    """CLI interface for the Business Idea Refinement Agent"""
    parser = argparse.ArgumentParser(
        description="Business Idea Refinement Agent - Auto-processes all pending business ideas"
    )
    
    parser.add_argument(
        "--voice-style",
        choices=["serious", "flippant", "upbeat"],
        default="upbeat",
        help="Voice style for audio feedback (default: upbeat)"
    )
    
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending email with results"
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize agent
        agent = BusinessIdeaAgent()
        
        # Get all pending ideas
        pending_ideas = agent.get_pending_ideas()
        
        if not pending_ideas:
            print("📭 No pending business ideas found in agent/user-ideas/pending/")
            print("💡 Add .md files to agent/user-ideas/pending/ to process them")
            return
        
        print(f"🚀 Found {len(pending_ideas)} pending business idea(s) to process")
        print("="*60)
        
        processed_count = 0
        failed_count = 0
        
        for idea_file in pending_ideas:
            try:
                print(f"\n📖 Processing: {idea_file}")
                
                # Load business idea
                pending_file = agent.pending_dir / idea_file
                business_idea = pending_file.read_text().strip()
                
                if not business_idea:
                    print(f"⚠️  Skipping empty file: {idea_file}")
                    continue
                
                # Process the business idea
                results = agent.process_business_idea(
                    business_idea=business_idea,
                    voice_style=args.voice_style,
                    send_email=not args.no_email,
                    input_file_path=str(pending_file)
                )
                
                print(f"✅ Completed: {idea_file}")
                processed_count += 1
                
            except Exception as e:
                print(f"❌ Failed to process {idea_file}: {e}")
                failed_count += 1
                continue
        
        # Final summary
        print("\n" + "="*60)
        print("🎉 BATCH PROCESSING COMPLETE")
        print("="*60)
        print(f"✅ Successfully processed: {processed_count}")
        print(f"❌ Failed: {failed_count}")
        print(f"📁 Output directory: {agent.output_dir}")
        print(f"📧 Email notifications: {'Enabled' if not args.no_email else 'Disabled'}")
        
    except KeyboardInterrupt:
        print("\n🛑 Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
