#rag_utils.py
import os
import logging
import numpy as np
from dotenv import load_dotenv
import pinecone
from pypdf import PdfReader
import time
import io
from openai import OpenAI
import json
import fitz  # PyMuPDF
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants for RAG configuration
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
PINECONE_ENVIRONMENT = os.getenv('PINECONE_ENVIRONMENT', 'gcp-starter')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'pdf-embeddings')
EMBEDDING_DIMENSION = 1536  # For OpenAI's text-embedding-3-small
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BATCH_SIZE = 100
SIMILARITY_THRESHOLD = -1.00  # Minimum similarity score to consider a chunk relevant

# Global Pinecone client
pc = None 

def initialize_pinecone() -> pinecone.Pinecone:
    """Initialize Pinecone with API key from environment variables"""
    global pc
    if pc is not None:
        return pc
        
    api_key = PINECONE_API_KEY
    
    if not api_key:
        raise ValueError("PINECONE_API_KEY must be set in environment variables or .env file")
    
    try:
        pc = pinecone.Pinecone(api_key=api_key)
        logger.info("Pinecone initialized successfully")
        return pc
    except Exception as e:
        logger.error(f"Error initializing Pinecone: {e}")
        raise

def create_or_get_index(index_name: str, dimension: int):
    """Create a new Pinecone index or get an existing one"""
    try:
        # Initialize Pinecone if not already initialized
        global pc
        if pc is None:
            pc = initialize_pinecone()
            
        # Check if index exists
        indices = pc.list_indexes()
        index_names = [index.name for index in indices]
        
        if index_name not in index_names:
            logger.info(f"Creating new Pinecone index: {index_name}")
            pc.create_index(
                name=index_name,
                dimension=dimension,
                metric="cosine"
            )
            # Wait a bit for the index to be ready
            time.sleep(2)
            
        # Get the index
        index = pc.Index(index_name)
        logger.info(f"Successfully connected to index: {index_name}")
        return index
        
    except Exception as e:
        logger.error(f"Error creating/getting Pinecone index: {e}")
        raise

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using PyMuPDF"""
    try:
        # Create a document object from the bytes
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Extract text from each page
        text = ""
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            text += page.get_text() + " "
            
        # Close the document
        pdf_document.close()
        
        logger.info(f"Successfully extracted text from PDF: {len(text)} characters")
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF with PyMuPDF: {e}")
        raise

def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list:
    """Split text into overlapping chunks of specified size"""
    logger.info(f"Starting text chunking: text length={len(text)}, chunk_size={chunk_size}, overlap={chunk_overlap}")
    
    if not text:
        logger.warning("Empty text provided for chunking, returning empty list")
        return []
    
    chunks = []
    start = 0
    text_length = len(text)
    chunk_count = 0
    start_time = time.time()
    
    logger.info(f"Beginning chunking loop for {text_length} characters")
    while start < text_length:
        # Log progress every 10 chunks
        if chunk_count % 10 == 0:
            progress_pct = (start / text_length) * 100
            elapsed = time.time() - start_time
            logger.info(f"Chunking progress: {progress_pct:.1f}% ({start}/{text_length} chars, {chunk_count} chunks, {elapsed:.2f}s elapsed)")
        
        end = min(start + chunk_size, text_length)
        
        # Ensure we're not cutting off in the middle of a word if not at the end
        if end < text_length:
            # Find the next space after the chunk size
            next_space = text.find(' ', end)
            if next_space != -1 and next_space - end < 50:  # Limit how far we search
                logger.debug(f"Extending chunk from {end} to next space at {next_space}")
                end = next_space + 1  # Include the space
            else:
                logger.debug(f"No suitable space found after position {end}, using character boundary")
        
        # Add the chunk
        chunk = text[start:end].strip()
        chunks.append(chunk)
        chunk_count += 1
        
        logger.debug(f"Created chunk {chunk_count}: start={start}, end={end}, length={len(chunk)}")
        
        # Move the start position for the next chunk, considering overlap
        old_start = start
        start = end - chunk_overlap
        
        # Safety check - if we're not making progress
        if start <= old_start:
            logger.warning(f"Chunking not making progress: old_start={old_start}, new_start={start}. Forcing advancement.")
            start = end + 1
            if start >= text_length:
                logger.info("Reached end of text after forcing advancement")
                break
    
    processing_time = time.time() - start_time
    avg_chunk_size = sum(len(chunk) for chunk in chunks) / max(1, len(chunks))
    
    logger.info(f"Chunking completed: created {len(chunks)} chunks in {processing_time:.2f}s")
    logger.info(f"Chunk statistics: avg_size={avg_chunk_size:.1f} chars, total_chars={sum(len(c) for c in chunks)}")
    
    return chunks

def create_embeddings(chunks: list, model_name: str = 'text-embedding-3-small') -> np.ndarray:
    """Create embeddings for each text chunk using OpenAI's embedding model"""
    # Initialize OpenAI client
    logger.info(f"The API_KEY is {os.getenv('OPENAI_API_KEY')}")
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    try:
        test = requests.get('https://api.openai.com/v1/engines', 
                            timeout=5, 
                            headers={'Authorization': f'Bearer {os.getenv("OPENAI_API_KEY")}'})
        logger.info(f"Connectivity test: {test.status_code}")
    except Exception as conn_err:
        logger.error(f"Connectivity test failed: {str(conn_err)}")
    # Initialize empty array to store embeddings
    embeddings = []
    logger.info(f"First few chunks for debugging: {chunks[:5]}")
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i+BATCH_SIZE]
        try:
            response = client.embeddings.create(
                input=batch,
                model=model_name
            )
            # logger.error(f"Embeddings reposnse: {response}")
            # Extract embeddings from response
            batch_embeddings = [item.embedding for item in response.data]
            embeddings.extend(batch_embeddings)
            
            # Sleep to respect rate limits if not the last batch
            if i + BATCH_SIZE < len(chunks):
                time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error creating embeddings for batch starting at index {i}: {e}")
            raise
    
    # Convert list of embeddings to numpy array
    return np.array(embeddings)

