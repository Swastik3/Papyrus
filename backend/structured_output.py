import os
import json
import logging
import time
from typing import List, Dict, Tuple, Optional, Any, Union
from datetime import datetime
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from rag_utils import get_relevant_context
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DEFAULT_MODEL = "gpt-4o-mini"
SIMILARITY_THRESHOLD = 0.7  # Example value, replace with your actual threshold

class Source(BaseModel):
    """Model for a single source reference"""
    key: str = Field(..., description="Source key identifier")
    file_name: Optional[str] = Field(None, description="Name of the source file")
    page_number: Optional[int] = Field(None, description="Page number in the source document")
    text: Optional[str] = Field(None, description="Original text from the source")


class Paragraph(BaseModel):
    """Model for a paragraph with its sources"""
    text: str = Field(..., description="Full text content of the paragraph")
    sources: List[Source] = Field(default_factory=list, description="List of sources used in this paragraph")


class StructuredMessage(BaseModel):
    """Model for a complete structured message with role, content and paragraphs"""
    role: str = Field(..., description="Message role (e.g., 'assistant')")
    content: str = Field(..., description="Plain text content of the entire message")
    paragraphs: List[Paragraph] = Field(..., description="List of structured paragraphs with sources")


class ResponseTracking(BaseModel):
    """Model for the response tracking part of the LLM response"""
    paragraphs: List[Dict] = Field(..., description="List of paragraphs with their source keys")


class LLMResponse(BaseModel):
    """Model for the complete response from the LLM"""
    answer: str = Field(..., description="The complete answer text")
    response_tracking: ResponseTracking = Field(..., description="Tracking information with paragraph sources")


def validate_structured_message(message: Dict[str, Any]) -> Union[StructuredMessage, Dict[str, str]]:
    """
    Validates a structured message against the expected schema
    
    Args:
        message: Dictionary containing the structured message data
        
    Returns:
        Either a validated StructuredMessage object or an error dictionary
    """
    try:
        validated_message = StructuredMessage.model_validate(message)
        return validated_message
    except Exception as e:
        return {"error": f"Invalid structured message format: {str(e)}"}


def validate_llm_response(response_json: Dict[str, Any]) -> Union[LLMResponse, Dict[str, str]]:
    """
    Validates the raw JSON response from the LLM
    
    Args:
        response_json: Dictionary containing the response tracking data
        
    Returns:
        Either a validated LLMResponse object or an error dictionary
    """
    try:
        validated_response = LLMResponse.model_validate(response_json)
        return validated_response
    except Exception as e:
        return {"error": f"Invalid LLM response format: {str(e)}"}


# Mock function to simulate get_relevant_context
def get_relevant_context_mock(user_query: str, conversation_id: str, threshold: float = SIMILARITY_THRESHOLD, max_results: int = 5) -> Tuple[List[Dict], List[str]]:
    """
    Mock implementation of get_relevant_context
    
    In a real implementation, this would perform a similarity search
    against a vector database like Pinecone.
    
    Args:
        user_query: User's question
        conversation_id: ID of the conversation
        threshold: Similarity threshold
        max_results: Maximum number of results
        
    Returns:
        Tuple of (context_chunks, sources)
    """
    # For testing purposes, return mock data
    context_chunks = [
        {
            "text": "Solar panels work by converting sunlight into electricity through the photovoltaic effect. When photons hit a solar cell, they knock electrons loose from atoms, generating a flow of electricity.",
            "metadata": {
                "source": "renewable_energy.pdf",
                "page_number": 12
            }
        },
        {
            "text": "Modern solar panels typically have efficiency ratings between 15-22%. The theoretical maximum efficiency for silicon solar cells is around 33% due to physical constraints.",
            "metadata": {
                "source": "renewable_energy.pdf", 
                "page_number": 14
            }
        },
        {
            "text": "The cost of solar installations has dropped by more than 70% over the past decade, making solar energy increasingly competitive with fossil fuels in many markets.",
            "metadata": {
                "source": "energy_economics.pdf",
                "page_number": 23
            }
        }
    ]
    
    sources = ["renewable_energy.pdf", "energy_economics.pdf"]
    
    logger.info(f"Retrieved {len(context_chunks)} context chunks for query: '{user_query}'")
    return context_chunks, sources

