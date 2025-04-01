import os
from tika import parser
import PyPDF2

# Function to extract specific pages from the original PDF
def extract_pages(input_pdf, pages_to_extract, output_pdf):
    with open(input_pdf, "rb") as infile:
        reader = PyPDF2.PdfReader(infile)
        writer = PyPDF2.PdfWriter()

        for page_num in pages_to_extract:
            writer.add_page(reader.pages[page_num])

        with open(output_pdf, "wb") as outfile:
            writer.write(outfile)

# Function to extract text from a PDF using Tika OCR
def extract_text_from_pdf(pdf_path):
    raw = parser.from_file(pdf_path)
    text = raw.get('content', '')
    return text

# Function to process specific pages in a PDF
def extract_text_from_pages(input_pdf, pages_to_extract):
    # Define the temporary output PDF path for the selected pages
    output_pdf = "extracted_pages.pdf"
    
    # Extract the specified pages from the input PDF
    extract_pages(input_pdf, pages_to_extract, output_pdf)

    # Extract text using Tika OCR on the new PDF with selected pages
    ocr_text = extract_text_from_pdf(output_pdf)
    
    # Clean up temporary output PDF
    os.remove(output_pdf)
    
    return ocr_text

# Example usage
pdf_path = "sample.pdf"
pages = [1]  # Pages to extract (0-indexed)

# Extract text from the specified pages
ocr_text = extract_text_from_pages(pdf_path, pages)

# Print the extracted OCR text
print(ocr_text)