def prepare_pinecone_batch(chunks: list, embeddings: np.ndarray, file_id: str, filename: str, 
                        conversation_id:str, page_numbers: list = None) -> list:
    """
    Prepare data in the format required for Pinecone batch upsert
    
    Args:
        chunks: List of text chunks
        embeddings: Numpy array of embeddings
        file_id: Unique identifier for the file
        filename: Name of the file
        page_numbers: Optional list of page numbers corresponding to each chunk
    """
    batch_data = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        if conversation_id:
            logger.info(f"conversation_id received for batching is: {conversation_id}")
            metadata = {
                'text': chunk,
                'conversation_id': conversation_id,
                'source': filename,
                'chunk_id': i
            }
        else:
            metadata = {
                'text': chunk,
                'source': filename,
                'chunk_id': i
            }
        
        # Add page number to metadata if available
        if page_numbers and i < len(page_numbers):
            metadata['page'] = page_numbers[i]
        
        batch_data.append({
            'id': f"{file_id}_chunk_{i}",
            'values': embedding.tolist(),
            'metadata': metadata
        })
    return batch_data

def upsert_to_pinecone(index, batch_data: list, batch_size: int = 100) -> None:
    """Upsert data to Pinecone in batches"""
    if not batch_data:
        logger.warning("No batch data provided for upserting")
        return
        
    try:
        for i in range(0, len(batch_data), batch_size):
            batch = batch_data[i:i+batch_size]
            
            # Debug information
            logger.info(f"Upserting batch {i//batch_size + 1}/{(len(batch_data)-1)//batch_size + 1} with {len(batch)} vectors")
            
            # Explicitly create the vectors in the format Pinecone expects
            vectors = [{
                'id': item['id'],
                'values': item['values'],
                'metadata': item['metadata']
            } for item in batch]
            
            # Perform the upsert operation
            upsert_response = index.upsert(vectors=vectors)
            
            # Log the response for debugging
            logger.info(f"Upsert response: {upsert_response}")
            
            # Sleep to avoid rate limits if not the last batch
            if i + batch_size < len(batch_data):
                time.sleep(0.5)
                
    except Exception as e:
        logger.error(f"Error in upsert_to_pinecone: {str(e)}")
        raise