def convert_context_format(context_chunks):
    """
    Convert the context chunks from your format to the format expected by generate_answer_with_structured_context
    
    Args:
        context_chunks: List of dictionaries with text and source information
        
    Returns:
        List of dictionaries with text and metadata
    """
    converted_chunks = []
    
    for chunk in context_chunks:
        print("Page number extracted: ", chunk.get("page", 0))
        converted_chunk = {
            "text": chunk.get("text", ""),
            "metadata": {
                "source": chunk.get("source", "unknown"),
                "page_number": chunk.get("page", 0)
            }
        }
        converted_chunks.append(converted_chunk)
    
    return converted_chunks


def generate_answer_with_structured_context(
    user_query: str, 
    model: str = DEFAULT_MODEL,
    conversation_id: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Generate an answer to a user query with structured paragraph-source mapping
    
    Args:
        user_query: The user's question
        model: The OpenAI model to use for generating the answer
        conversation_id: Optional ID to keep track of conversation history
        conversation_history: Optional list of previous conversation messages
        
    Returns:    
        Dictionary containing the answer, structured data, and sources
    """
    start_time = time.time()
    logger.info(f"Generating structured answer for query: '{user_query}' with model {model}")
    
    try:
        # Get relevant context using your function
        raw_context_chunks, sources = get_relevant_context(user_query, conversation_id=conversation_id)
        
        # Convert your context format to the format expected by this function
        context_chunks = convert_context_format(raw_context_chunks)
        
        # If no relevant context found
        if not context_chunks:
            context_prompt = f"""You are answering a question generally.
                    
                    You must respond with a JSON object that follows this exact structure:
                    {{
                      "answer": "Your full answer here as a single string with all paragraphs included",
                      "response_tracking": {{
                        "paragraphs": [
                          {{
                            "text": "The full text of paragraph 1 of your answer and not the context",
                            "source_keys": ["general_knowledge"]
                          }},
                          {{
                            "text": "The full text of paragraph 2 of your answer and not the context",
                            "source_keys": ["general_knowledge"]
                          }}
                        ]
                      }}
                    }}
                    
                    Since no specific context is provided, mark all source_keys as "general_knowledge".
                    Ensure the paragraphs in response_tracking match exactly with how you would split your answer.
                    
                    QUESTION:
                    {user_query}
                    """
            has_context = False
            
        # Create prompt with context dictionary
        else:
            # Create a dictionary of context chunks for easier reference
            context_dict = {}
            for i, chunk in enumerate(context_chunks):
                chunk_key = f"chunk_{i}"
                context_dict[chunk_key] = {
                    "text": chunk.get("text", ""),
                    "metadata": {
                        "source": chunk.get("metadata", {}).get("source", "unknown"),
                        "page_number": chunk.get("metadata", {}).get("page_number", 0)
                    }
                }
            
            # Format the context for the prompt
            formatted_context = "\n\n".join([
                f"[{key}] {value['text']}" 
                for key, value in context_dict.items()
            ])
            
            context_prompt = f"""You are answering a question based on specific context provided.
                    Answer the question based ONLY on the context provided.
                    If the context doesn't contain the information needed to answer that question, say that you don't have enough information to answer that question, answer it generally and the source_key should simply be general_knowledge.
                    Do not use any prior knowledge outside what is provided in the context or conversation history.
                    
                    You must respond with a JSON object that follows this exact structure:
                    {{
                      "answer": "Your full answer here as a single string with all paragraphs included",
                      "response_tracking": {{
                        "paragraphs": [
                          {{
                            "text": "The full text of paragraph 1 of your answer and not the context",
                            "source_keys": ["chunk_0", "chunk_2"]
                          }},
                          {{
                            "text": "The full text of paragraph 2 of your answer and not the context",
                            "source_keys": ["chunk_1"]
                          }}
                        ]
                      }}
                    }}
                    
                    Each context chunk has a key like "chunk_0", "chunk_1", etc. In your response, reference these exact keys.
                    If a paragraph doesn't use any specific context, use "source_keys": ["general_knowledge"].
                    Ensure the paragraphs in response_tracking match exactly with how you would split your answer.
                    
                    CONTEXT:
                    {formatted_context}
                    
                    CONTEXT KEYS AND METADATA:
                    {str(context_dict)}
                    
                    QUESTION:
                    {user_query}
                    """
            has_context = True
        
        # Initialize OpenAI client
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Prepare messages with conversation history if available
        messages = []
        if conversation_history and len(conversation_history) > 0:
            # Add existing conversation history
            messages = conversation_history.copy()
            # Add the context prompt as the latest user message
            messages.append({"role": "user", "content": context_prompt})
        else:
            # No conversation history, just use system message and the prompt
            messages = [
                {"role": "system", "content": "You are a helpful assistant that answers questions based on specific context provided."},
                {"role": "user", "content": context_prompt}
            ]
        
        # Prepare request parameters with response_format to enforce JSON
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"}
        }
        
        # Generate answer with OpenAI
        logger.info(f"Sending request to OpenAI API with model: {model}")
        completion = client.chat.completions.create(**request_params)
        full_response = completion.choices[0].message.content
        
        # Process the response, which should now be a JSON string
        try:
            # Parse the JSON response
            response_data = json.loads(full_response)
            
            # Validate the response structure
            validation_result = validate_llm_response(response_data)
            
            if isinstance(validation_result, dict) and "error" in validation_result:
                logger.warning(f"LLM response validation failed: {validation_result['error']}")
                # Continue with best effort parsing
            else:
                logger.info("LLM response validation successful")
                
            # Extract the answer text
            print("Response data: ", response_data)
            answer_text = response_data.get("answer", "")
            
            # Process the structured data
            structured_paragraphs = []
            
            tracking_data = response_data.get("response_tracking", {})
            
            for para in tracking_data.get("paragraphs", []):
                para_text = para.get("text", "")
                source_keys = para.get("source_keys", ["general_knowledge"])
                
                # Build the sources info with full context details
                sources_info = []
                for key in source_keys:
                    if key == "general_knowledge":
                        sources_info.append({
                            "key": "general_knowledge",
                            "file_name": None,
                            "page_number": None,
                            "text": None
                        })
                    elif has_context and key in context_dict:
                        try:
                            sources_info.append({
                                "key": key,
                                "file_name": context_dict[key]["metadata"]["source"],
                                "page_number": context_dict[key]["metadata"]["page_number"],
                                "text": context_dict[key]["text"]
                            })
                        except KeyError as e:
                            logger.warning(f"KeyError accessing context_dict[{key}]: {e}")
                            # More detailed logging to debug structure
                            logger.warning(f"context_dict[{key}] structure: {json.dumps(context_dict[key], default=str)}")
                            # Fallback with as much information as we can recover
                            sources_info.append({
                                "key": key,
                                "file_name": context_dict[key]["metadata"].get("source", None),
                                "page_number": context_dict[key]["metadata"].get("page_number", None),
                                "text": context_dict[key].get("text", None)
                            })
                    else:
                        # Handle unknown keys
                        sources_info.append({
                            "key": key,
                            "file_name": None,
                            "page_number": None,
                            "text": None
                        })
                
                structured_paragraphs.append({
                    "text": para_text,
                    "sources": sources_info
                })
            
            # If no paragraphs were found in the tracking data, use the whole answer as one paragraph
            if not structured_paragraphs:
                structured_paragraphs = [{
                    "text": answer_text,
                    "sources": []
                }]
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            # Fallback if JSON parsing fails
            answer_text = full_response
            structured_paragraphs = [{
                "text": full_response,
                "sources": [{"key": "parsing_error", "file_name": None, "page_number": None, "text": None}]
            }]
        
        # Create the structured message
        structured_message = {
            "role": "assistant",
            "content": answer_text,
            "paragraphs": structured_paragraphs
        }
        
        # Validate the structured message
        validation_result = validate_structured_message(structured_message)
        
        if isinstance(validation_result, dict) and "error" in validation_result:
            logger.warning(f"Structured message validation failed: {validation_result['error']}")
            # Add error info to the response
            structured_message["validation_error"] = validation_result["error"]
        else:
            logger.info("Structured message validation successful")
        
        elapsed_time = time.time() - start_time
        logger.info(f"Generated structured answer in {elapsed_time:.2f} seconds")
        
        return {
            "answer": answer_text,
            "structured_data": structured_paragraphs,
            "sources": sources,
            "has_context": has_context,
            "processing_time": round(elapsed_time, 2),
            "structured_message": structured_message,
            "raw_response": full_response
        }
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"Error generating structured answer: {e}")
        
        error_message = f"I encountered an error while processing your question: {str(e)}"
        
        return {
            "answer": error_message,
            "structured_data": [],
            "sources": [],
            "has_context": False,
            "processing_time": round(elapsed_time, 2),
            "error": str(e)
        }


def main():
    """
    Test function to demonstrate the structured output generation
    """
    # Check if OpenAI API key is available
    if not os.getenv('OPENAI_API_KEY'):
        print("Error: OPENAI_API_KEY environment variable is not set")
        print("Please set your OpenAI API key with: export OPENAI_API_KEY='your-api-key'")
        return
    
    # Test query
    query = input("Enter your question: ") or "How do solar panels work and what's their efficiency?"
    conversation_id = input("Enter conversation ID (or press Enter for default): ") or "test-conversation"
    model = input("Enter model name (or press Enter for default): ") or DEFAULT_MODEL
    
    print(f"\nGenerating structured answer for query: '{query}'")
    print(f"Using model: {model}")
    print(f"Conversation ID: {conversation_id}\n")
    
    # Generate the answer
    result = generate_answer_with_structured_context(
        user_query=query,
        model=model,
        conversation_id=conversation_id
    )
    
    # Print the result
    print("\n=============== ANSWER ===============")
    print(result["answer"])
    
    print("\n=============== STRUCTURED DATA ===============")
    for i, para in enumerate(result["structured_data"]):
        print(f"\nParagraph {i+1}: {para['text']}")
        print("Sources:")
        for source in para["sources"]:
            print(f"  - Key: {source['key']}")
            if source["file_name"]:
                print(f"    File: {source['file_name']}")
            if source["page_number"]:
                print(f"    Page: {source['page_number']}")
            if source["text"]:
                print(f"    Text: {source['text'][:50]}...")
    
    print("\n=============== VALIDATION ===============")
    if "validation_error" in result.get("structured_message", {}):
        print(f"Validation Error: {result['structured_message']['validation_error']}")
    else:
        print("Validation: Successful")
    
    print("\n=============== RAW RESPONSE ===============")
    print(result.get("raw_response", "N/A"))
    
    print("\n=============== SUMMARY ===============")
    print(f"Processing Time: {result['processing_time']} seconds")
    print(f"Has Context: {result['has_context']}")
    print(f"Sources: {result['sources']}")
    
    # Save the result to a file
    with open("structured_output_result.json", "w") as f:
        json.dump(result, f, indent=2)
    
    print("\nResult saved to structured_output_result.json")


if __name__ == "__main__":
    main()