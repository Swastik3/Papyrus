import os
import logging
import time
from typing import List, Dict, Tuple, Optional, Any
import numpy as np

# Import environment variable management
from dotenv import load_dotenv

# Import LangChain components
from langchain.chains import ConversationalRetrievalChain
# from langchain_community.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from langchain.memory import ConversationBufferMemory
from langchain.vectorstores import Pinecone as LangchainPinecone
from langchain.schema import Document
from langchain.prompts import PromptTemplate
from langchain.callbacks.base import BaseCallbackHandler
from langchain_openai import ChatOpenAI
# Import Pinecone
import pinecone
import warnings

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
SIMILARITY_THRESHOLD = 0.7  # Minimum similarity score to consider a chunk relevant
DEFAULT_MODEL = "gpt-4o-mini"  # Default model to use

# Global Pinecone client
pc = None

# Optional streaming callback handler for real-time responses
class StreamingCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming LLM responses"""
    
    def __init__(self, socket_emit_func=None):
        self.socket_emit_func = socket_emit_func
        self.response_chunks = []
        
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """Called when LLM produces a new token"""
        self.response_chunks.append(token)
        if self.socket_emit_func:
            self.socket_emit_func('token', {'token': token})
    
    def get_response(self) -> str:
        """Get the full response so far"""
        return ''.join(self.response_chunks)


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


class ConversationManager:
    """Manages conversation history and state for the RAG system"""
    
    def __init__(self):
        self.conversations = {}
        
    def get_memory(self, conversation_id: str) -> ConversationBufferMemory:
        """Get or create a memory object for a conversation"""
        if conversation_id not in self.conversations:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.conversations[conversation_id] = ConversationBufferMemory(
                    memory_key="chat_history",
                    return_messages=True
                )
        return self.conversations[conversation_id]
    
    def clear_memory(self, conversation_id: str) -> None:
        """Clear memory for a specific conversation"""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
            logger.info(f"Cleared memory for conversation {conversation_id}")
    
    def get_conversation_ids(self) -> List[str]:
        """Get a list of all active conversation IDs"""
        return list(self.conversations.keys())


# Global conversation manager
conversation_manager = ConversationManager()


def get_langchain_retriever(filters: Optional[Dict[str, Any]] = None):
    """
    Create a LangChain retriever connected to the Pinecone index
    
    Args:
        filters: Optional metadata filters to apply when retrieving documents
        
    Returns:
        A LangChain retriever object
    """
    # Initialize the embedding model
    embedding = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=os.getenv('OPENAI_API_KEY')
    )
    
    # Initialize Pinecone
    initialize_pinecone()
    
    # Connect to the vector store
    vectorstore = LangchainPinecone.from_existing_index(
        index_name=PINECONE_INDEX_NAME,
        embedding=embedding,
        text_key="text"  # The key in your metadata that contains the text content
    )
    
    # Create search parameters
    search_kwargs = {
        "k": 5,  # Number of documents to retrieve
        # "score_threshold": SIMILARITY_THRESHOLD
    }
    
    # Add filters if provided
    if filters:
        search_kwargs["filter"] = filters
    
    # Create and return the retriever
    return vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs=search_kwargs
    )


def format_sources(source_documents: List[Document]) -> List[str]:
    """
    Format source documents into a list of source citations
    
    Args:
        source_documents: List of LangChain Document objects
        
    Returns:
        List of formatted source citations
    """
    sources = []
    for doc in source_documents:
        source = doc.metadata.get("source", "Unknown")
        page = doc.metadata.get("page", None)
        
        if page is not None:
            source_with_page = f"{source} (page {page})"
            sources.append(source_with_page)
        else:
            sources.append(source)
    
    # Get unique sources
    return list(set(sources))


def generate_answer_with_langchain(
    user_query: str, 
    model: str = DEFAULT_MODEL, 
    conversation_id: Optional[str] = None,
    streaming: bool = False,
    socket_emit_func = None,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate an answer to a user query using LangChain's ConversationalRetrievalChain
    
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
    
    try:
        # Get the retriever
        retriever = get_langchain_retriever(filters)
        
        # Set up callback handlers for streaming if needed
        callbacks = None
        streaming_handler = None
        if streaming and socket_emit_func:
            streaming_handler = StreamingCallbackHandler(socket_emit_func)
            callbacks = [streaming_handler]
            logger.info("Streaming mode enabled with socket emit function")
        
        # Set up the LLM
        llm = ChatOpenAI(
            temperature=0.2, 
            model_name=model,
            max_tokens=1000,
            streaming=streaming,
            callbacks=callbacks,
            openai_api_key=os.getenv('OPENAI_API_KEY')
        )
        
        # Create memory if this is a conversation
        memory = None
        if conversation_id:
            memory = conversation_manager.get_memory(conversation_id)
            logger.info(f"Using conversation memory for ID: {conversation_id}")
        
        # Create custom prompts
        qa_prompt = PromptTemplate(
            template="""You are a helpful assistant that answers questions based on the provided context.
            Answer the question based ONLY on the context provided.
            If the context doesn't contain the information needed to answer the question, say "I don't have enough information to answer that question."
            Do not use any prior knowledge.

            CONTEXT:
            {context}

            QUESTION:
            {question}

            ANSWER:""",
            input_variables=["context", "question"]
        )
        logger.info("Custom prompt template created")
        # Create the conversational chain
        chain = ConversationalRetrievalChain.from_llm(
            llm=llm,
            retriever=retriever,
            memory=memory,
            # return_source_documents=True,
            combine_docs_chain_kwargs={"prompt": qa_prompt},
            output_key="answer",
        )
        
        # Run the chain
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = chain({"question": user_query})
        
        # Extract answer and sources
        answer = result.get("answer", "")
        source_documents = result.get("source_documents", [])
        
        # Format sources
        sources = format_sources(source_documents)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Generated answer in {elapsed_time:.2f} seconds")
        
        # If streaming, get the full response from the handler
        if streaming and streaming_handler:
            # The streaming_handler already sent tokens to the client
            # so we just need to return the full response for the final result
            answer = streaming_handler.get_response()
        
        return {
            "answer": answer,
            "sources": sources,
            "has_context": len(source_documents) > 0,
            "processing_time": round(elapsed_time, 2)
        }
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"Error generating answer with LangChain: {e}")
        return {
            "answer": f"I encountered an error while processing your question: {str(e)}",
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
    try:
        conversation_manager.clear_memory(conversation_id)
        return True
    except Exception as e:
        logger.error(f"Error clearing conversation {conversation_id}: {e}")
        return False


if __name__ == "__main__":
    # Example usage
    initialize_pinecone()
    
    # Test the RAG system
    query = "What is the main topic of the document?"
    print(f"Testing query: '{query}'")
    
    result = generate_answer_with_langchain(
        query,
        model=DEFAULT_MODEL,
        conversation_id="test-conversation"
    )
    
    print("\n--- RESULT ---")
    print(f"Answer: {result['answer']}")
    print(f"Sources: {result['sources']}")
    print(f"Has context: {result['has_context']}")
    print(f"Processing time: {result['processing_time']} seconds")