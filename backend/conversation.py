# conversation.py
import os
import logging
import time
import uuid
from typing import List, Dict, Tuple, Optional, Any, Union
from datetime import datetime
import pymongo
from pymongo import MongoClient
from dotenv import load_dotenv
from openai import OpenAI

# Import the RAG utilities
from rag_utils import (
    get_relevant_context,
    SIMILARITY_THRESHOLD
)


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants for configuration
DEFAULT_MODEL = "gpt-4o-mini"  # Default model to use
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
MONGODB_DB = os.getenv('MONGODB_DB', 'rag_conversations')
MONGODB_COLLECTION = os.getenv('MONGODB_COLLECTION', 'conversations')
CACHE_TIMEOUT_SECONDS = 3600  # How long to keep conversations in memory cache (1 hour)

# MongoDB client (initialized on first use)
mongo_client = None
db = None
conversations_collection = None

# In-memory cache for conversations
# Format: {conversation_id: {'data': [...], 'last_accessed': timestamp}}
conversation_cache = {}

def get_mongodb_connection():
    """
    Initialize and return MongoDB client and collection.
    Uses lazy initialization to connect only when needed.
    """
    global mongo_client, db, conversations_collection
    
    if mongo_client is None:
        try:
            mongo_client = MongoClient(MONGODB_URI)
            db = mongo_client[MONGODB_DB]
            conversations_collection = db[MONGODB_COLLECTION]
            logger.info(f"Connected to MongoDB: {MONGODB_URI}, database: {MONGODB_DB}")
            
            # Create indexes for faster queries
            conversations_collection.create_index("conversation_id")
            conversations_collection.create_index("last_updated")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    return conversations_collection

def clean_expired_cache_entries():
    """Remove expired entries from the in-memory cache"""
    current_time = time.time()
    expired_keys = []
    
    for conv_id, cache_data in conversation_cache.items():
        if current_time - cache_data['last_accessed'] > CACHE_TIMEOUT_SECONDS:
            expired_keys.append(conv_id)
    
    for key in expired_keys:
        logger.info(f"Removing expired cache entry for conversation {key}")
        del conversation_cache[key]
    
    if expired_keys:
        logger.info(f"Removed {len(expired_keys)} expired cache entries")

