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
  const [hoveredCitation, setHoveredCitation] = useState<string | null>(null);
  
  // Auto-scroll when streaming content changes
  useEffect(() => {
    if (streamingContent !== null && streamingRef.current) {
      streamingRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [streamingContent]);
  
  // Trigger citation preview loading when hovering
  useEffect(() => {
    if (hoveredCitation && onCitationHover) {
      onCitationHover(hoveredCitation);
    }
  }, [hoveredCitation, onCitationHover]);

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
            }`}
          >
            <p className="text-gray-200 whitespace-pre-line">{message.content}</p>
            {message.sources && message.sources.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-700">
                <p className="text-xs text-gray-400">Sources:</p>
                <ul className="mt-1 text-xs text-gray-400">
                  {message.sources.map((source, i) => {
                    const { filename, page } = parseCitationSource(source);
                    return (
                      <li 
                        key={i} 
                        className="flex items-center relative mb-1 group"
                      >
                        <button
                          onClick={() => onCitationClick && onCitationClick(filename, page)}
                          onMouseEnter={() => setHoveredCitation(source)}
                          onMouseLeave={() => setHoveredCitation(null)}
                          className="flex items-center hover:text-blue-300 transition-colors w-full text-left"
                        >
                          <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-2 flex-shrink-0"></span>
                          <span className="truncate">{source}</span>
                        </button>
                        
                        {/* Citation preview tooltip */}
                        {hoveredCitation === source && (
                          <div className="absolute left-0 bottom-full mb-2 bg-gray-800 p-3 rounded shadow-lg z-10 max-w-xs text-xs text-gray-200 break-words">
                            <div className="font-medium mb-1 text-blue-300">{filename}</div>
                            {citationPreviews[source] ? (
                              <>
                                <p className="opacity-90 line-clamp-4">{citationPreviews[source].text}</p>
                                <p className="text-gray-400 mt-1 text-right italic">Click to view PDF</p>
                              </>
                            ) : (
                              <p className="opacity-90">Loading preview...</p>
                            )}
                            <div className="absolute left-3 bottom-[-6px] w-3 h-3 bg-gray-800 transform rotate-45"></div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
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
      
      {/* Loading indicator (only shown if not streaming) */}
      {isLoading && !streamingContent && (
        <div className="flex justify-start">
          <div className="bg-[#1A1A1A] rounded-lg p-4">
            <div className="flex space-x-2">
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"></div>
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-100"></div>
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-200"></div>
            </div>
          </div>
        </div>
      )}
      
      <div ref={messagesEndRef}></div>
    </div>
  );
};

export default ChatMessages;