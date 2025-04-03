import threading
import queue
import fitz  # PyMuPDF
import base64
import os
import time
import io
import anthropic
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

def process_image(image_bytes, max_width=800, max_height=800):
    """Process a single image with Claude Vision API"""
    # Encode the image to base64
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    
    # Create Anthropic client
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    start_time = time.time()
    print("Initializing the OCR request")
    
    try:
        response = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract all text from this image, preserving its structure. Include all text content while maintaining paragraphs, headings, lists, and table structures if present."
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64_image
                            }
                        }
                    ]
                }
            ]
        )
        
        end_time = time.time()
        print(f"OCR Request Time: {end_time - start_time:.2f} seconds")
        
        # Extract and return the text content
        return response.content[0].text
    except Exception as e:
        print(f"Error in OCR request: {e}")
        return None

def worker(page_queue, results, file_id, filename, conversation_id, chunk_and_index_func=None, progress_callback=None):
    """Worker thread to process pages from the queue"""
    while not page_queue.empty():
        try:
            page_num, page_image = page_queue.get(block=False)
            
            # Update progress if callback is provided
            if progress_callback:
                progress_callback(f"Processing page {page_num+1}")
            
            print(f"Processing page {page_num+1}")
            
            # Perform OCR on the page
            ocr_text = process_image(page_image)
            results[page_num] = ocr_text
            
            # If we have text and a function to chunk and index, use it
            if ocr_text and chunk_and_index_func:
                page_data = {
                    'pageNum': page_num + 1,  # 1-indexed for user-friendliness
                    'text': ocr_text
                }
                # Chunk and index this page
                chunk_and_index_func([page_data], file_id, filename, conversation_id)
            
            # Update progress again after page is complete
            if progress_callback:
                progress_callback(f"Completed page {page_num+1}")
                
            page_queue.task_done()
        except queue.Empty:
            break
        except Exception as e:
            print(f"Error processing page: {e}")
            if progress_callback:
                progress_callback(f"Error on page {page_num+1}: {str(e)}")
            page_queue.task_done()

def process_pdf_with_threads(pdf_bytes, file_id, filename, conversation_id, 
                             chunk_and_index_func, max_workers=4, progress_callback=None):
    """Process a PDF document with multiple threads for OCR and index chunks to Pinecone"""
    start_time = time.time()
    
    # Create a BytesIO object to read the PDF
    pdf_stream = io.BytesIO(pdf_bytes)
    
    # Open the PDF
    doc = fitz.open(stream=pdf_stream, filetype="pdf")
    page_count = len(doc)
    
    # Update progress
    if progress_callback:
        progress_callback(f"PDF has {page_count} pages to process")
    
    # Create a queue for pages and a dict for results
    page_queue = queue.Queue()
    results = {}
    
    # Add pages to the queue
    for page_idx in range(page_count):
        page = doc[page_idx]
        pix = page.get_pixmap()
        img_data = pix.tobytes("png")
        page_queue.put((page_idx, img_data))
    
    # Create and start worker threads
    threads = []
    for _ in range(min(max_workers, page_count)):
        thread = threading.Thread(
            target=worker, 
            args=(page_queue, results, file_id, filename, conversation_id, chunk_and_index_func, progress_callback)
        )
        thread.start()
        threads.append(thread)
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # Close the document
    doc.close()
    
    # Collect results in order
    ordered_results = [results.get(i, "") for i in range(page_count)]
    combined_text = "\n\n--- Page Break ---\n\n".join(ordered_results)
    
    end_time = time.time()
    processing_time = end_time - start_time
    print(f"Total processing time: {processing_time:.2f} seconds")
    
    # Final progress update
    if progress_callback:
        progress_callback(f"Completed OCR of all {page_count} pages in {processing_time:.1f} seconds")
    
    return combined_text

def process_pdfs_with_ocr(files, chunk_and_index_func, conversation_id, max_workers=4, progress_callback=None):
    """
    Process a list of PDF files with OCR and index to Pinecone
    
    Args:
        files: List of (filename, file_bytes, file_id) tuples
        chunk_and_index_func: Function to chunk and index text to Pinecone
        conversation_id: ID of the conversation
        max_workers: Maximum number of threads to use for PDF processing
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict mapping filenames to extracted text
    """
    results = {}
    
    for filename, file_bytes, file_id in files:
        try:
            if filename.lower().endswith('.pdf'):
                # Process PDF with multithreading
                if progress_callback:
                    progress_callback(f"Starting OCR for {filename}")
                
                print(f"Processing PDF with OCR: {filename}")
                
                # Define a wrapper progress callback that includes the filename
                def file_progress_callback(message):
                    if progress_callback:
                        progress_callback(f"{filename}: {message}")
                
                extracted_text = process_pdf_with_threads(
                    file_bytes, 
                    file_id, 
                    filename, 
                    conversation_id,
                    chunk_and_index_func, 
                    max_workers=max_workers,
                    progress_callback=file_progress_callback
                )
                
                if extracted_text:
                    results[filename] = extracted_text
                    if progress_callback:
                        progress_callback(f"Successfully processed {filename}")
                else:
                    results[filename] = "OCR processing failed. No text extracted."
                    if progress_callback:
                        progress_callback(f"Failed to extract text from {filename}")
            else:
                # Skip non-PDF files
                print(f"Skipping non-PDF file: {filename}")
                results[filename] = "Skipped. Only PDF files are supported for OCR."
                if progress_callback:
                    progress_callback(f"Skipped non-PDF file: {filename}")
                
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            results[filename] = f"Error processing file: {str(e)}"
            if progress_callback:
                progress_callback(f"Error processing {filename}: {str(e)}")
    
    return results