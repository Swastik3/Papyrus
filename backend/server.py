from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import os
import base64
import uuid
import time
import threading
import logging
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
load_dotenv()

# Import RAG utilities
from rag_utils import (
    initialize_pinecone, 
    create_or_get_index,
    process_pdf_chunk,
    search_pinecone,
    get_relevant_context,
    generate_answer_with_context,
    PINECONE_INDEX_NAME,
    EMBEDDING_DIMENSION
)

# import the RAG bot
from rag_langchain import  generate_answer_with_langchain

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25, async_mode='eventlet')

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Store active uploads and processing status
active_uploads = {}

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'})

@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info(f"Client disconnected: {request.sid}")
    # Clean up any incomplete uploads for this client
    for upload_id, data in list(active_uploads.items()):
        if data.get('sid') == request.sid:
            cleanup_upload(upload_id)

def cleanup_upload(upload_id):
    """Clean up resources for an incomplete upload"""
    if upload_id in active_uploads:
        del active_uploads[upload_id]
    logger.info(f"Cleaned up upload: {upload_id}")

def process_pdf_chunk_thread(upload_id, file_id, filename, chunk_data):
    """Process a PDF chunk in a separate thread"""
    try:
        # Get upload info
        upload_info = active_uploads.get(upload_id)
        if not upload_info:
            logger.warning(f"Upload {upload_id} not found")
            return
            
        sid = upload_info.get('sid')
        if not sid:
            logger.warning(f"Session ID not found for upload {upload_id}")
            return
        
        # Extract chunk details
        start_page = chunk_data.get('startPage', 0)
        end_page = chunk_data.get('endPage', 0)
        total_pages = chunk_data.get('totalPages', 0)
        page_data = chunk_data.get('pageData', [])
        
        # Update status to processing this chunk
        socketio.emit('upload_progress', {
            'id': upload_id,
            'fileId': file_id,
            'fileName': filename,
            'progress': int((start_page / total_pages) * 100),
            'status': 'uploading',
            'message': f'Processing pages {start_page}-{end_page}...',
            'processedPages': start_page - 1,
            'totalPages': total_pages
        }, room=sid)
        
        # Process the PDF chunk
        chunks_processed = process_pdf_chunk(page_data, file_id, filename)
        
        # Update processed pages count
        processed_pages = end_page
        upload_info['processed_pages'] = processed_pages
        
        # Calculate overall progress
        progress = min(int((processed_pages / total_pages) * 100), 99)
        
        # Update status
        socketio.emit('upload_progress', {
            'id': upload_id,
            'fileId': file_id,
            'fileName': filename,
            'progress': progress,
            'status': 'uploading',
            'message': f'Processed {chunks_processed} chunks from pages {start_page}-{end_page}',
            'processedPages': processed_pages,
            'totalPages': total_pages
        }, room=sid)
        
        # Check if all pages have been processed
        if processed_pages >= total_pages:
            # Mark as completed
            upload_info['completed'] = True
            
            # Final update
            socketio.emit('upload_progress', {
                'id': upload_id,
                'fileId': file_id,
                'fileName': filename,
                'progress': 100,
                'status': 'completed',
                'message': f'PDF processed and indexed successfully',
                'processedPages': total_pages,
                'totalPages': total_pages
            }, room=sid)
            
            logger.info(f"Completed processing PDF {filename}")
        
    except Exception as e:
        logger.error(f"Error processing PDF chunk: {str(e)}")
        socketio.emit('upload_progress', {
            'id': upload_id,
            'fileId': file_id,
            'fileName': filename,
            'progress': 0,
            'status': 'error',
            'error': f'Error processing PDF chunk: {str(e)}'
        }, room=sid)

