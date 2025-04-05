/* components/Sidebar.tsx*/

import React, { useState, useEffect, useRef } from 'react';
import { Message } from '../app/page';
import { RefreshCw, MessageSquare, Trash2, Download } from 'lucide-react';

interface ConversationPreview {
  id: string;
  firstMessage: string;
}

interface SidebarProps {
  messages: Message[];
  onExpandChange: (expanded: boolean) => void;
  onConversationSelect: (conversationId: string) => void;
  currentConversationId: string;
  onNewConversation?: () => void;
  onDeleteConversation?: (conversationId: string) => Promise<void>;
}

const Sidebar: React.FC<SidebarProps> = ({ 
  messages, 
  onExpandChange, 
  onConversationSelect,
  currentConversationId,
  onNewConversation,
  onDeleteConversation
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const [conversations, setConversations] = useState<ConversationPreview[]>([]);
  const [isLoadingConversations, setIsLoadingConversations] = useState(false);
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);
  const [exportingConversationId, setExportingConversationId] = useState<string | null>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);

  // Fetch all conversations from the backend
  const fetchConversations = async () => {
    try {
      setIsLoadingConversations(true);
      
      // Call the API to get all conversation IDs
      const response = await fetch('http://localhost:5001/api/conversations', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          userId: 'current-user' // You may want to implement actual user IDs later
        })
      });
      
      if (!response.ok) {
        throw new Error('Failed to fetch conversations');
      }
      
      const data = await response.json();
      
      // Use the conversations data from the API response
      const conversationPreviews = data.conversations.reverse().map((conv: any) => ({
        id: conv.conversation_id,
        firstMessage: conv.first_message || `Conversation ${conv.conversation_id.substring(0, 8)}...`
      }));
      
      setConversations(conversationPreviews);
    } catch (error) {
      console.error('Error fetching conversations:', error);
    } finally {
      setIsLoadingConversations(false);
    }
  };

  // Export conversation as JSON
  const exportConversation = async (conversationId: string) => {
    try {
      setExportingConversationId(conversationId);
      
      // Call the API to get conversation export
      const response = await fetch('http://localhost:5001/api/export-conversation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          conversationId
        })
      });
      
      if (!response.ok) {
        throw new Error('Failed to export conversation');
      }
      
      const data = await response.json();
      
      // Create a downloadable file from the JSON response
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      
      // Create a temporary link and trigger the download
      const link = document.createElement('a');
      link.href = url;
      link.download = `conversation-${conversationId.substring(0, 8)}.json`;
      document.body.appendChild(link);
      link.click();
      
      // Clean up
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      
    } catch (error) {
      console.error('Error exporting conversation:', error);
      alert('Failed to export conversation');
    } finally {
      setExportingConversationId(null);
    }
  };

  // Fetch conversations when component mounts
  useEffect(() => {
    if (isHovered) {
      fetchConversations();
    }
  }, [isHovered]);

  useEffect(() => {
    onExpandChange(isHovered);
  }, [isHovered, onExpandChange]);

  return (
    <div 
      ref={sidebarRef}
      className="fixed left-0 h-full z-10"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className={`h-full bg-[#1A1A1A] transition-all duration-300 ${isHovered ? 'w-72' : 'w-2'}`}>
        <div className={`${isHovered ? 'block' : 'hidden'} p-4 overflow-y-auto h-full`}>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-bold text-white">Conversations</h2>
            <div className="flex space-x-2">
              {onNewConversation && (
                <button 
                  onClick={onNewConversation}
                  className="p-2 rounded hover:bg-[#2A2A2A] text-gray-400 hover:text-gray-200"
                  title="New conversation"
                >
                  <MessageSquare size={16} />
                </button>
              )}
              <button 
                onClick={fetchConversations}
                className="p-2 rounded hover:bg-[#2A2A2A] text-gray-400 hover:text-gray-200"
                title="Refresh conversations"
              >
                <RefreshCw size={16} />
              </button>
            </div>
          </div>
          
          {isLoadingConversations ? (
            <div className="flex justify-center py-4">
              <div className="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-gray-500"></div>
            </div>
          ) : (
            <div className="space-y-2">
              {conversations.length > 0 ? (
                conversations.map((conv) => (
                  <div 
                    key={conv.id}
                    className={`p-3 rounded cursor-pointer flex items-center justify-between hover:bg-[#2A2A2A] transition-colors ${
                      currentConversationId === conv.id ? 'bg-[#2A2A2A] border-l-2 border-blue-500' : 'bg-[#1A1A1A]'
                    }`}
                  >
                    <div 
                      className="flex items-center flex-grow truncate"
                      onClick={() => onConversationSelect(conv.id)}
                    >
                      <MessageSquare size={16} className="mr-2 text-gray-400 flex-shrink-0" />
                      <div className="truncate text-sm text-gray-200">{conv.firstMessage}</div>
                    </div>
                    <div className="flex items-center space-x-1 flex-shrink-0">
                      {/* Export button */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          exportConversation(conv.id);
                        }}
                        className="p-1 rounded hover:bg-[#3A3A3A] text-gray-500 hover:text-blue-400"
                        title="Export conversation"
                        disabled={exportingConversationId === conv.id}
                      >
                        {exportingConversationId === conv.id ? (
                          <div className="w-3.5 h-3.5 rounded-full border-2 border-gray-500 border-t-transparent animate-spin" />
                        ) : (
                          <Download size={14} />
                        )}
                      </button>
                      
                      {/* Delete button */}
                      {onDeleteConversation && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (window.confirm('Are you sure you want to delete this conversation?')) {
                              setDeletingConversationId(conv.id);
                              onDeleteConversation(conv.id)
                                .then(() => {
                                  // Remove from local state on success
                                  setConversations(conversations.filter(c => c.id !== conv.id));
                                })
                                .finally(() => {
                                  setDeletingConversationId(null);
                                });
                            }
                          }}
                          className="p-1 rounded hover:bg-[#3A3A3A] text-gray-500 hover:text-red-400"
                          title="Delete conversation"
                          disabled={deletingConversationId === conv.id}
                        >
                          {deletingConversationId === conv.id ? (
                            <div className="w-3.5 h-3.5 rounded-full border-2 border-gray-500 border-t-transparent animate-spin" />
                          ) : (
                            <Trash2 size={14} />
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-gray-500 text-sm py-2">No conversations yet</p>
              )}
            </div>
          )}
          
          <div className="mt-6 pt-4 border-t border-gray-700">
            <h3 className="text-sm font-medium text-gray-400 mb-2">Current Conversation</h3>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {messages.map((msg, i) => (
                <div key={i} className={`p-2 rounded ${msg.role === 'user' ? 'bg-[#2A2A2A]' : 'bg-[#1A1A1A] border border-gray-800'}`}>
                  <p className="text-xs text-gray-400 mb-1">{msg.role === 'user' ? 'You' : 'Papyrus'}</p>
                  <p className="text-xs text-gray-300 truncate">{msg.content}</p>
                </div>
              ))}
              {messages.length === 0 && (
                <p className="text-gray-500 text-xs">No messages in this conversation</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Sidebar;