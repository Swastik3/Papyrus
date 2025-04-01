import React, { useEffect, useRef } from 'react';
import { Message } from '../app/page';

interface ChatMessagesProps {
  messages: Message[];
  isLoading: boolean;
  streamingContent: string | null;
  messagesEndRef: React.RefObject<HTMLDivElement>;
}

const ChatMessages: React.FC<ChatMessagesProps> = ({ 
  messages, 
  isLoading, 
  streamingContent,
  messagesEndRef 
}) => {
  // Reference for the streaming message
  const streamingRef = useRef<HTMLDivElement>(null);
  
  // Auto-scroll when streaming content changes
  useEffect(() => {
    if (streamingContent !== null && streamingContent !== "") {
      // Use requestAnimationFrame to ensure smooth scrolling during streaming
      requestAnimationFrame(() => {
        if (streamingRef.current) {
          streamingRef.current.scrollIntoView({ behavior: "smooth" });
        }
      });
    }
  }, [streamingContent]);

  return (
    <div className="flex-1 overflow-y-auto mb-4 space-y-4">
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
                  {message.sources.map((source, i) => (
                    <li key={i} className="flex items-center">
                      <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-2"></span>
                      {source}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      ))}
      
      {/* Streaming content with improved animation */}
      {streamingContent !== null && (
        <div className="flex justify-start animate-fadeIn">
          <div className="bg-[#1A1A1A] rounded-lg py-3 px-5 max-w-[70%]">
            <p className="text-gray-200 whitespace-pre-line">{streamingContent}</p>
            {/* Improved blinking cursor with better animation */}
            <span className="inline-block ml-1 w-2 h-4 bg-blue-400 animate-cursor-blink"></span>
            <div ref={streamingRef}></div>
          </div>
        </div>
      )}
      
      {/* Loading indicator (only shown if not streaming) */}
      {isLoading && streamingContent === null && (
        <div className="flex justify-start">
          <div className="bg-[#1A1A1A] rounded-lg p-4">
            <div className="flex space-x-2">
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" />
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-100" />
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-200" />
            </div>
          </div>
        </div>
      )}
      
      <div ref={messagesEndRef} />
    </div>
  );
};

export default ChatMessages;