class ConversationManager:
    """
    Manages conversation history and state for the RAG system
    with MongoDB persistence and memory caching
    """
    
    def __init__(self):
        """Initialize the conversation manager"""
        # The actual conversations data is stored in the global cache
        # and MongoDB for persistence
        self.collection = get_mongodb_connection()
        pass
    
    def get_all_conversations(self) -> List[str]:
        """
        Get all conversations from MongoDB
        
        Returns:
            List of conversation documents
        """
        try:
            collection = self.collection
            cursor = collection.find({})
            doc = list(cursor)
            conversation_ids = [doc.get("conversation_id",None) for doc in doc]
            logger.info(f"Retrieved {len(conversation_ids)} conversations from MongoDB")
            return conversation_ids
        except Exception as e:
            logger.error(f"Error retrieving conversations from MongoDB: {e}")
            return []
    
    def get_conversation(self, conversation_id: str) -> List[Dict[str, str]]:
        """
        Get conversation history from cache or MongoDB
        
        Args:
            conversation_id: Unique identifier for the conversation
            
        Returns:
            List of message objects with role and content
        """
        # Clean expired cache entries
        clean_expired_cache_entries()
        
        # Check if conversation is in memory cache
        if conversation_id in conversation_cache:
            # Update last accessed time
            conversation_cache[conversation_id]['last_accessed'] = time.time()
            logger.info(f"Retrieved conversation {conversation_id} from cache")
            return conversation_cache[conversation_id]['data']
        
        # Not in cache, try to get from MongoDB
        try:
            collection = self.collection
            conversation_doc = collection.find_one({"conversation_id": conversation_id})
            
            if conversation_doc:
                # Found in MongoDB, update cache
                messages = conversation_doc.get("messages", [])
                conversation_cache[conversation_id] = {
                    'data': messages,
                    'last_accessed': time.time()
                }
                logger.info(f"Retrieved conversation {conversation_id} from MongoDB")
                return messages
            
            # Not found in MongoDB, initialize new conversation
            logger.info(f"Creating new conversation with ID {conversation_id}")
            messages = [
                {
                    "role": "system", 
                    "content": "You are a helpful assistant that answers questions based on specific context provided."
                }
            ]
            
            # Save to cache and MongoDB
            conversation_cache[conversation_id] = {
                'data': messages,
                'last_accessed': time.time()
            }
            
            collection.insert_one({
                "conversation_id": conversation_id,
                "messages": messages,
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "metadata": {}
            })
            
            return messages
            
        except Exception as e:
            logger.error(f"Error retrieving conversation from MongoDB: {e}")
            # Fall back to a new conversation if we can't connect to MongoDB
            messages = [
                {
                    "role": "system", 
                    "content": "You are a helpful assistant that answers questions based on specific context provided."
                }
            ]
            conversation_cache[conversation_id] = {
                'data': messages,
                'last_accessed': time.time()
            }
            return messages
    
    def add_to_conversation(self, conversation_id: str, role: str, content: str) -> None:
        """
        Add a message to the conversation history
        
        Args:
            conversation_id: Unique identifier for the conversation
            role: Message role (user, assistant, system)
            content: Message content
        """
        # Get existing messages
        messages = self.get_conversation(conversation_id)
        
        # Add new message
        messages.append({"role": role, "content": content})
        
        # Update cache
        conversation_cache[conversation_id] = {
            'data': messages,
            'last_accessed': time.time()
        }
        
        # Update MongoDB
        try:
            collection = self.collection
            collection.update_one(
                {"conversation_id": conversation_id},
                {
                    "$set": {
                        "messages": messages,
                        "last_updated": datetime.utcnow()
                    }
                },
                upsert=True
            )
            logger.info(f"Added message to conversation {conversation_id} and updated MongoDB")
        except Exception as e:
            logger.error(f"Error updating conversation in MongoDB: {e}")
            # Continue with in-memory only if MongoDB fails
    
    def clear_conversation(self, conversation_id: str) -> bool:
        """
        Clear conversation history, keeping only the system message
        
        Args:
            conversation_id: The ID of the conversation to clear
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Initialize with just the system message
            messages = [
                {
                    "role": "system", 
                    "content": "You are a helpful assistant that answers questions based on specific context provided."
                }
            ]
            
            # Update cache
            conversation_cache[conversation_id] = {
                'data': messages,
                'last_accessed': time.time()
            }
            
            # Update MongoDB
            try:
                collection = self.collection
                collection.update_one(
                    {"conversation_id": conversation_id},
                    {
                        "$set": {
                            "messages": messages,
                            "last_updated": datetime.utcnow(),
                            "cleared_at": datetime.utcnow()
                        }
                    },
                    upsert=True
                )
                logger.info(f"Cleared conversation {conversation_id}")
            except Exception as e:
                logger.error(f"Error clearing conversation in MongoDB: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Error clearing conversation {conversation_id}: {e}")
            return False
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Completely delete a conversation
        
        Args:
            conversation_id: The ID of the conversation to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Remove from cache
            if conversation_id in conversation_cache:
                del conversation_cache[conversation_id]
            
            # Remove from MongoDB
            try:
                collection = self.collection
                result = collection.delete_one({"conversation_id": conversation_id})
                
                if result.deleted_count > 0:
                    logger.info(f"Deleted conversation {conversation_id} from MongoDB")
                else:
                    logger.warning(f"Conversation {conversation_id} not found in MongoDB")
            except Exception as e:
                logger.error(f"Error deleting conversation from MongoDB: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Error deleting conversation {conversation_id}: {e}")
            return False
    
    def get_conversation_ids(self) -> List[str]:
        """
        Get a list of all active conversation IDs
        
        Returns:
            List of conversation IDs
        """
        try:
            collection = self.collection
            cursor = collection.find({}, {"conversation_id": 1, "_id": 0})
            ids = [doc["conversation_id"] for doc in cursor]
            
            logger.info(f"Retrieved {len(ids)} conversation IDs from MongoDB")
            return ids
        except Exception as e:
            logger.error(f"Error retrieving conversation IDs from MongoDB: {e}")
            # Fall back to cache if MongoDB fails
            return list(conversation_cache.keys())
    
    def get_conversation_metadata(self, conversation_id: str) -> Dict[str, Any]:
        """
        Get metadata for a specific conversation
        
        Args:
            conversation_id: The ID of the conversation
            
        Returns:
            Dictionary of metadata
        """
        try:
            collection = self.collection
            doc = collection.find_one(
                {"conversation_id": conversation_id},
                {"metadata": 1, "created_at": 1, "last_updated": 1, "_id": 0}
            )
            
            if doc:
                return {
                    "metadata": doc.get("metadata", {}),
                    "created_at": doc.get("created_at"),
                    "last_updated": doc.get("last_updated"),
                    "message_count": len(self.get_conversation(conversation_id))
                }
            else:
                return {
                    "metadata": {},
                    "message_count": len(self.get_conversation(conversation_id))
                }
        except Exception as e:
            logger.error(f"Error retrieving conversation metadata from MongoDB: {e}")
            return {
                "metadata": {},
                "message_count": len(self.get_conversation(conversation_id)) if conversation_id in conversation_cache else 0
            }
    
    def update_conversation_metadata(self, conversation_id: str, metadata: Dict[str, Any]) -> bool:
        """
        Update metadata for a specific conversation
        
        Args:
            conversation_id: The ID of the conversation
            metadata: Dictionary of metadata to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            collection = self.collection
            result = collection.update_one(
                {"conversation_id": conversation_id},
                {"$set": {"metadata": metadata, "last_updated": datetime.utcnow()}},
                upsert=True
            )
            
            logger.info(f"Updated metadata for conversation {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating conversation metadata in MongoDB: {e}")
            return False

