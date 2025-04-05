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
from structured_output import generate_answer_with_structured_context
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
        
    def add_file_to_conversation(self, conversation_id: str, filename: str, unique_filename: str):
        """
        Add a file to a specific conversation
        
        Args:
            conversation_id: ID of the conversation to add the file to
        """
        try:
            collection = self.collection
            doc = collection.find_one({"conversation_id": conversation_id})
            if doc and "files" in doc:
                # If files exists, add the new key-value pair to the existing dictionary
                existing_files = doc.get("files", {})
                existing_files[filename] = unique_filename
                metadata_update = {"files": existing_files}
            else:
                # If files doesn't exist, create a new dictionary with the key-value pair
                metadata_update = {"files": {filename: unique_filename}}
                
            # Update the database with the new file information
            result = collection.update_one(
                {"conversation_id": conversation_id},
                {"$set": {
                    "files": metadata_update["files"],
                    "last_updated": datetime.utcnow()
                }},
                upsert=True
            )
            
            logger.info(f"Added file {filename} to conversation {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding file to conversation {conversation_id}: {e}")
            return False
        
    def get_conversation_files(self, conversation_id: str):
        """
        Get the files for a specific conversation
        """
        try:
            collection = self.collection
            doc = collection.find_one({"conversation_id": conversation_id})
            return doc.get("files", {})
        except Exception as e:
            logger.error(f"Error getting files for conversation {conversation_id}: {e}")
            return {}
        
    def add_structured_message(self, conversation_id: str, structured_message: Dict[str, Any]) -> None:
        """
        Add a simplified structured message to the conversation history
        
        Args:
            conversation_id: Unique identifier for the conversation
            structured_message: Message with role, content, and simplified paragraph structure
        """
        # Get existing messages
        messages = self.get_conversation(conversation_id)
        
        # Add new structured message
        messages.append(structured_message)
        
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
            logger.info(f"Added simplified message to conversation {conversation_id} and updated MongoDB")
        except Exception as e:
            logger.error(f"Error updating conversation in MongoDB: {e}")

    def get_full_conversation(self, conversation_id):
        """
        Get the full MongoDB document for a conversation
        
        Args:
            conversation_id: The ID of the conversation to retrieve
            
        Returns:
            The full conversation document as a dictionary, or None if not found
        """
        try:
            # Find the conversation by ID
            collection = self.collection
            conversation = collection.find_one({"conversation_id": conversation_id})
            
            if not conversation:
                return None
                
            # Convert ObjectId to string for JSON serialization
            conversation['_id'] = str(conversation['_id'])
            
            # Convert any other MongoDB-specific types that may not be JSON serializable
            for message in conversation.get('messages', []):
                if '_id' in message:
                    message['_id'] = str(message['_id'])
                    
            # Process any nested documents
            if 'files' in conversation and isinstance(conversation['files'], dict):
                for file_key, file_value in conversation['files'].items():
                    if hasattr(file_value, 'to_json'):
                        conversation['files'][file_key] = file_value.to_json()
                        
            return conversation
            
        except Exception as e:
            logger.error(f"Error getting full conversation: {e}")
            return None

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
def get_all_conversations_from_db(user_id=None):
    """
    Get all conversation IDs from MongoDB with their first user message
    
    Args:
        user_id: Optional user ID to filter conversations
        
    Returns:
        List of dictionaries with conversation IDs and first messages
    """
    try:
        global conversation_manager
        if conversation_manager is None:
            conversation_manager = ConversationManager()
            
        # Get all conversation IDs
        conversation_ids = conversation_manager.get_conversation_ids()
        
        # Get the first user message for each conversation
        conversations_with_preview = []
        
        for conv_id in conversation_ids:
            messages = conversation_manager.get_conversation(conv_id)
            
            # Find the first user message
            first_user_message = None
            for msg in messages:
                if msg.get('role') == 'user':
                    first_user_message = msg.get('content')
                    # Truncate long messages
                    if first_user_message and len(first_user_message) > 50:
                        first_user_message = first_user_message[:50] + '...'
                    break
                    
            conversations_with_preview.append({
                "conversation_id": conv_id,
                "first_message": first_user_message or "New conversation",
                "message_count": len([m for m in messages if m.get('role') != 'system'])
            })
            
        logger.info(f"Retrieved {len(conversations_with_preview)} conversations with previews")
        return conversations_with_preview
        
    except Exception as e:
        logger.error(f"Error retrieving conversations from MongoDB: {e}")
        return []
    
    
