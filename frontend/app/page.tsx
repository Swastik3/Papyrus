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
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string>(
    `conv-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
  );
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingContent]);

  const handleSubmit = async (message: string, uploadedPdfIds?: string[]) => {
    if (!message.trim()) return;

    // Add user message to chat
    setMessages(prev => [...prev, { role: 'user', content: message }]);
    setIsLoading(true);
  };

  const handleStreamStart = () => {
    // Clear any previous streaming content
    setStreamingContent('');
  };

  const handleStreamToken = (token: string) => {
    setStreamingContent(prev => (prev === null ? token : prev + token));
    scrollToBottom();
  };

  const handleStreamEnd = (answer: string, sources: string[]) => {
    // Add completed message to chat
    setMessages(prev => [...prev, { 
      role: 'assistant', 
      content: answer,
      sources: sources 
    }]);
    
    // Clear streaming content
    setStreamingContent(null);
    setIsLoading(false);
    scrollToBottom();
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
          
          {/* Chat messages component */}
          <ChatMessages 
            messages={messages} 
            isLoading={isLoading}
            streamingContent={streamingContent}
            messagesEndRef={messagesEndRef} 
          />
          
          {/* Input form component */}
          <InputForm 
            onSubmit={handleSubmit} 
            pdfs={pdfs}
            onPdfUpload={handlePdfUpload}
            onRemovePdf={removePdf}
            onStreamStart={handleStreamStart}
            onStreamToken={handleStreamToken}
            onStreamEnd={handleStreamEnd}
            conversationId={conversationId}
          />
        </div>
      </div>
    </div>
  );
}