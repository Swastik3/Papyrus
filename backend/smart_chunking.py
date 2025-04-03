import time
from gmft.auto import CroppedTable, TableDetector, AutoTableFormatter, AutoTableDetector
from gmft.pdf_bindings import PyPDFium2Document
from gmft_pymupdf import PyMuPDFDocument
import anthropic
import textwrap
import fitz  # PyMuPDF
import base64
import os  
from dotenv import load_dotenv
from PIL import Image
import io
import pandas as pd
from gmft._rich_text.rich_page import embed_tables

load_dotenv()

detector = AutoTableDetector()
formatter = AutoTableFormatter()

def chunk_text(text, chunk_size=1000, overlap=200):
    """Chunk text with overlap."""
    if not text:
        return []
    
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunk = text[i:i + chunk_size]
        chunks.append(chunk)
        if i + chunk_size >= len(text):
            break
    return chunks

def convert_table_to_markdown(table_df: pd.DataFrame) -> str:
    """
    Convert a pandas DataFrame to a markdown-formatted string.
    
    Args:
        table_df (pd.DataFrame): Input DataFrame to convert
    
    Returns:
        str: Markdown-formatted table
    """
    # Ensure the table is well-formatted
    table_df = table_df.fillna('')  # Replace NaN with empty string
    
    # Use pandas built-in to_markdown method
    markdown_table = table_df.to_markdown(index=True)
    print(markdown_table)
    return markdown_table

def process_pdf(pdf_path, chunk_size=1000, overlap=200):
    """
    Process PDF: extract text and tables with context.
    
    Args:
        pdf_path (str): Path to the PDF file
        chunk_size (int): Size of text chunks
        overlap (int): Overlap between chunks
    
    Returns:
        list: Extracted content with text and tables
    """
    start_time = time.time()
    print(f"Starting PDF processing: {pdf_path}")
    
    doc = fitz.open(pdf_path)
    extracted_content = []
    
    for page_idx in range(len(doc)):
        page_start_time = time.time()
        print(f"Processing page {page_idx + 1}/{len(doc)}")
        
        page = doc[page_idx]
        pymupdf_page = PyMuPDFDocument(pdf_path)[page_idx]
        
        # Extract page text
        text_start_time = time.time()
        page_text = page.get_text()
        print(f"  Text extraction time: {time.time() - text_start_time:.2f} seconds")
        
        # Detect tables on the page
        table_detection_start = time.time()
        page_tables = detector.extract(pymupdf_page)
        print(f"  Table detection time: {time.time() - table_detection_start:.2f} seconds")
        print(f"  Found {len(page_tables)} tables on page {page_idx + 1}")
        
        if page_tables:
            # Process each table
            for table_idx, table in enumerate(page_tables):
                table_start_time = time.time()
                # Convert table to pandas DataFrame
                try:
                    formatted_table = formatter.format(table)
                    table_df: pd.DataFrame = formatted_table.df()
                    
                    # Get text before and after the table
                    # Find the approximate location of the table in the text
                    pre_table_text = ""
                    post_table_text = ""
                    
                    # Simple approach: Take text from the start of the page
                    # and split it into pre and post table text
                    text_parts = page_text.split('\n')
                    split_index = len(text_parts) // 2  # Rough midpoint
                    pre_table_text = '\n'.join(text_parts[:split_index])
                    post_table_text = '\n'.join(text_parts[split_index:])
                    
                    # Compile the table content with context
                    table_content = (
                        f"### Context Before Table:\n{pre_table_text}\n\n"
                        f"### Table {table_idx + 1} on Page {page_idx + 1}:\n"
                        f"{convert_table_to_markdown(table_df)}\n\n"
                        f"### Context After Table:\n{post_table_text}"
                    )
                    
                    extracted_content.append(table_content)
                    print(f"  Table {table_idx + 1} processing time: {time.time() - table_start_time:.2f} seconds")
                    
                except Exception as e:
                    print(f"Error processing table on page {page_idx + 1}: {e}")
        
        # If no tables, chunk the text
        if not page_tables:
            chunking_start = time.time()
            text_chunks = chunk_text(page_text, chunk_size, overlap)
            for chunk in text_chunks:
                extracted_content.append(chunk)
            print(f"  Text chunking time: {time.time() - chunking_start:.2f} seconds")
            print(f"  Created {len(text_chunks)} text chunks")
        
        print(f"Page {page_idx + 1} processing time: {time.time() - page_start_time:.2f} seconds")
    
    # Close the document
    doc.close()
    
    total_time = time.time() - start_time
    print(f"Total PDF processing time: {total_time:.2f} seconds")
    
    return extracted_content

def main():
    start_time = time.time()
    
    # Example usage
    pdf_path = "sample_main.pdf"
    extracted_content = process_pdf(pdf_path)
    
    # Write extracted content to a file
    writing_start = time.time()
    with open("extracted_content.md", "w", encoding="utf-8") as f:
        for idx, content in enumerate(extracted_content, 1):
            f.write(f"## Content Block {idx}\n")
            f.write(content)
            f.write("\n\n---\n\n")
    
    print(f"Writing to file time: {time.time() - writing_start:.2f} seconds")
    print(f"Extracted {len(extracted_content)} content blocks")
    print(f"Total execution time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()