from docx import Document

def extract_docx_text(file_path):
    doc = Document(file_path)
    text = []

    for para in doc.paragraphs:
        text.append(para.text)

    return "\n".join(text)