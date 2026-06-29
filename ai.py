import os
import logging
from dotenv import load_dotenv
from groq import Groq
from pypdf import PdfReader

# ------------------ SETUP ------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ------------------ 1️⃣ TEXT EXTRACTION (PDF + DOCX) ------------------
def extract_pdf_text(file_path):
    """Extract text from PDF or DOCX files."""
    try:
        logger.info(f"Extracting text from: {file_path}")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()

        # ── DOCX ──
        if ext == '.docx':
            try:
                from docx import Document
            except ImportError:
                raise ImportError("python-docx not installed. Run: pip install python-docx")

            doc = Document(file_path)
            text = "\n".join(
                para.text for para in doc.paragraphs if para.text.strip()
            )
            if not text.strip():
                raise ValueError("No readable text found in DOCX")
            logger.info(f"✓ Extracted {len(text)} characters from DOCX")
            return text

        # ── PDF ──
        elif ext == '.pdf':
            reader = PdfReader(file_path)
            if len(reader.pages) == 0:
                raise ValueError("PDF has no pages")
            text = ""
            for i, page in enumerate(reader.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                except Exception as e:
                    logger.warning(f"Page {i} skipped: {e}")
            if not text.strip():
                raise ValueError("No readable text found in PDF")
            logger.info(f"✓ Extracted {len(text)} characters from PDF")
            return text

        else:
            raise ValueError(f"Unsupported file type: {ext}. Only PDF and DOCX are supported.")

    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        return None


# ------------------ 2️⃣ SUMMARY (RUN ONLY ONCE ON APPROVE) ------------------
def generate_summary(text):
    try:
        chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]

        summaries = []

        for chunk in chunks[:5]:
            prompt = f"Summarize this:\n{chunk}"

            res = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            summaries.append(res.choices[0].message.content)

        final_prompt = "Combine into one summary:\n" + "\n".join(summaries)

        final_res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.3
        )

        return final_res.choices[0].message.content

    except Exception as e:
        return f"Error: {e}"


# ------------------ 3️⃣ Q&A (FAST CHAT) ------------------
def ask_question(context, question):
    try:
        if not context or not context.strip():
            return "Error: No document context available."
        if not question or not question.strip():
            return "Error: Question cannot be empty."

        logger.info(f"Question: {question}")

        context = context[:1500]

        prompt = f"""You are a strict AI assistant.

Rules:
1. Answer ONLY from the given context
2. If the answer is not present, say: "This information is not available in the document."
3. Do NOT guess

Context:
{context}

Question: {question}"""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        result = response.choices[0].message.content.strip()
        logger.info("✓ Answer generated")
        return result

    except Exception as e:
        logger.error(f"Q&A error: {e}")
        return f"Error: {e}"