def generate_answer_with_context_and_history(
    user_query: str, 
    model: str = DEFAULT_MODEL,
    conversation_id: Optional[str] = None,
    streaming: bool = False,
    socket_emit_func = None
) -> Dict[str, Any]:
    """
    Generate an answer to a user query using context from vector search and conversation history
    
    Args:
        user_query: The user's question
        model: The OpenAI model to use for generating the answer
        conversation_id: Optional ID to keep track of conversation history
        streaming: Whether to stream the response tokens
        socket_emit_func: Function to emit streaming tokens if streaming is True
        filters: Optional metadata filters to apply when retrieving documents
        
    Returns:
        Dictionary containing the answer, sources, and whether relevant context was found
    """
    start_time = time.time()
    logger.info(f"Generating answer for query: '{user_query}' with model {model}")
    
    # Ensure the conversation manager is initialized
    global conversation_manager
    if conversation_manager is None:
        conversation_manager = ConversationManager()
    
    try:
        # Get relevant context
        context, sources = get_relevant_context(user_query, conversation_id=conversation_id)
        
        # If no relevant context found
        
        if not context:
            context_prompt = f"""You are answering a question generally.
                    {user_query}
                    """
            has_context = False
        
        # Create prompt with context
        else: 
            context_prompt = f"""You are answering a question based on specific context provided.
                    Answer the question based ONLY on the context provided.
                    If the context doesn't contain the information needed to answer the question, say "I don't have enough information to answer that question."
                    Do not use any prior knowledge outside what is provided in the context or conversation history.

                    CONTEXT:
                    {context}

                    QUESTION:
                    {user_query}
                    """
            has_context = True
        
        # Initialize OpenAI client
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Get conversation history if available
        messages = []
        if conversation_id:
            # Get existing conversation
            messages = conversation_manager.get_conversation(conversation_id).copy()
            # Add the context and question as the latest user message
            messages.append({"role": "user", "content": context_prompt})
        else:
            # No conversation history, just use system message and the prompt
            messages = [
                {"role": "system", "content": "You are a helpful assistant that answers questions based on specific context provided."},
                {"role": "user", "content": context_prompt}
            ]
        
        # Prepare request parameters
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2000
        }
        
        # Add streaming parameters if enabled
        if streaming:
            request_params["stream"] = True
        
        # Generate answer with OpenAI
        if streaming and socket_emit_func:
            # Handle streaming response
            logger.info(f"Streaming enabled, will emit tokens via WebSocket")
            answer_chunks = []
            
            # Make streaming request
            stream = client.chat.completions.create(**request_params)
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    answer_chunks.append(content)
                    print(content, end='', flush=True)
                    # Emit the token to the client
                    logger.debug(f"Emitting token: {content}")
                    socket_emit_func('token', {'token': content})
                    
                    # Small delay to avoid overwhelming the client
                    time.sleep(0.2)
            
            # Combine chunks into final answer
            answer = ''.join(answer_chunks)
            logger.info(f"Streaming complete, total response length: {len(answer)}")
        else:
            # Non-streaming request
            logger.info(f"Using non-streaming request")
            completion = client.chat.completions.create(**request_params)
            answer = completion.choices[0].message.content
            
        # Add to conversation history if we have a conversation ID
        if conversation_id:
            conversation_manager.add_to_conversation(conversation_id, "user", user_query)
            conversation_manager.add_to_conversation(conversation_id, "assistant", answer)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Generated answer in {elapsed_time:.2f} seconds")
        
        return {
            "answer": answer,
            "sources": sources,
            "has_context": has_context,
            "processing_time": round(elapsed_time, 2)
        }
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"Error generating answer: {e}")
        
        error_message = f"I encountered an error while processing your question: {str(e)}"
        
        # Still add to conversation history if we have a conversation ID
        if conversation_id:
            conversation_manager.add_to_conversation(conversation_id, "user", user_query)
            conversation_manager.add_to_conversation(conversation_id, "assistant", error_message)
        
        return {
            "answer": error_message,
            "sources": [],
            "has_context": False,
            "processing_time": round(elapsed_time, 2),
            "error": str(e)
        }