def get_conversation_messages(conversation_id: str):
    """
    Get all messages for a specific conversation
    
    Args:
        conversation_id: ID of the conversation to retrieve
        
    Returns:
        Dict containing the messages and conversation metadata
    """
    try:
        # Get the conversation manager
        global conversation_manager
        if conversation_manager is None:
            conversation_manager = ConversationManager()
            
        # Retrieve messages for the specified conversation
        messages = conversation_manager.get_conversation(conversation_id)
        
        # Get metadata
        metadata = conversation_manager.get_conversation_metadata(conversation_id)
        
        logger.info(f"Retrieved {len(messages)} messages for conversation {conversation_id}")
        
        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "metadata": metadata
        }
        
    except Exception as e:
        logger.error(f"Error retrieving conversation messages: {e}")
        return {
            "conversation_id": conversation_id,
            "messages": [],
            "metadata": {},
            "error": str(e)
        }
    
def add_file_to_conversation(conversation_id: str, filename: str, unique_filename: str):
    return conversation_manager.add_file_to_conversation(conversation_id, filename, unique_filename)

def get_conversation_files(conversation_id: str,):
    return conversation_manager.get_conversation_files(conversation_id)

def generate_answer_with_context_and_history(
    user_query: str, 
    model: str = DEFAULT_MODEL,
    conversation_id: Optional[str] = None,
    streaming: bool = False,
    socket_emit_func = None
) -> Dict[str, Any]:
    """
    Wrapper function that uses the structured context generator and adds results to conversation history
    
    Args:
        user_query: The user's question
        model: The OpenAI model to use for generating the answer
        conversation_id: Optional ID to keep track of conversation history
        streaming: Whether to stream the response tokens
        socket_emit_func: Function to emit streaming tokens if streaming is True
        
    Returns:
        Dictionary containing the answer, sources, and whether relevant context was found
    """
    start_time = time.time()
    logger.info(f"Wrapper: Generating answer for query: '{user_query}' with model {model}")
    
    # Ensure the conversation manager is initialized
    global conversation_manager
    if conversation_manager is None:
        conversation_manager = ConversationManager()
    
    try:
        # Get conversation history from MongoDB if conversation_id is provided
        conversation_history = []
        if conversation_id:
            conversation_history = conversation_manager.get_conversation(conversation_id)
            # Extract only role and content from conversation history for the LLM context
            # This prevents the model from seeing the structured data and sources directly
            simplified_history = []
            for message in conversation_history:
                # Only include role and content fields
                simplified_message = {
                    "role": message.get("role", ""),
                    "content": message.get("content", "")
                }
                simplified_history.append(simplified_message)
            
            # Replace the full history with the simplified version
            conversation_history = simplified_history
            logger.info(f"Retrieved {len(conversation_history)} messages from conversation history")
        
        # Use the structured context generator with conversation history
        result = generate_answer_with_structured_context(
            user_query=user_query,
            model=model,
            conversation_id=conversation_id,
            conversation_history=conversation_history
        )
        
        # Extract the info we need
        answer = result["answer"]
        structured_data = result["structured_data"]
        sources = result["sources"]
        has_context = result["has_context"]
        
        # Prepare the structured message to add to conversation history
        structured_message = {
            "role": "assistant",
            "content": answer,
            "paragraphs": structured_data
        }
        
        # Add to conversation history if we have a conversation ID
        if conversation_id:
            # Add the user query to the conversation history
            conversation_manager.add_to_conversation(conversation_id, "user", user_query)
            conversation_manager.add_structured_message(conversation_id, structured_message)
            logger.info(f"Added structured message to conversation {conversation_id}")
        
        elapsed_time = time.time() - start_time
        
        return {
            "answer": answer,
            "structured_data": structured_data,
            "sources": sources,
            "has_context": has_context,
            "processing_time": round(elapsed_time, 2)
        }
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"Error in wrapper function: {e}")
        
        error_message = f"I encountered an error while processing your question: {str(e)}"
        
        # Add error to conversation history if we have a conversation ID
        if conversation_id:
            conversation_manager.add_to_conversation(conversation_id, "user", user_query)
            conversation_manager.add_to_conversation(conversation_id, "assistant", error_message)
        
        return {
            "answer": error_message,
            "sources": [],
            "structured_data": [],
            "has_context": False,
            "processing_time": round(elapsed_time, 2),
            "error": str(e)
        }
if __name__ == "__main__":
    # Example usage
    try:
        get_mongodb_connection()
        print("MongoDB connection successful.")
    except Exception as e:
        print(f"MongoDB connection failed: {e}")