def process_pdf_chunk(page_data, file_id, filename, conversation_id):
    """
    Process a chunk of PDF pages, create embeddings and upsert to Pinecone
    
    Args:
        page_data: List of dictionaries with 'pageNum' and 'text' keys
        file_id: Unique identifier for the file
        filename: Name of the file
        conversation_id: ID of the conversation
    
    Returns:
        Number of chunks processed
    """
    try:
        # Extract text and page numbers
        page_texts = [page['text'] for page in page_data]
        page_numbers = [page['pageNum'] for page in page_data]
        
        # Combine all texts into one string with page markers
        combined_text = ' '.join(page_texts)
        
        # Chunk the text
        chunks = chunk_text(combined_text, CHUNK_SIZE, CHUNK_OVERLAP)
        
        if not chunks:
            logger.warning(f"No text chunks created for {filename} pages {page_numbers}")
            return 0
        
        # Create embeddings
        embeddings = create_embeddings(chunks)
        
        # Map chunks to their approximate page numbers based on starting position
        chunk_page_numbers = []
        
        # Calculate cumulative text lengths for page boundary detection
        cumulative_lengths = [0]  # Start with 0
        current_length = 0
        for text in page_texts:
            current_length += len(text)
            cumulative_lengths.append(current_length)
        
        # For each chunk, determine which page it starts on
        for chunk in chunks:
            # Calculate where this chunk starts in the combined text
            chunk_start_pos = combined_text.find(chunk[:50])  # Use first 50 chars to find reliable match
            
            # If match not found, use a different approach
            if chunk_start_pos == -1:
                logger.warning(f"Could not find exact chunk position. Using approximate mapping.")
                # Just place in middle if we can't find it
                chunk_start_pos = current_length // 2
            
            # Find which page this position corresponds to
            page_idx = 0
            while page_idx < len(cumulative_lengths) - 1 and chunk_start_pos >= cumulative_lengths[page_idx + 1]:
                page_idx += 1
                
            # Assign the page number
            if page_idx < len(page_numbers):
                chunk_page_numbers.append(page_numbers[page_idx])
            else:
                # Fallback to last page if something went wrong
                chunk_page_numbers.append(page_numbers[-1])
                logger.warning(f"Page mapping issue - assigned to last page")
                
        # Get or create Pinecone index
        index = create_or_get_index(PINECONE_INDEX_NAME, EMBEDDING_DIMENSION)
        
        # Prepare batch data
        batch_data = prepare_pinecone_batch(chunks, embeddings, file_id, filename, 
                                           conversation_id=conversation_id,
                                           page_numbers=chunk_page_numbers)
        
        # Upsert to Pinecone
        upsert_to_pinecone(index, batch_data)
        
        logger.info(f"Processed {len(chunks)} chunks from {len(page_data)} pages of {filename}")
        return len(chunks)
        
    except Exception as e:
        logger.error(f"Error processing PDF chunk: {str(e)}")
        raise

