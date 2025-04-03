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
from queue import Queue
# from gevent import monkey
# monkey.patch_all()
load_dotenv()
from conversation import (
    get_all_conversations_from_db,
    get_conversation_messages,
    generate_answer_with_context_and_history,
    add_file_to_conversation,
    get_conversation_files,
    ConversationManager
)
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

from thread_ocr import process_pdfs_with_ocr

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

def process_pdf_pages(file_bytes, upload_id, file_id, filename, sid, conversation_id):
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
        chunks_processed = process_pdf_chunk(all_page_data, file_id, filename, conversation_id)
        
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
        conversation_id = request.form.get('conversationId')
        print(f"Conversation ID: {conversation_id}")
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
        result_file_id = process_pdf_pages(file_bytes, upload_id, file_id, filename, sid, conversation_id)
        # Update MongoDB document with the file information
        if add_file_to_conversation(conversation_id, filename, unique_filename):
            logger.info(f"Added file {filename} to conversation {conversation_id}")
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


@app.route('/api/conversations', methods=['POST'])
def get_all_conversations():
    """
    Get all conversations for a specific user
    """
    try:
        data = request.json
        user_id = data.get('userId')
        
        conversations = get_all_conversations_from_db(user_id)
        
        return jsonify({
            'conversations': conversations
        })
        
    except Exception as e:
        logger.error(f"Error fetching conversations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversation-messages', methods=['POST'])
def get_conversation_messages_endpoint():
    """
    Get all messages for a specific conversation
    """
    try:
        data = request.json
        conversation_id = data.get('conversationId')
        
        if not conversation_id:
            return jsonify({'error': 'No conversation ID provided'}), 400
            
        result = get_conversation_messages(conversation_id)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error fetching conversation messages: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-conversation', methods=['POST'])
def delete_conversation_endpoint():
    """
    Delete a specific conversation from the database
    """
    try:
        data = request.json
        conversation_id = data.get('conversationId')
        
        if not conversation_id:
            return jsonify({'error': 'No conversation ID provided'}), 400
        
        # Initialize conversation manager if needed
        conversation_manager = ConversationManager()
        
        # Delete the conversation
        success = conversation_manager.delete_conversation(conversation_id)
        
        if success:
            logger.info(f"Successfully deleted conversation {conversation_id}")
            return jsonify({'success': True, 'message': 'Conversation deleted successfully'})
        else:
            logger.error(f"Failed to delete conversation {conversation_id}")
            return jsonify({'success': False, 'error': 'Failed to delete conversation'}), 500
            
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
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
        
        logger.info(f"Processing streamed query: {query} with conversation_id: {conversation_id}")
        
        # Emit that we're processing the query
        emit('query_processing', {
            'queryId': query_id,
            'status': 'processing'
        })
        
        # Define a function to emit tokens during streaming
        def emit_token(event, data):
            print(f"Emitting token: {data}")
            socketio.emit(event, data, room=request.sid)
        
        # Generate answer with streaming
        result = generate_answer_with_context_and_history(
            query, 
            model=model, 
            conversation_id=conversation_id,
            # streaming=True,
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

@app.route('/api/citation-text', methods=['POST'])
def get_citation_text():
    """Get the text content for a specific citation"""
    try:
        data = request.json
        citation_source = data.get('source')
        conversation_id = data.get('conversationId')
        # Not implemented yet 
        return jsonify({'error': 'Invalid citation source format'}), 400
        
    except Exception as e:
        logger.error(f"Error getting citation text: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pdf/<filename>', methods=['GET'])
def get_pdf_file(filename):
    """
    Get a specific PDF file by filename
    """
    try:
        # Get conversation_id from the request if provided
        conversation_id = request.args.get('conversation_id')
        logger.info(f"Getting PDF file {filename} for conversation {conversation_id}")            
        # Try to get the file information from MongoDB
        pdf_path = None
        
        # First check if this is a file ID
        unique_name = get_conversation_files(conversation_id).get(filename, None)
        if unique_name:
                pdf_path = os.path.join(UPLOAD_FOLDER, unique_name)
        else:
            logger.info(f"File {filename} not found in MongoDB")
                    
        if not pdf_path:
            return jsonify({'error': 'PDF not found'}), 404
            
        # Return the PDF file
        return send_from_directory(
            os.path.dirname(pdf_path),
            os.path.basename(pdf_path),
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logger.error(f"Error retrieving PDF file: {e}")
        return jsonify({'error': str(e)}), 500

# Replace the existing scan_pdf route with this implementation
@app.route('/api/scan_pdf', methods=['POST'])
def scan_pdf():
    """Handle PDF OCR upload and processing with Pinecone indexing"""
    try:
        # Check if files are in the request
        if 'scans' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided for OCR processing'}), 400
            
        files = request.files.getlist('scans')
        conversation_id = request.form.get('conversationId')
        socket_id = request.form.get('socketId')
        
        if not files or len(files) == 0:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
            
        logger.info(f"Received {len(files)} files for OCR processing in conversation {conversation_id}")
        
        # Process each file - only accept PDFs
        valid_files = []
        for file in files:
            # Validate file is a PDF
            if not file.filename or not file.filename.lower().endswith('.pdf'):
                return jsonify({'success': False, 'error': 'Only PDF files are supported for OCR'}), 400
                
            # Generate file ID
            file_id = str(uuid.uuid4())
            
            # Read file bytes and add to processing list
            file_bytes = file.read()
            valid_files.append((file.filename, file_bytes, file_id))
            
            # Save the uploaded file
            secure_name = secure_filename(file.filename)
            unique_filename = f"{file_id}_{secure_name}"
            file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            
            # Save the file to disk
            with open(file_path, 'wb') as f:
                f.write(file_bytes)
                
            # Add file to the conversation
            if add_file_to_conversation(conversation_id, file.filename, unique_filename):
                logger.info(f"Added OCR PDF {file.filename} to conversation {conversation_id}")
        
        # Generate a unique ID for this OCR batch
        ocr_batch_id = str(uuid.uuid4())
        
        # Create directory for OCR results if it doesn't exist
        ocr_results_dir = os.path.join(UPLOAD_FOLDER, 'ocr_results')
        if not os.path.exists(ocr_results_dir):
            os.makedirs(ocr_results_dir)
        
        result_queue = Queue()
        
        # Modify the thread function to use a queue for communication
        def process_ocr_files_thread():
            try:
                # Process all files without intermediate progress updates
                ocr_results = process_pdfs_with_ocr(
                    valid_files, 
                    process_pdf_chunk,
                    conversation_id,
                    max_workers=4,
                )
                
                # Save OCR results to text files
                for filename, text in ocr_results.items():
                    if text:
                        # Save extracted text to a file
                        safe_filename = secure_filename(filename)
                        text_filename = f"{ocr_batch_id}_{safe_filename}.txt"
                        text_path = os.path.join(ocr_results_dir, text_filename)
                        
                        with open(text_path, 'w', encoding='utf-8') as f:
                            f.write(text)
                            
                        logger.info(f"Saved OCR text for {filename} to {text_path}")
                
                # Put success result in queue
                result_queue.put({
                    'success': True,
                    'fileId': ocr_batch_id,
                    'totalFiles': len(files)
                })
                
            except Exception as e:
                # Put error result in queue
                logger.error(f"Error in OCR processing thread: {str(e)}")
                result_queue.put({
                    'success': False,
                    'error': str(e),
                    'fileId': ocr_batch_id
                })
        
        # Start OCR processing in a background thread
        ocr_thread = threading.Thread(target=process_ocr_files_thread)
        ocr_thread.start()  # Remove daemon=True
        
        # Wait for the thread to complete and get results
        ocr_thread.join(timeout=300)  # 5-minute timeout
        
        # Retrieve results from the queue
        try:
            result = result_queue.get(block=False)
            
            # Use socketio.emit with namespace if needed
            if socket_id:
                if result.get('success'):
                    # Emit progress update
                    socketio.emit('scan_progress', {
                        'id': f"ocr-{result['fileId']}",
                        'fileId': result['fileId'],
                        'fileName': f"OCR Documents ({result['totalFiles']})",
                        'progress': 100,
                        'status': 'completed',
                        'message': 'OCR processing completed successfully',
                        'totalPages': len(valid_files),
                        'processedPages': len(valid_files)
                    }, room=socket_id)
                    
                    # Emit completion event
                    socketio.emit('scan_complete', {
                        'success': True,
                        'fileId': result['fileId'],
                        'message': 'OCR processing completed successfully'
                    }, room=socket_id)
                else:
                    # Emit error event
                    socketio.emit('scan_progress', {
                        'id': f"ocr-{result['fileId']}",
                        'fileId': result['fileId'],
                        'fileName': f"OCR Documents ({len(files)})",
                        'progress': 0,
                        'status': 'error',
                        'error': f'OCR processing failed: {result.get("error", "Unknown error")}'
                    }, room=socket_id)
            
            # Return appropriate response
            return jsonify({
                'success': result.get('success', False),
                'fileId': result.get('fileId'),
                'message': 'OCR processing completed.'
            })
        
        except result_queue.Empty:
            # Thread did not complete in time
            logger.error("OCR processing thread timed out")
            return jsonify({
                'success': False, 
                'error': 'OCR processing timed out'
            }), 500
        
    except Exception as e:
        logger.error(f"Error processing OCR documents: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

    
if __name__ == '__main__':
    # Initialize Pinecone
    initialize_pinecone()
    logger.info("Starting PDF upload server with RAG capabilities...")
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)