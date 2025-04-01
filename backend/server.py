#server.py
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
    # generate_answer_with_context,
    PINECONE_INDEX_NAME,
    EMBEDDING_DIMENSION
)

from conversation import (
    get_all_conversations_from_db,
    generate_answer_with_context_and_history
)

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

def process_pdf_pages(file_bytes, upload_id, file_id, filename, sid):
    """Process PDF pages and send progress updates via WebSocket"""
    try:
        from pypdf import PdfReader
        import io
        
        # Read the PDF
        pdf_stream = io.BytesIO(file_bytes)
        pdf = PdfReader(pdf_stream)
        total_pages = len(pdf.pages)
        
        # Initialize upload info
        active_uploads[upload_id] = {
            'filename': filename,
            'file_id': file_id,
            'start_time': time.time(),
            'sid': sid,
            'total_pages': total_pages,
            'processed_pages': 0,
            'completed': False
        }
        
        # Extract text from pages
        all_page_data = []
        for pageNum in range(total_pages):
            page = pdf.pages[pageNum]
            text = page.extract_text()
            all_page_data.append({
                'pageNum': pageNum + 1,  # 1-indexed for user-friendliness
                'text': text
            })
            
            # Update processed pages
            active_uploads[upload_id]['processed_pages'] = pageNum + 1
            
            # Calculate progress percentage
            progress = int(((pageNum + 1) / total_pages) * 100)
            
            # Emit progress update
            socketio.emit('upload_progress', {
                'id': upload_id,
                'fileId': file_id,
                'fileName': filename,
                'progress': progress,
                'status': 'uploading',
                'message': f'Extracting text from page {pageNum + 1}/{total_pages}',
                'processedPages': pageNum + 1,
                'totalPages': total_pages
            }, room=sid)
        
        # Process all pages at once
        socketio.emit('upload_progress', {
            'id': upload_id,
            'fileId': file_id,
            'fileName': filename,
            'progress': 100,
            'status': 'uploading',
            'message': f'Processing extracted text...',
            'processedPages': total_pages,
            'totalPages': total_pages
        }, room=sid)
        
        # Process the chunks
        chunks_processed = process_pdf_chunk(all_page_data, file_id, filename)
        
        # Mark as completed
        active_uploads[upload_id]['completed'] = True
        
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
        
        logger.info(f"Completed processing PDF {filename} with {chunks_processed} chunks")
        return file_id
        
    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        socketio.emit('upload_progress', {
            'id': upload_id,
            'fileId': file_id,
            'fileName': filename,
            'progress': 0,
            'status': 'error',
            'error': f'Error processing PDF: {str(e)}'
        }, room=sid)
        return None

@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    """Handle PDF upload via HTTP POST"""
    try:
        # Check if file is in the request
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
            
        file = request.files['file']
        
        # Check if filename is empty
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
            
        # Check if file is a PDF
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'success': False, 'error': 'File must be a PDF'}), 400
        
        # Get upload ID from form or generate one
        upload_id = request.form.get('uploadId', f"upload-{uuid.uuid4()}")
        
        # Generate a unique filename
        file_id = str(uuid.uuid4())
        filename = file.filename
        secure_name = secure_filename(filename)
        unique_filename = f"{file_id}_{secure_name}"
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        # Save file to disk
        file.save(file_path)
        logger.info(f"File saved to {file_path}")
        
        # Get client's socket ID
        sid = request.form.get('socketId')
        if not sid:
            # Get client connections for this session
            return jsonify({'success': False, 'error': 'Socket ID required for progress updates'}), 400
        
        # Read the file into memory
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        
        # Process the PDF (non-threaded)
        result_file_id = process_pdf_pages(file_bytes, upload_id, file_id, filename, sid)
        
        if result_file_id:
            return jsonify({
                'success': True,
                'fileId': file_id,
                'filename': filename,
                'message': 'File processed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to process PDF'
            }), 500
        
    except Exception as e:
        logger.error(f"Error in upload_pdf: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
        conversation_id = data.get('conversationId')
        
        if not query:
            return jsonify({'error': 'No query provided'}), 400
        
        logger.info(f"Processing query: {query}")
        
        # Generate answer with context
        start_time = time.time()
        
        # Use langchain if specified, otherwise use our standard RAG
        # if conversation_id:
        #     result = generate_answer_with_langchain(query, model=model, conversation_id=conversation_id)
        # else:
        result = generate_answer_with_context_and_history(query, model=model, 
                                                          conversation_id=conversation_id)
        
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
    
@app.route('/api/conversations', methods=['POST'])
def get_all_conversations():
    """
    Get all conversations for a specific user
    """
    try:
        data = request.json
        user_id = data.get('userId')
        
        if not user_id:
            return jsonify({'error': 'No user ID provided'}), 400
        conversations_ids = get_all_conversations_from_db(user_id)
        
        return jsonify({
            'conversations_ids': conversations_ids
        })
        
    except Exception as e:
        logger.error(f"Error fetching conversations: {e}")
        return jsonify({'error': str(e)}), 500

@socketio.on('query')
def handle_query(data):
    """Handle WebSocket query and stream response"""
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
        
        logger.info(f"Processing streamed query: {query}")
        
        # Emit that we're processing the query
        emit('query_processing', {
            'queryId': query_id,
            'status': 'processing'
        })
        
        # Define a function to emit tokens during streaming
        def emit_token(event, data):
            socketio.emit(event, data, room=request.sid)
        
        # Generate answer with streaming
        result = generate_answer_with_context_and_history(
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

if __name__ == '__main__':
    # Initialize Pinecone
    initialize_pinecone()
    logger.info("Starting PDF upload server with RAG capabilities...")
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)