def search_pinecone(query: str, conversation_id: str = None, top_k: int = 10) -> list:
    """Search Pinecone index for similar chunks"""
    try:
        # Initialize Pinecone if not already initialized
        global pc
        if pc is None:
            pc = initialize_pinecone()
        
        # Get index
        index = create_or_get_index(PINECONE_INDEX_NAME, EMBEDDING_DIMENSION)
        
        # Get embeddings for query
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        response = client.embeddings.create(
            input=[query],
            model='text-embedding-3-small'
        )
        query_embedding = response.data[0].embedding
        
        # Search Pinecone using the index's query method
        search_results = None
        if conversation_id:
            search_results = index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True,
                filter={
                    'conversation_id': conversation_id
                }
            )
        else:
            search_results = index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True
            )
            
        logger.info(f"Search results: {len(search_results.matches)} matches found")
        # logger.debug(f"Search results: {json.dumps(search_results.matches, indent=2)}")
        # Format results
        results = []
        for match in search_results.matches:
            result = {
                'score': match.score,
                'text': match.metadata.get('text', ''),
                'source': match.metadata.get('source', ''),
                'chunk_id': match.metadata.get('chunk_id', -1)
            }
            
            # Add page number if available
            if 'page' in match.metadata:
                result['page'] = match.metadata['page']
                
            results.append(result)
            
        return results
        
    except Exception as e:
        logger.error(f"Error searching Pinecone: {e}")
        raise

def get_relevant_context(user_query: str, conversation_id:str, threshold: float = SIMILARITY_THRESHOLD, max_results: int = 5) -> tuple:
    """
    Performs similarity search for a user query and returns relevant context
    that exceeds the similarity threshold.
    
    Args:
        user_query: The user's question or query
        threshold: Minimum similarity score to include a chunk (0-1)
        max_results: Maximum number of results to return
        
    Returns:
        Tuple of (context_text, sources) where:
            - context_text is the combined text of relevant chunks
            - sources is a list of source filenames for citation
    """
    try:
        # Get search results
        search_results = search_pinecone(user_query, top_k=max_results*2, conversation_id=conversation_id)  # Get more than needed to filter
        logger.info(f"Search results for query '{user_query}': {len(search_results)} results")
        # Filter results by threshold
        filtered_results = [result for result in search_results if result['score'] >= threshold]
        
        # Limit to max_results
        filtered_results = filtered_results[:max_results*2]
        
        if not filtered_results:
            logger.info(f"No relevant context found for query: {user_query} for conversation_id: {conversation_id}")
            return "", []
        
        # Extract text and sources
        context_chunks = []
        sources = [] #dict with source and page number
        
        for result in filtered_results:
            chunk_text = result['text']
            source = result['source']
            
            # Create a dictionary with text and source information
            chunk_dict = {
                "text": chunk_text,
                "source": source
            }
            
            # Add page number if available
            if 'page' in result:
                source_with_page = f"{source} (page {result['page']})"
                sources.append(source_with_page)
                chunk_dict["page"] = result['page']
            else:
                sources.append(source)
            
            # Append the dictionary to context_chunks
            context_chunks.append(chunk_dict)
        
        # Get unique sources
        sources = list(set(sources)) #will be empty now
        
        # Join context chunks with separator
        # context_text = "\n\n---\n\n".join(context_chunks)
        
        # logger.info(f"Found {len(filtered_results)} relevant chunks from {len(sources)} sources")
        # logger.info(f"Context text: {context_text[:100]}...")  # Log first 100 chars of context
        return context_chunks, sources
        
    except Exception as e:
        logger.error(f"Error getting relevant context: {e}")
        raise

