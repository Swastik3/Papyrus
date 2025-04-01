import os
import logging
import numpy as np
from dotenv import load_dotenv
import pinecone
from pypdf import PdfReader
import time
import io
import fitz  # PyMuPDF
from openai import OpenAI
import json

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
SIMILARITY_THRESHOLD = 0.0  # Minimum similarity score to consider a chunk relevant

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
    """Extract all text from PDF bytes"""
    try:
        pdf_stream = io.BytesIO(pdf_bytes)
        reader = PdfReader(pdf_stream)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + " "
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise

def extract_text_from_pdf_file(pdf_path: str) -> str:
    """Extract all text from a PDF file using PyMuPDF"""
    try:
        # Open the PDF file directly by path
        pdf_document = fitz.open(pdf_path)
        
        # Extract text from each page
        text = ""
        total_pages = len(pdf_document)
        logger.info(f"Processing PDF with {total_pages} pages")
        
        for page_num in range(total_pages):
            if page_num % 10 == 0:  # Log progress every 10 pages
                logger.info(f"Extracting text from page {page_num+1}/{total_pages}")
            
            page = pdf_document[page_num]
            page_text = page.get_text()
            text += page_text + " "
            
        # Close the document
        pdf_document.close()
        
        logger.info(f"Successfully extracted text from PDF file '{pdf_path}': {len(text)} characters")
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF file '{pdf_path}' with PyMuPDF: {e}")
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
    # Initialize OpenAI client with network-focused configuration
    client = OpenAI(
        api_key=os.getenv('OPENAI_API_KEY'),
        timeout=90.0,  # Longer timeout for network issues
        max_retries=5  # More retries for intermittent issues
    )
    
    # Initialize empty array to store embeddings
    embeddings = []
    chunk_count = len(chunks)
    logger.info(f"Creating embeddings for {chunk_count} chunks using model {model_name}")
    
    for i in range(0, chunk_count, BATCH_SIZE):
        batch = chunks[i:i+BATCH_SIZE]
        batch_size = len(batch)
        batch_num = i//BATCH_SIZE + 1
        total_batches = (chunk_count-1)//BATCH_SIZE + 1
        
        logger.info(f"Processing batch {batch_num}/{total_batches} with {batch_size} chunks")
        
        # Track timing for diagnostics
        start_time = time.time()
        
        try:
            # Make the API call with exponential backoff retry logic
            retry = 0
            max_retries = 5
            retry_delay = 1
            success = False
            
            while retry < max_retries and not success:
                try:
                    response = client.embeddings.create(
                        input=batch,
                        model=model_name
                    )
                    success = True
                except Exception as retry_error:
                    retry += 1
                    if retry < max_retries:
                        logger.warning(f"Connection error on attempt {retry}/{max_retries}: {str(retry_error)}")
                        logger.warning(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        # Last attempt failed, re-raise with more context
                        logger.error(f"All {max_retries} attempts failed")
                        raise Exception(f"Failed to create embeddings after {max_retries} attempts: {str(retry_error)}")
            
            # Extract embeddings from response
            batch_embeddings = [item.embedding for item in response.data]
            embeddings.extend(batch_embeddings)
            
            # Log successful batch completion with timing
            elapsed = time.time() - start_time
            logger.info(f"Batch {batch_num}/{total_batches} completed in {elapsed:.2f}s ({batch_size/elapsed:.1f} chunks/sec)")
            
            # Adaptive rate limiting
            if i + BATCH_SIZE < chunk_count:
                # Calculate adaptive delay based on API response time
                # Faster responses → shorter delay, slower responses → longer delay
                adaptive_delay = min(max(1.0, elapsed * 0.5), 5.0)
                logger.info(f"Waiting {adaptive_delay:.2f}s before next batch")
                time.sleep(adaptive_delay)
                
        except Exception as e:
            logger.error(f"Error creating embeddings for batch {batch_num}/{total_batches}: {str(e)}")
            
            # Try to get a network diagnostic
            try:
                import socket
                can_connect = socket.create_connection(("api.openai.com", 443), timeout=5)
                logger.info(f"Network connectivity test: {'Success' if can_connect else 'Failed'}")
                if can_connect:
                    can_connect.close()
            except Exception as net_error:
                logger.error(f"Network diagnostic failed: {str(net_error)}")
            
            raise
    
    # Convert list of embeddings to numpy array
    embeddings_array = np.array(embeddings)
    logger.info(f"Successfully created embeddings array with shape {embeddings_array.shape}")
    return embeddings_array

def prepare_pinecone_batch(chunks: list, embeddings: np.ndarray, file_id: str, filename: str, 
                          page_numbers: list = None, conversation_id: str = None) -> list:
    """
    Prepare data in the format required for Pinecone batch upsert
    
    Args:
        chunks: List of text chunks
        embeddings: Numpy array of embeddings
        file_id: Unique identifier for the file
        filename: Name of the file
        page_numbers: Optional list of page numbers corresponding to each chunk
        conversation_id: Optional conversation ID to associate with these chunks
    """
    batch_data = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        metadata = {
            'text': chunk,
            'source': filename,
            'chunk_id': i
        }
        
        # Add page number if available
        if page_numbers and i < len(page_numbers):
            metadata['page'] = page_numbers[i]
            
        # Add conversation ID if available
        if conversation_id:
            metadata['conversation_id'] = conversation_id
        
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

def process_pdf_chunk(page_data, file_id, filename, conversation_id=None):
    """
    Process a chunk of PDF pages, create embeddings and upsert to Pinecone
    
    Args:
        page_data: List of dictionaries with 'pageNum' and 'text' keys
        file_id: Unique identifier for the file
        filename: Name of the file
        conversation_id: Optional conversation ID to associate with these chunks
    
    Returns:
        Number of chunks processed
    """
    try:
        # Extract text and page numbers
        page_texts = [page['text'] for page in page_data]
        page_numbers = [page['pageNum'] for page in page_data]
        
        # Combine all texts into one string
        combined_text = ' '.join(page_texts)
        
        # Chunk the text
        chunks = chunk_text(combined_text, CHUNK_SIZE, CHUNK_OVERLAP)
        
        if not chunks:
            logger.warning(f"No text chunks created for {filename} pages {page_numbers}")
            return 0
        
        # Create embeddings
        embeddings = create_embeddings(chunks)
        
        # Map chunks to their approximate page numbers
        # This is a simplified approach that assumes chunks come from sequential pages
        chunk_page_numbers = []
        text_processed = 0
        current_page_idx = 0
        current_page_text = page_texts[current_page_idx]
        current_page_length = len(current_page_text)
        
        for chunk in chunks:
            chunk_length = len(chunk)
            
            # If this chunk would exceed the current page, move to the next page
            while text_processed + chunk_length > current_page_length and current_page_idx < len(page_texts) - 1:
                text_processed = 0
                current_page_idx += 1
                current_page_text = page_texts[current_page_idx]
                current_page_length = len(current_page_text)
            
            # Assign the current page number to this chunk
            chunk_page_numbers.append(page_numbers[current_page_idx])
            
            # Update text processed
            text_processed += chunk_length
        
        # Get or create Pinecone index
        index = create_or_get_index(PINECONE_INDEX_NAME, EMBEDDING_DIMENSION)
        
        # Prepare batch data
        batch_data = prepare_pinecone_batch(
            chunks, 
            embeddings, 
            file_id, 
            filename, 
            chunk_page_numbers,
            conversation_id
        )
        
        # Upsert to Pinecone
        upsert_to_pinecone(index, batch_data)
        
        logger.info(f"Processed {len(chunks)} chunks from {len(page_data)} pages of {filename}")
        return len(chunks)
        
    except Exception as e:
        logger.error(f"Error processing PDF chunk: {str(e)}")
        raise

def search_pinecone(query: str, top_k: int = 10, filters: dict = None) -> list:
    """
    Search Pinecone index for similar chunks
    
    Args:
        query: The search query
        top_k: Number of results to return
        filters: Optional metadata filters (e.g., {'conversation_id': 'abc123'})
        
    Returns:
        List of search results
    """
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
        
        # Prepare query parameters
        query_params = {
            "vector": query_embedding,
            "top_k": top_k,
            "include_metadata": True
        }
        
        # Add filter if provided
        if filters:
            query_params["filter"] = filters
        
        # Search Pinecone using the index's query method
        search_results = index.query(**query_params)
        logger.info(f"Search results: {len(search_results.matches)} matches found")
        
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

def get_relevant_context(user_query: str, threshold: float = SIMILARITY_THRESHOLD, max_results: int = 5, filters: dict = None) -> tuple:
    """
    Performs similarity search for a user query and returns relevant context
    that exceeds the similarity threshold.
    
    Args:
        user_query: The user's question or query
        threshold: Minimum similarity score to include a chunk (0-1)
        max_results: Maximum number of results to return
        filters: Optional metadata filters (e.g., {'conversation_id': 'abc123'})
        
    Returns:
        Tuple of (context_text, sources) where:
            - context_text is the combined text of relevant chunks
            - sources is a list of source filenames for citation
    """
    try:
        # Get search results
        search_results = search_pinecone(user_query, top_k=max_results*2, filters=filters)  # Get more than needed to filter
        logger.info(f"Search results for query '{user_query}': {len(search_results)} results")
        
        # Filter results by threshold
        filtered_results = [result for result in search_results if result['score'] >= threshold]
        
        # Limit to max_results
        filtered_results = filtered_results[:max_results]
        
        if not filtered_results:
            logger.info(f"No relevant context found for query: {user_query}")
            return "", []
        
        # Extract text and sources
        context_chunks = []
        sources = []
        
        for result in filtered_results:
            chunk_text = result['text']
            source = result['source']
            
            # Add page number if available
            if 'page' in result:
                source_with_page = f"{source} (page {result['page']})"
                sources.append(source_with_page)
                context_chunks.append(f"[{source_with_page}]\n{chunk_text}")
            else:
                sources.append(source)
                context_chunks.append(f"[{source}]\n{chunk_text}")
        
        # Get unique sources
        sources = list(set(sources))
        
        # Join context chunks with separator
        context_text = "\n\n---\n\n".join(context_chunks)
        
        logger.info(f"Found {len(filtered_results)} relevant chunks from {len(sources)} sources")
        logger.info(f"Context text: {context_text[:100]}...")  # Log first 100 chars of context
        return context_text, sources
        
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

if __name__ == "__main__":
    # Initialize Pinecone
    initialize_pinecone()
    
    # Example: Test connectivity
    if pc is not None:
        print("Pinecone initialized successfully")
    else:
        print("Failed to initialize Pinecone")