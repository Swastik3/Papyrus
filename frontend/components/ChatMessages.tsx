/* components/ChatMessages.tsx */
import React, { useEffect, useRef, useState } from 'react';
import { Message } from '../app/page';

interface CitationPreview {
  source: string;
  text: string;
  fileName: string;
  page?: number;
}

interface ChatMessagesProps {
  messages: Message[];
  isLoading: boolean;
  streamingContent: string | null;
  messagesEndRef: React.RefObject<HTMLDivElement>;
  onCitationClick?: (source: string, page?: number) => void;
  onCitationHover?: (source: string) => void;
  citationPreviews?: Record<string, CitationPreview>;
}

const ChatMessages: React.FC<ChatMessagesProps> = ({ 
  messages, 
  isLoading, 
  streamingContent,
  messagesEndRef,
  onCitationClick,
  onCitationHover,
  citationPreviews = {}
}) => {
  // Reference for the streaming message
  const streamingRef = useRef<HTMLDivElement>(null);
  const [hoveredCitationId, setHoveredCitationId] = useState<string | null>(null);
  
  // Auto-scroll when streaming content changes
  useEffect(() => {
    if (streamingContent !== null && streamingRef.current) {
      streamingRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [streamingContent]);
  
  // Trigger citation preview loading when hovering
  useEffect(() => {
    if (hoveredCitationId && onCitationHover) {
      // Extract the actual citation text from the ID
      const citationText = hoveredCitationId.split('|')[1];
      if (citationText) {
        onCitationHover(citationText);
      }
    }
  }, [hoveredCitationId, onCitationHover]);

  // Parse source string to extract filename and page number
  const parseCitationSource = (source: string): { filename: string; page?: number } => {
    // Simple approach to extract PDF filename
    const pdfMatch = source.match(/(.+?\.pdf)/i);
    let filename = pdfMatch ? pdfMatch[1] : source;
    
    // Extract page if it exists
    const pageMatch = source.match(/\(page (\d+(?:\.\d+)?)\)/);
    const page = pageMatch ? parseInt(pageMatch[1], 10) : undefined;
    
    // If no PDF extension found, add it
    if (!filename.toLowerCase().endsWith('.pdf')) {
      filename = `${filename}.pdf`;
    }
    
    return { filename, page };
  };

  // Helper function to render structured paragraphs with citations
  const renderStructuredParagraph = (paragraph: any, paragraphIndex: number, citationStartIndex: number, messageIndex: number) => {
    if (!paragraph.sources || paragraph.sources.length === 0) {
      return {
        element: <p className="text-gray-200 whitespace-pre-line mb-3" key={paragraphIndex}>{paragraph.text}</p>,
        nextCitationIndex: citationStartIndex
      };
    }

    // Filter out sources that don't have file names
    const validSources = paragraph.sources.filter((source: any) => 
      source.file_name !== null && source.key !== "general_knowledge"
    );

    if (validSources.length === 0) {
      return {
        element: <p className="text-gray-200 whitespace-pre-line mb-3" key={paragraphIndex}>{paragraph.text}</p>,
        nextCitationIndex: citationStartIndex
      };
    }

    // Current index for citation numbers
    let currentCitationIndex = citationStartIndex;

    return {
      element: (
        <div className="mb-4" key={paragraphIndex}>
          <p className="text-gray-200 whitespace-pre-line">
            {paragraph.text}
            <span className="inline-flex ml-1 gap-1">
              {validSources.map((source: any, idx: number) => {
                const sourceText = `${source.file_name}${source.page_number ? ` (page ${source.page_number})` : ''}`;
                const citationNumber = currentCitationIndex++;
                // Include messageIndex parameter in the ID to make it unique across all messages
                const citationId = `msg-${messageIndex}-para-${paragraphIndex}-citation-${idx}|${sourceText}`;
                
                return (
                  <button
                    key={idx}
                    onClick={() => onCitationClick && source.file_name && 
                      onCitationClick(source.file_name, source.page_number || undefined)}
                    onMouseEnter={() => setHoveredCitationId(citationId)}
                    onMouseLeave={() => setHoveredCitationId(null)}
                    className="inline-flex items-center justify-center h-5 w-5 text-xs bg-blue-600 hover:bg-blue-700 
                      text-white rounded-full font-medium transition-colors relative"
                    title={sourceText}
                  >
                    {citationNumber}
                    
                    {/* Enhanced tooltip on hover - MUCH wider and taller for citations */}
                    {hoveredCitationId === citationId && (
                      <div className="absolute left-0 bottom-full mb-2 bg-gray-800 p-4 rounded shadow-lg z-10 min-w-[200px] max-w-[600px] w-auto text-sm text-gray-200 break-words">
                        <div className="font-medium mb-2 text-blue-300 text-base">{sourceText}</div>
                        {/* Larger text preview with more lines visible */}
                        <p className="opacity-90 line-clamp-8 max-h-[300px] overflow-y-auto">
                          {source.text ? 
                            (source.text.length > 150 ? 
                              `${source.text.substring(0, 150)}...` : 
                              source.text) : 
                            "No preview available"}
                        </p>
                        <p className="text-gray-400 mt-2 text-right italic">Click number to view PDF</p>
                        <div className="absolute left-3 bottom-[-6px] w-3 h-3 bg-gray-800 transform rotate-45"></div>
                      </div>
                    )}
                  </button>
                );
              })}
            </span>
          </p>
        </div>
      ),
      nextCitationIndex: currentCitationIndex
    };
  };

  // Helper function to render sources section at the bottom of each message
  const renderSourcesSection = (message: Message, messageIndex: number) => {
    // Extract unique sources from paragraphs
    if (!message.paragraphs) return null;
    
    const allSources: any[] = [];
    
    message.paragraphs.forEach(paragraph => {
      paragraph.sources.forEach((source: any) => {
        if (source.file_name && source.key !== "general_knowledge") {
          // Check if we already have this source in our list by file_name and page_number
          const exists = allSources.some(
            s => s.file_name === source.file_name && s.page_number === source.page_number
          );
          
          if (!exists) {
            allSources.push(source);
          }
        }
      });
    });
    
    if (allSources.length === 0) return null;
    
    return (
      <div className="mt-2 pt-2 border-t border-gray-700">
        <p className="text-xs text-gray-400">Sources:</p>
        <ul className="mt-1 text-xs text-gray-400">
          {allSources.map((source, i) => {
            const sourceText = `${source.file_name}${source.page_number ? ` (page ${source.page_number})` : ''}`;
            // Include message index in source list citation ID to make it unique across all messages
            const sourceListCitationId = `msg-${messageIndex}-source-list-${i}|${sourceText}`;
            
            return (
              <li 
                key={i} 
                className="flex items-center relative mb-1 group"
              >
                <button
                  onClick={() => onCitationClick && source.file_name && 
                    onCitationClick(source.file_name, source.page_number || undefined)}
                  onMouseEnter={() => setHoveredCitationId(sourceListCitationId)}
                  onMouseLeave={() => setHoveredCitationId(null)}
                  className="flex items-center hover:text-blue-300 transition-colors w-full text-left relative"
                >
                  <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-2 flex-shrink-0"></span>
                  <span className="truncate">{sourceText}</span>
                  
                  {/* Enhanced source list tooltip - wider and taller */}
                  {hoveredCitationId === sourceListCitationId && (
                    <div className="absolute left-0 bottom-full mb-2 bg-gray-800 p-4 rounded shadow-lg z-10 min-w-[400px] max-w-[600px] w-auto text-sm text-gray-200 break-words">
                      <div className="font-medium mb-2 text-blue-300 text-base">{sourceText}</div>
                      <p className="opacity-90 line-clamp-8 max-h-[300px] overflow-y-auto">
                        {source.text ? 
                          (source.text.length > 250 ? 
                            `${source.text.substring(0, 250)}...` : 
                            source.text) : 
                          "No preview available"}
                      </p>
                      <p className="text-gray-400 mt-2 text-right italic">Click to view PDF</p>
                      <div className="absolute left-3 bottom-[-6px] w-3 h-3 bg-gray-800 transform rotate-45"></div>
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );
  };

  return (
    <div className="flex-1 overflow-y-auto mb-4 space-y-4">
      {/* Regular messages */}
      {messages.map((message, index) => (
        <div
          key={index}
          className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          <div
            className={`max-w-[70%] rounded-lg py-3 px-5 ${
              message.role === 'user' ? 'bg-[#2A2A2A]' : 'bg-[#1A1A1A]'
            } relative`}
          >
            {/* Render user messages normally */}
            {message.role === 'user' ? (
              <p className="text-gray-200 whitespace-pre-line">{message.content}</p>
            ) : (
              <>
                {/* Render assistant messages with structured paragraphs if available */}
                {message.paragraphs && message.paragraphs.length > 0 ? (
                  <>
                    {(() => {
                      // Track citation numbering across paragraphs
                      let citationIndex = 1;
                      const paragraphElements = [];
                      
                      // Render each paragraph and update the citation index
                      for (let i = 0; i < message.paragraphs.length; i++) {
                        const { element, nextCitationIndex } = renderStructuredParagraph(
                          message.paragraphs[i], 
                          i, 
                          citationIndex,
                          index // Pass message index to make citations unique across all messages
                        );
                        
                        paragraphElements.push(element);
                        citationIndex = nextCitationIndex;
                      }
                      
                      return paragraphElements;
                    })()}
                    {renderSourcesSection(message, index)}
                  </>
                ) : (
                  <>
                    {/* Fallback for non-structured assistant messages */}
                    <p className="text-gray-200 whitespace-pre-line">{message.content}</p>
                    {message.sources && message.sources.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-gray-700">
                        <p className="text-xs text-gray-400">Sources:</p>
                        <ul className="mt-1 text-xs text-gray-400">
                          {message.sources.map((source, i) => {
                            // Parse source string to get filename and page
                            const { filename, page } = parseCitationSource(source);
                            // Make sure fallback citation IDs include a timestamp to make them truly unique
                            const fallbackCitationId = `unique-${Date.now()}-fallback-msg-${index}-source-${i}|${source}`;
                            
                            return (
                              <li 
                                key={i} 
                                className="flex items-center relative mb-1 group"
                              >
                                <button
                                  onClick={() => onCitationClick && onCitationClick(filename, page)}
                                  onMouseEnter={() => setHoveredCitationId(fallbackCitationId)}
                                  onMouseLeave={() => setHoveredCitationId(null)}
                                  className="flex items-center hover:text-blue-300 transition-colors w-full text-left relative"
                                >
                                  <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-2 flex-shrink-0"></span>
                                  <span className="truncate">{source}</span>
                                  
                                  {/* Enhanced fallback source list tooltip */}
                                  {hoveredCitationId === fallbackCitationId && (
                                    <div className="absolute left-0 bottom-full mb-2 bg-gray-800 p-4 rounded shadow-lg z-10 min-w-[400px] max-w-[600px] w-auto text-sm text-gray-200 break-words">
                                      <div className="font-medium mb-2 text-blue-300 text-base">{source}</div>
                                      {citationPreviews[source] ? (
                                        <>
                                          <p className="opacity-90 line-clamp-8 overflow-y-auto">{citationPreviews[source].text}</p>
                                          <p className="text-gray-400 mt-2 text-right italic">Click to view PDF</p>
                                        </>
                                      ) : (
                                        <p className="opacity-90">Loading preview...</p>
                                      )}
                                      <div className="absolute left-3 bottom-[-6px] w-3 h-3 bg-gray-800 transform rotate-45"></div>
                                    </div>
                                  )}
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      ))}
      
      {/* Streaming content */}
      {streamingContent !== null && (
        <div className="flex justify-start">
          <div className="bg-[#1A1A1A] rounded-lg py-3 px-5 max-w-[70%]">
            <p className="text-gray-200 whitespace-pre-line">{streamingContent}</p>
            <div className="mt-2 flex space-x-1">
              <div className="w-1 h-1 bg-gray-500 rounded-full animate-pulse"></div>
              <div className="w-1 h-1 bg-gray-500 rounded-full animate-pulse delay-75"></div>
              <div className="w-1 h-1 bg-gray-500 rounded-full animate-pulse delay-150"></div>
            </div>
            <div ref={streamingRef}></div>
          </div>
        </div>
      )}
      
      <div ref={messagesEndRef}></div>
    </div>
  );
};

export default ChatMessages;