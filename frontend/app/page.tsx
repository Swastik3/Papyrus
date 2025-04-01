'use client';

import './globals.css';
import { useState, useRef, useCallback, useEffect } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatMessages from '@/components/ChatMessages';
import InputForm from '@/components/InputForm';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  sources?: string[];
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pdfs, setPdfs] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  // Initialize as empty string instead of null
  const [streamingContent, setStreamingContent] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [conversationId, setConversationId] = useState<string>(
    `conv-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
  );
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Separate effect for streaming content updates
  useEffect(() => {
    if (isStreaming) {
      scrollToBottom();
    }
  }, [isStreaming, streamingContent]);

  const handleSubmit = async (message: string, uploadedPdfIds?: string[]) => {
    if (!message.trim()) return;

    // Add user message to chat
    setMessages(prev => [...prev, { role: 'user', content: message }]);
    
    // Reset streaming state
    setStreamingContent("");
    setIsStreaming(true);
    setIsLoading(true);
    
    console.log("Message submitted, waiting for streaming response...");
  };

  const handleStreamToken = (token: string) => {
    console.log('%c handleStreamToken called ', 'background: #27ae60; color: white; padding: 4px;', token);
    
    // Ensure we're in streaming mode
    if (!isStreaming) {
      console.log('%c Setting isStreaming to true ', 'background: #f1c40f; color: white; padding: 4px;');
      setIsStreaming(true);
    }
    
    // Update streaming content with more visibility
    setStreamingContent(prev => {
      const newContent = prev + token;
      console.log('%c streamingContent updated ', 'background: #e67e22; color: white; padding: 4px;', 
        'Length:', newContent.length, 
        'Content (last 20 chars):', newContent.slice(-20));
      return newContent;
    });
  };

  const handleQueryResponse = (answer: string, sources: string[]) => {
    console.log("Query complete, final answer length:", answer.length);
    console.log("Current streaming content length:", streamingContent.length);
    console.log("isStreaming:", isStreaming);
    
    // IMPORTANT: Save the current streaming content to a local variable 
    // to avoid race conditions with state updates
    const finalContent = isStreaming ? streamingContent : answer;
    
    // Add the final message
    setMessages(prev => [...prev, { 
      role: 'assistant', 
      content: finalContent.length > 0 ? finalContent : answer, // Fallback to answer
      sources: sources 
    }]);
    
    // Reset streaming states
    setIsStreaming(false);
    setStreamingContent("");
    setIsLoading(false);
    
    // Ensure we scroll to bottom
    setTimeout(scrollToBottom, 50);
  };

  const handlePdfUpload = useCallback((files: File[]) => {
    const pdfFiles = files.filter(file => file.type === 'application/pdf');
    if (pdfFiles.length > 0) {
      setPdfs(prev => [...prev, ...pdfFiles]);
    }
  }, []);

  const removePdf = (index: number) => {
    setPdfs(prev => prev.filter((_, i) => i !== index));
  };

  const [isSidebarExpanded, setIsSidebarExpanded] = useState<boolean>(false);

  const handleSidebarExpandChange = (expanded: boolean) => {
    setIsSidebarExpanded(expanded);
  };

  // Debug logging for any changes to our key state variables
  useEffect(() => {
    console.log("isStreaming changed:", isStreaming);
  }, [isStreaming]);

  useEffect(() => {
    console.log("isLoading changed:", isLoading);
  }, [isLoading]);

  return (
    <div className="flex min-h-screen bg-[#0A0A0A] text-gray-100">
      {/* Sidebar component */}
      <Sidebar 
        messages={messages} 
        onExpandChange={handleSidebarExpandChange}
      />

      {/* Main chat area */}
      <div className="w-full flex transition-all duration-300 ease-in-out" style={{ paddingLeft: isSidebarExpanded ? '18rem' : 0, justifyContent: isSidebarExpanded ? 'flex-start' : 'center' }}>
        <div className="max-w-5xl flex flex-col p-4" style={{ width: isSidebarExpanded ? '100%' : '80%' }}>
          <h1 className="text-3xl font-bold text-center mb-8 text-white">Papyrus</h1>
          <div className="border-b border-gray-600 mb-8"></div>
          
          {/* Debug display to see state values */}
          {/* <div className="mb-2 text-xs text-gray-500">
            Debug: isStreaming={String(isStreaming)}, isLoading={String(isLoading)}, 
            streamingContent length={streamingContent.length}
          </div> */}
          
          {/* Chat messages component */}
          <ChatMessages 
            messages={messages} 
            isLoading={isLoading}
            streamingContent={isStreaming ? streamingContent : null}
            messagesEndRef={messagesEndRef} 
          />
          
          {/* Input form component */}
          <InputForm 
            onSubmit={handleSubmit} 
            pdfs={pdfs}
            onPdfUpload={handlePdfUpload}
            onRemovePdf={removePdf}
            onQueryResponse={handleQueryResponse}
            onStreamToken={handleStreamToken}
            conversationId={conversationId}
          />
        </div>
      </div>
    </div>
  );
}