def clear_conversation(conversation_id: str) -> bool:
    """
    Clear a specific conversation history
    
    Args:
        conversation_id: The ID of the conversation to clear
        
    Returns:
        True if successful, False otherwise
    """
    # Ensure the conversation manager is initialized
    global conversation_manager
    if conversation_manager is None:
        conversation_manager = ConversationManager()
        
    try:
        return conversation_manager.clear_conversation(conversation_id)
    except Exception as e:
        logger.error(f"Error clearing conversation {conversation_id}: {e}")
        return False

# Initialize the conversation manager
conversation_manager = ConversationManager()

# wrapper for get_all_conversations
def get_all_conversations_from_db() -> List[str]:
    """
    Get all conversation IDs from MongoDB
    
    Returns:
        List of conversation IDs
    """
    try:
        return conversation_manager.get_all_conversations()
    except Exception as e:
        logger.error(f"Error retrieving conversations from MongoDB: {e}")
        return []


# Example Flask API routes (commented out for reference):
"""
@app.route('/api/query', methods=['POST'])
def query_pdf_content():
    try:
        data = request.json
        query = data.get('query')
        model = data.get('model', DEFAULT_MODEL)
        conversation_id = data.get('conversation_id')
        
        if not query:
            return jsonify({'error': 'No query provided'}), 400
        
        logger.info(f"Processing query: {query}")
        
        # Generate answer with context and history
        result = generate_answer_with_context_and_history(
            query, 
            model=model, 
            conversation_id=conversation_id
        )
        
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
        model = data.get('model', DEFAULT_MODEL)
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
"""

if __name__ == "__main__":
    # Example usage
    try:
        get_mongodb_connection()
        print("MongoDB connection successful.")
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
    # conversation_id = f"test-{uuid.uuid4()}"
    # print(f"Testing with conversation ID: {conversation_id}")
    
    # # First query
    # first_query = "What is this document about?"
    # print(f"\nFirst Query: '{first_query}'")
    
    # result1 = generate_answer_with_context_and_history(
    #     first_query,
    #     conversation_id=conversation_id
    # )
    
    # print(f"Answer: {result1['answer']}")
    # print(f"Sources: {result1['sources']}")
    
    # # Second query that references the first
    # second_query = "Can you tell me more about that topic?"
    # print(f"\nSecond Query: '{second_query}'")
    
    # result2 = generate_answer_with_context_and_history(
    #     second_query,
    #     conversation_id=conversation_id
    # )
    
    # print(f"Answer: {result2['answer']}")
    # print(f"Sources: {result2['sources']}")
    
    # # Print the conversation history
    # history = conversation_manager.get_conversation(conversation_id)
    # print("\nConversation History:")
    # for msg in history:
    #     role = msg["role"]
    #     if role != "system":
    #         print(f"{role.upper()}: {msg['content'][:100]}...")