def delete_all_embeddings_from_index(index_name: str = PINECONE_INDEX_NAME):
    """
    Delete all embeddings/vectors from the specified Pinecone index.
    
    Args:
        index_name: Name of the Pinecone index to clear
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Attempting to delete all vectors from index '{index_name}'")
        start_time = time.time()
        
        # Initialize Pinecone if not already initialized
        global pc
        if pc is None:
            pc = initialize_pinecone()
            logger.info("Initialized Pinecone client")
        
        # Check if index exists
        indices = pc.list_indexes()
        index_names = [index.name for index in indices]
        
        if index_name not in index_names:
            logger.warning(f"Index '{index_name}' does not exist, nothing to delete")
            return False
        
        # Get the index
        index = pc.Index(index_name)
        logger.info(f"Connected to index '{index_name}'")
        
        # Get stats to see how many vectors we're deleting
        try:
            stats = index.describe_index_stats()
            total_vectors = stats.total_vector_count
            logger.info(f"Index contains {total_vectors} vectors before deletion")
        except Exception as e:
            logger.warning(f"Could not get index stats: {e}")
            total_vectors = "unknown number of"
        
        # Delete all vectors
        logger.info(f"Deleting all vectors from index '{index_name}'...")
        
        # Use the delete_all method if available in your Pinecone version
        try:
            # Method 1: Try using delete_all (newer Pinecone versions)
            index.delete(delete_all=True)
            logger.info(f"Successfully deleted all vectors using delete_all")
        except (AttributeError, TypeError) as e:
            logger.info(f"delete_all not available, using alternative approach: {e}")
        
        # Verify deletion
        try:
            stats_after = index.describe_index_stats()
            remaining_vectors = stats_after.total_vector_count
            logger.info(f"Index contains {remaining_vectors} vectors after deletion")
            
            if remaining_vectors == 0:
                logger.info(f"Successfully deleted all vectors from index '{index_name}'")
            else:
                logger.warning(f"Some vectors ({remaining_vectors}) still remain in the index")
        except Exception as e:
            logger.warning(f"Could not verify deletion: {e}")
        
        elapsed_time = time.time() - start_time
        logger.info(f"Deletion operation completed in {elapsed_time:.2f} seconds")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting vectors from index: {e}")
        return False



def process_smart_content(content_data, file_id, filename, conversation_id):
    """
    Process content data using smart chunking strategy
    
    Args:
        content_data: List of dictionaries with 'pageNum', 'text', and 'is_table' keys
        file_id: Unique identifier for the file
        filename: Name of the file
        conversation_id: ID of the conversation
    
    Returns:
        Number of chunks processed
    """
    try:
        # Separate table content and text content
        table_content = [item for item in content_data if item.get('is_table', False)]
        text_content = [item for item in content_data if not item.get('is_table', False)]
        
        # Process table content first (tables are already their own chunks)
        table_chunks = [item['text'] for item in table_content]
        table_page_numbers = [item['pageNum'] for item in table_content]
        
        # Process text content with standard chunking
        text_pages = []
        page_numbers = []
        
        for item in text_content:
            text_pages.append(item['text'])
            page_numbers.append(item['pageNum'])
        
        # Combine all text into one string
        combined_text = ' '.join(text_pages)
        
        # Chunk the text
        text_chunks = chunk_text(combined_text, CHUNK_SIZE, CHUNK_OVERLAP)
        
        # Combine table chunks and text chunks
        all_chunks = table_chunks + text_chunks
        
        # If no chunks were created, return 0
        if not all_chunks:
            logger.warning(f"No chunks created for {filename}")
            return 0
        
        # Create embeddings
        embeddings = create_embeddings(all_chunks)
        
        # Map table chunks directly to their page numbers
        chunk_page_numbers = []
        
        # Add table page numbers first
        chunk_page_numbers.extend(table_page_numbers)
        
        # Calculate cumulative text lengths for page boundary detection
        if text_pages:
            cumulative_lengths = [0]  # Start with 0
            current_length = 0
            for text in text_pages:
                current_length += len(text)
                cumulative_lengths.append(current_length)
            
            # For each text chunk, determine which page it starts on
            for chunk in text_chunks:
                # Calculate where this chunk starts in the combined text
                chunk_start_pos = combined_text.find(chunk[:50])  # Use first 50 chars for reliable match
                
                # If match not found, use a different approach
                if chunk_start_pos == -1:
                    logger.warning(f"Could not find exact chunk position. Using approximate mapping.")
                    # Just place in middle if we can't find it
                    chunk_start_pos = current_length // 2
                
                # Find which page this position corresponds to
                page_idx = 0
                while page_idx < len(cumulative_lengths) - 1 and chunk_start_pos >= cumulative_lengths[page_idx + 1]:
                    page_idx += 1
                    
                # Assign the page number
                if page_idx < len(page_numbers):
                    chunk_page_numbers.append(page_numbers[page_idx])
                else:
                    # Fallback to last page if something went wrong
                    chunk_page_numbers.append(page_numbers[-1])
                    logger.warning(f"Page mapping issue - assigned to last page")
        
        # Get or create Pinecone index
        index = create_or_get_index(PINECONE_INDEX_NAME, EMBEDDING_DIMENSION)
        
        # Prepare batch data
        batch_data = prepare_pinecone_batch(all_chunks, embeddings, file_id, filename, 
                                           conversation_id=conversation_id,
                                           page_numbers=chunk_page_numbers)
        
        upsert_to_pinecone(index, batch_data)
        
        logger.info(f"Processed {len(all_chunks)} chunks ({len(table_chunks)} table chunks, {len(text_chunks)} text chunks) from {filename}")
        return len(all_chunks)
        
    except Exception as e:
        logger.error(f"Error in process_smart_content: {str(e)}")
        raise

if __name__ == "__main__":
    # Initialize Pinecone
    initialize_pinecone()
    delete_all_embeddings_from_index()
    # for testing
    # if pc is not None:
        # try:
        #     # List the indices to verify connection
        #     indices = pc.list_indexes()
        #     index_names = [index.name for index in indices]
        #     print(f"Pinecone indices: {index_names}")
            
        #     # Test with a sample PDF
        #     sample_pdf_path = "sample.pdf"
            
        #     if os.path.exists(sample_pdf_path):
        #         print(f"\nTesting with {sample_pdf_path}...")
                
        #         # Read the PDF file
        #         with open(sample_pdf_path, "rb") as f:
        #             pdf_bytes = f.read()
                
        #         # Create a unique file ID
        #         file_id = f"test_{int(time.time())}"
                
        #         # Extract text from the PDF
        #         print("Extracting text from PDF...")
        #         text = extract_text_from_pdf_bytes(pdf_bytes=pdf_bytes)
        #         print(f"Extracted {len(text)} characters of text")
                
        #         # Create chunks
        #         print("Creating text chunks...")
        #         chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        #         print(f"Created {len(chunks)} chunks")
                
        #         # Create embeddings
        #         print("Creating embeddings...")
        #         embeddings = create_embeddings(chunks)
        #         print(f"Created {len(embeddings)} embeddings")
                
        #         # Prepare batch data for Pinecone
        #         print("Preparing batch data for Pinecone...")
        #         batch_data = prepare_pinecone_batch(chunks, embeddings, file_id, sample_pdf_path)
                
        #         # Get or create Pinecone index
        #         print("Getting Pinecone index...")
        #         index = create_or_get_index(PINECONE_INDEX_NAME, EMBEDDING_DIMENSION)
                
        #         # Upsert to Pinecone
        #         print("Upserting data to Pinecone...")
        #         upsert_to_pinecone(index, batch_data)
                
        #         time.sleep(8)
        #         # Test query
        #         test_query = "what is the document about?"
        #         print(f"\nTesting query: '{test_query}'")

        #         # Get results
        #         print("Generating answer with context...")
        #         result = generate_answer_with_context(test_query)
                
        #         # Display the result
        #         print("\n--- RESULT ---")
        #         print(f"Answer: {result['answer']}")
        #         print(f"Sources: {result['sources']}")
        #         print(f"Has context: {result['has_context']}")
                
        #     else:
        #         print(f"Error: {sample_pdf_path} not found. Please place a sample PDF file in the same directory.")
                
        # except Exception as e:
        #     print(f"Error during testing: {e}")
    # else:
    #     print("Pinecone client is not initialized")