@socketio.on('upload_pdf_chunk')
def handle_pdf_chunk(data):
    """Handle PDF chunk upload via WebSocket"""
    try:
        upload_id = data.get('uploadId')
        file_id = data.get('fileId')
        filename = data.get('fileName', 'unnamed.pdf')
        chunk_id = data.get('chunkId')
        start_page = data.get('startPage', 0)
        end_page = data.get('endPage', 0)
        total_pages = data.get('totalPages', 0)
        page_data = data.get('pageData', [])
        
        if not upload_id or not file_id or not page_data:
            emit('upload_progress', {
                'id': upload_id or 'unknown',
                'fileName': filename,
                'progress': 0,
                'status': 'error',
                'error': 'Missing required data for chunk processing'
            })
            return
        
        # Initialize upload info if this is the first chunk
        if upload_id not in active_uploads:
            active_uploads[upload_id] = {
                'filename': filename,
                'file_id': file_id,
                'start_time': time.time(),
                'sid': request.sid,
                'completed': False,
                'total_pages': total_pages,
                'processed_pages': 0
            }
            
            # Save a placeholder file
            unique_filename = f"{file_id}_{secure_filename(filename)}"
            file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            
            with open(file_path, 'w') as f:
                f.write(f"PDF being processed: {filename}")
        
        # Process the PDF chunk in a background thread
        # thread = threading.Thread(
        #     target=process_pdf_chunk_thread,
        #     args=(upload_id, file_id, filename, data)
        # )
        # thread.daemon = True
        # thread.start()
        
        # this implements threading such that the task can also emit events
        socketio.start_background_task(
        process_pdf_chunk_thread,
        upload_id, file_id, filename, data
        )
        # process_pdf_chunk_thread(upload_id, file_id, filename, data)
        
        # Acknowledge receipt of chunk
        emit('chunk_received', {
            'uploadId': upload_id,
            'chunkId': chunk_id,
            'startPage': start_page,
            'endPage': end_page
        })
        
    except Exception as e:
        logger.error(f"Error in handle_pdf_chunk: {str(e)}")
        emit('upload_progress', {
            'id': upload_id if 'upload_id' in locals() else 'unknown',
            'fileName': filename if 'filename' in locals() else 'unknown',
            'progress': 0,
            'status': 'error',
            'error': str(e)
        })

# @socketio.on('upload_pdf')
# def handle_pdf_upload(data):
#     """Handle full PDF upload via WebSocket (legacy method)"""
#     try:
#         upload_id = data.get('uploadId')
#         file_data = data.get('fileData')
#         filename = data.get('fileName', 'unnamed.pdf')
        
#         if not upload_id or not file_data:
#             emit('upload_progress', {
#                 'id': upload_id or 'unknown',
#                 'fileName': filename,
#                 'progress': 0,
#                 'status': 'error',
#                 'error': 'Missing upload ID or file data'
#             })
#             return
        
#         # Decode base64 data (remove header if present)
#         if ',' in file_data and ';base64,' in file_data:
#             file_data = file_data.split(';base64,', 1)[1]
        
#         # Decode the base64 data
#         file_bytes = base64.b64decode(file_data)
        
#         # Generate a unique filename
#         file_id = str(uuid.uuid4())
#         secure_name = secure_filename(filename)
#         unique_filename = f"{file_id}_{secure_name}"
#         file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
#         # Save file to disk
#         with open(file_path, 'wb') as f:
#             f.write(file_bytes)
            
#         # Create initial status
#         active_uploads[upload_id] = {
#             'filename': filename,
#             'file_id': file_id,
#             'start_time': time.time(),
#             'sid': request.sid,
#             'file_path': file_path,
#             'completed': False
#         }
        
#         # Acknowledge receipt
#         emit('upload_started', {
#             'id': upload_id,
#             'fileName': filename,
#             'fileId': file_id
#         })
        
#         # Send warning that this method is deprecated
#         emit('upload_progress', {
#             'id': upload_id,
#             'fileId': file_id,
#             'fileName': filename,
#             'progress': 10,
#             'status': 'uploading',
#             'message': 'Using legacy upload method. Consider switching to chunked uploads for better performance.'
#         })
        
#     except Exception as e:
#         logger.error(f"Error in handle_pdf_upload: {str(e)}")
#         emit('upload_progress', {
#             'id': upload_id if 'upload_id' in locals() else 'unknown',
#             'fileName': filename if 'filename' in locals() else 'unknown',
#             'progress': 0,
#             'status': 'error',
#             'error': str(e)
#         })

@app.route('/api/pdfs', methods=['GET'])
def list_pdfs():
    """List all uploaded PDFs"""
    pdfs = []
    for filename in os.listdir(UPLOAD_FOLDER):
        if filename.endswith('.pdf'):
            file_id = filename.split('_')[0]
            original_name = '_'.join(filename.split('_')[1:])
            pdfs.append({
                'id': file_id,
                'name': original_name,
                'path': f"/api/pdfs/{file_id}"
            })
    return jsonify(pdfs)

