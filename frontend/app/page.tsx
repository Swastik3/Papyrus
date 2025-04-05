/* app/page.tsx */
'use client';

import './globals.css';
import { useState, useRef, useCallback, useEffect } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatMessages from '@/components/ChatMessages';
import InputForm from '@/components/InputForm';
import PDFViewer from '@/components/PDFViewer';
import { citationService } from '@/lib/CitationService';

export interface Source {
  key: string;
  file_name: string | null;
  page_number: number | null;
  text: string | null;
}

export interface Paragraph {
  text: string;
  sources: Source[];
}

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources?: string[];
  paragraphs?: Paragraph[]; // Add support for structured paragraphs
}

interface ConversationMessages {
  [conversationId: string]: Message[];
}

interface CitationPreview {
  source: string;
  text: string;
  fileName: string;
  page?: number;
}

export default function Home() {
  // Store messages for multiple conversations
  const [conversationsMessages, setConversationsMessages] = useState<ConversationMessages>({});
  
  // Active conversation messages
  const [messages, setMessages] = useState<Message[]>([]);
  
  const [pdfs, setPdfs] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [streamingContent, setStreamingContent] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  
  // PDF Viewer state
  const [activePdf, setActivePdf] = useState<{ url: string; fileName: string; page?: number } | null>(null);
  const [showPdfViewer, setShowPdfViewer] = useState<boolean>(false);
  
  // Citation preview state
  const [citationPreviews, setCitationPreviews] = useState<Record<string, CitationPreview>>({});
  
  // Initialize with a default ID - will be replaced on client side after mount
  const [conversationId, setConversationId] = useState<string>(
    `conv-default`
  );
  
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Handle localStorage only after component mounts on client side
  useEffect(() => {
    // This code only runs on the client after mount
    const savedId = localStorage.getItem('currentConversationId');
    if (savedId) {
      console.log("Loading existing conversation ID from localStorage:", savedId);
      setConversationId(savedId);
    } else {
      // Create a new ID only if none exists
      const newId = `conv-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      console.log("Creating and saving new conversation ID:", newId);
      localStorage.setItem('currentConversationId', newId);
      setConversationId(newId);
    }
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (isStreaming) {
      scrollToBottom();
    }
  }, [isStreaming, streamingContent]);

  // Skip loading messages until we have a proper conversation ID
  useEffect(() => {
    // Only load messages once we have a real conversation ID (not the default one)
    if (conversationId && conversationId !== 'conv-default') {
      console.log("Loading messages for conversation:", conversationId);
      
      // First, check if we already have messages for this conversation in state
      if (conversationsMessages[conversationId]) {
        setMessages(conversationsMessages[conversationId]);
      } else {
        // Otherwise, fetch them from the server
        fetchConversationMessages(conversationId);
      }
    }
  }, [conversationId, conversationsMessages]);

  // Function to handle citation click
  const handleCitationClick = useCallback((source: string, page?: number) => {
    console.log(`Citation clicked: "${source}"`);
    
    // Parse the source to get just the filename without page info
    const { filename, page: parsedPage } = citationService.parseCitationSource(source);
    const pageToUse = page || parsedPage;
    
    console.log(`Parsed citation: filename="${filename}", page=${pageToUse}`);
    
    // Make sure we're using properly encoded filename
    const pdfUrl = citationService.getPdfUrl(filename, conversationId);
    
    console.log("Full PDF URL:", pdfUrl);
    
    setActivePdf({
      url: pdfUrl,
      fileName: filename,
      page: pageToUse
    });
    
    setShowPdfViewer(true);
  }, [conversationId]);
  
  // Function to handle citation hover to load preview text
  const handleCitationHover = useCallback(async (source: string) => {
    // Check if we already have this citation preview
    if (citationPreviews[source]) {
      return;
    }
    
    try {
      // Fetch the citation text
      const response = await citationService.getCitationText(source, conversationId);
      
      if (response && !response.error) {
        const { filename, page } = citationService.parseCitationSource(source);
        
        // Add to citation previews
        setCitationPreviews(prev => ({
          ...prev,
          [source]: {
            source,
            text: response.text,
            fileName: filename,
            page
          }
        }));
      }
    } catch (error) {
      console.error('Error fetching citation preview:', error);
    }
  }, [citationPreviews, conversationId]);

  // Only update localStorage when the ID changes after initialization
  useEffect(() => {
    // Skip initial default ID and only update for real conversation IDs
    if (typeof window !== 'undefined' && conversationId && conversationId !== 'conv-default') {
      console.log("Updating localStorage with conversation ID:", conversationId);
      localStorage.setItem('currentConversationId', conversationId);
    }
  }, [conversationId]);

  // Function to fetch messages for a specific conversation
  const fetchConversationMessages = async (id: string) => {
    try {
      setIsLoading(true);
      console.log("Fetching messages for conversation:", id);
      
      // Call backend API to get conversation messages
      const response = await fetch(`http://localhost:5001/api/conversation-messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          conversationId: id
        })
      });
      
      if (!response.ok) {
        throw new Error('Failed to fetch conversation messages');
      }
      
      const data = await response.json();
      
      // Transform backend message format to our format if necessary
      const formattedMessages = data.messages.filter((msg: any) => 
        msg.role !== 'system' // Filter out system messages
      ).map((msg: any) => ({
        role: msg.role,
        content: msg.content,
        sources: msg.sources || [],
        paragraphs: msg.paragraphs || [] // Include paragraphs if available
      }));
      
      console.log(`Loaded ${formattedMessages.length} messages for conversation:`, id);
      
      // Update both the current messages and the cached messages
      setMessages(formattedMessages);
      setConversationsMessages(prev => ({
        ...prev,
        [id]: formattedMessages
      }));
      
    } catch (error) {
      console.error('Error fetching conversation messages:', error);
      // Set empty message array if fetch fails
      setMessages([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle deleting a conversation
  const handleDeleteConversation = async (id: string): Promise<void> => {
    try {
      console.log("Deleting conversation:", id);
      
      // Call backend API to delete the conversation
      const response = await fetch(`http://localhost:5001/api/delete-conversation`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          conversationId: id
        })
      });
      
      if (!response.ok) {
        throw new Error('Failed to delete conversation');
      }
      
      // Remove conversation from state
      setConversationsMessages(prev => {
        const updated = { ...prev };
        delete updated[id];
        return updated;
      });
      
      // If we deleted the current conversation, start a new one
      if (id === conversationId) {
        // Remove from localStorage if we're deleting the current conversation
        if (typeof window !== 'undefined') {
          localStorage.removeItem('currentConversationId');
        }
        startNewConversation();
      }
      
    } catch (error) {
      console.error('Error deleting conversation:', error);
      alert('Failed to delete conversation. Please try again.');
      throw error; // Re-throw to propagate to the calling code
    }
  };

  // Handle switching to a different conversation
  const handleConversationSelect = (id: string) => {
    if (id !== conversationId) {
      console.log("Switching from conversation", conversationId, "to", id);
      
      // Save current conversation state before switching
      if (messages.length > 0) {
        setConversationsMessages(prev => ({
          ...prev,
          [conversationId]: messages
        }));
      }
      
      // Switch to the selected conversation
      setConversationId(id);
      setStreamingContent("");
      setIsStreaming(false);
      
      // Close PDF viewer if open
      setShowPdfViewer(false);
      setActivePdf(null);
    }
  };

  const handleSubmit = async (message: string, uploadedPdfIds?: string[]) => {
    if (!message.trim()) return;
    
    console.log("Submitting message for conversation:", conversationId);

    // Add user message to chat
    const updatedMessages = [...messages, { role: 'user', content: message }];
    setMessages(updatedMessages as Message[]);
    
    // Also update the conversationsMessages state
    setConversationsMessages(prev => ({
          ...prev,
          [conversationId]: updatedMessages as Message[]
        }));
    
    // Reset streaming state
    setStreamingContent("");
    setIsStreaming(true);
    setIsLoading(true);
  };

  const handleStreamToken = (token: string) => {
    // Ensure we're in streaming mode
    if (!isStreaming) {
      setIsStreaming(true);
    }
    
    // Update streaming content
    setStreamingContent(prev => {
      const newContent = prev + token;
      return newContent;
    });
  };

  const handleQueryResponse = (answer: string, sources: string[], structured_data?: any) => {
    console.log("Query complete for conversation:", conversationId);
    
    // Save the current streaming content to avoid race conditions
    const finalContent = isStreaming ? streamingContent : answer;
    
    // Create new assistant message
    const assistantMessage: Message = { 
      role: 'assistant', 
      content: finalContent.length > 0 ? finalContent : answer,
      sources: sources 
    };
    
    // Add structured paragraphs if available
    if (structured_data && Array.isArray(structured_data)) {
      assistantMessage.paragraphs = structured_data;
    }
    
    // Add the final message
    const updatedMessages = [...messages, assistantMessage];
    setMessages(updatedMessages as Message[]);
    
    // Also update the conversationsMessages state
    setConversationsMessages(prev => ({
      ...prev,
      [conversationId]: updatedMessages as Message[]
    }));
    
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

  // Start a new conversation
  const startNewConversation = () => {
    // Save current conversation state
    if (messages.length > 0) {
      setConversationsMessages(prev => ({
        ...prev,
        [conversationId]: messages
      }));
    }
    
    // Generate a new conversation ID
    const newId = `conv-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    console.log("Starting new conversation with ID:", newId);
    
    // Update conversationId state
    setConversationId(newId);
    
    // Update localStorage
    if (typeof window !== 'undefined') {
      localStorage.setItem('currentConversationId', newId);
    }
    
    // Reset UI state
    setMessages([]);
    setStreamingContent("");
    setIsStreaming(false);
    setIsLoading(false);
    
    // Close PDF viewer if open
    setShowPdfViewer(false);
    setActivePdf(null);
  };

  return (
    <div className="flex min-h-screen bg-[#0A0A0A] text-gray-100">
      {/* Sidebar component */}
      <Sidebar 
        messages={messages} 
        onExpandChange={handleSidebarExpandChange}
        onConversationSelect={handleConversationSelect}
        currentConversationId={conversationId}
        onNewConversation={startNewConversation}
        onDeleteConversation={handleDeleteConversation}
      />

      {/* Main chat area */}
      <div 
        className={`w-full flex transition-all duration-300 ease-in-out relative`} 
        style={{ 
          paddingLeft: isSidebarExpanded ? '18rem' : 0, 
          justifyContent: isSidebarExpanded ? 'flex-start' : 'center',
          marginRight: showPdfViewer ? 'calc(40%)' : 0
        }}
      >
        
        {/* Chat content area - no longer needs to shrink */}
        <div className={`flex flex-col p-4 transition-all duration-300 ease-in-out ${
          isSidebarExpanded ? 'max-w-5xl w-full' : 'max-w-5xl w-4/5'
        }`}>
          <div className="flex justify-center items-center mb-8">
            <h1 className="text-3xl font-bold text-center text-white">Papyrus</h1>
          </div>
          <div className="border-b border-gray-600 mb-8"></div>
          
          {/* Chat messages component */}
          <ChatMessages 
            messages={messages} 
            isLoading={isLoading}
            streamingContent={isStreaming ? streamingContent : null}
            messagesEndRef={messagesEndRef}
            onCitationClick={handleCitationClick}
            onCitationHover={handleCitationHover}
            citationPreviews={citationPreviews}
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
        
        {/* PDF Viewer Panel */}
        {showPdfViewer && activePdf ? (
          <PDFViewer
            pdfSource={activePdf.url}
            fileName={activePdf.fileName}
            initialPage={activePdf.page}
            onClose={() => {
              setShowPdfViewer(false);
              setActivePdf(null);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}