@app.route('/api/pdfs/<file_id>', methods=['GET'])
def get_pdf(file_id):
    """Get a specific PDF by ID"""
    for filename in os.listdir(UPLOAD_FOLDER):
        if filename.startswith(f"{file_id}_") and filename.endswith('.pdf'):
            return send_from_directory(UPLOAD_FOLDER, filename)
    return jsonify({'error': 'PDF not found'}), 404

@app.route('/api/search', methods=['POST'])
def search_pdf_content():
    """Search for content in indexed PDFs"""
    try:
        data = request.json
        query = data.get('query')
        
        if not query:
            return jsonify({'error': 'No query provided'}), 400
            
        # Search using the RAG utility
        results = search_pinecone(query, top_k=5)
        
        return jsonify({
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error searching PDF content: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/query', methods=['POST'])
def query_pdf_content():
    """
    Query the system with a natural language question and get an answer
    generated based on the indexed PDF content
    """
    try:
        data = request.json
        query = data.get('query')
        model = data.get('model', 'gpt-4o-mini')
        
        if not query:
            return jsonify({'error': 'No query provided'}), 400
        
        logger.info(f"Processing query: {query}")
        
        # Generate answer with context
        start_time = time.time()
        result = generate_answer_with_langchain(query, model=model)
        elapsed_time = time.time() - start_time
        
        # Add processing time to result
        result['processing_time'] = round(elapsed_time, 2)
        
        logger.info(f"Query processed in {elapsed_time:.2f} seconds")
        logger.info(f"Query result: {result}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error processing query: {e}")
        return jsonify({
            'error': str(e),
            'answer': "I encountered an error while processing your question. Please try again.",
            'sources': [],
            'has_context': False
        }), 500

@socketio.on('query')
def handle_query(data):
    try:
        query = data.get('query')
        model = data.get('model', 'gpt-4o-mini')
        query_id = data.get('queryId', str(uuid.uuid4()))
        conversation_id = data.get('conversationId')
        
        if not query:
            emit('query_error', {
                'queryId': query_id,
                'error': 'No query provided'
            })
            return
        
        # Emit that we're processing the query
        emit('query_processing', {
            'queryId': query_id,
            'status': 'processing'
        })
        
        # Define a function to emit tokens during streaming
        def emit_token(event, data):
            socketio.emit(event, data, room=request.sid)
        
        # Generate answer with streaming
        result = generate_answer_with_langchain(
            query, 
            model=model, 
            conversation_id=conversation_id,
            streaming=True,
            socket_emit_func=emit_token
        )
        
        # Emit the final result
        socketio.emit('query_result', {
            'queryId': query_id,
            'status': 'completed',
            'answer': result['answer'],
            'sources': result['sources'],
            'has_context': result['has_context'],
            'processing_time': result['processing_time']
        }, room=request.sid)
        
    except Exception as e:
        logger.error(f"Error in handle_query: {str(e)}")
        emit('query_error', {
            'queryId': query_id if 'query_id' in locals() else 'unknown',
            'error': str(e)
        })

@app.route('/api/message', methods=['POST'])
def process_message():
    """
    Process a user message and generate an AI response using RAG
    This is the main endpoint for the chat interface
    """
    try:
        data = request.json
        message = data.get('message')
        
        if not message:
            return jsonify({'error': 'No message provided'}), 400
        
        logger.info(f"Processing message: {message}")
        
        # Generate answer with RAG
        start_time = time.time()
        result = generate_answer_with_context(message)
        elapsed_time = time.time() - start_time
        
        # Format response
        response = {
            'role': 'assistant',
            'content': result['answer'],
            'sources': result['sources'],
            'has_context': result['has_context'],
            'processing_time': round(elapsed_time, 2)
        }
        
        logger.info(f"Message processed in {elapsed_time:.2f} seconds")
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return jsonify({
            'role': 'assistant',
            'content': "I encountered an error while processing your message. Please try again.",
            'sources': [],
            'has_context': False
        }), 500

if __name__ == '__main__':
    # Initialize Pinecone
    initialize_pinecone()
    logger.info("Starting PDF upload server with RAG capabilities...")
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)