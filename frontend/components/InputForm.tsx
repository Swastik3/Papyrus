import React, { useState, useRef, useCallback, useEffect } from 'react';
import { MessageSquare } from 'lucide-react';
import { useDropzone } from 'react-dropzone';
import PdfUpload from './PdfUpload';
import { socketService } from '@/lib/WebSocketService';

interface UploadStatus {
  id: string;
  fileId: string;
  fileName: string;
  progress: number;
  status: 'uploading' | 'completed' | 'error';
  error?: string;
  message?: string;
  totalPages?: number;
  processedPages?: number;
}

interface InputFormProps {
  onSubmit: (message: string, uploadedPdfIds?: string[]) => void;
  pdfs: File[];
  onPdfUpload: (files: File[]) => void;
  onRemovePdf: (index: number) => void;
  onQueryResponse: (answer: string, sources: string[]) => void;
  onStreamToken: (token: string) => void;
  conversationId?: string;
}

const API_URL = 'http://localhost:5001';

const InputForm: React.FC<InputFormProps> = ({ 
  onSubmit, 
  pdfs, 
  onPdfUpload, 
  onRemovePdf,
  onQueryResponse,
  onStreamToken,
  conversationId
}) => {
  const [isUploadVisible, setIsUploadVisible] = useState<boolean>(false);
  const [uploadStatuses, setUploadStatuses] = useState<UploadStatus[]>([]);
  const [uploadedPdfIds, setUploadedPdfIds] = useState<string[]>([]);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isMessageLoading, setIsMessageLoading] = useState<boolean>(false);
  const [currentQueryId, setCurrentQueryId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Connect to WebSocket for progress updates and streaming
  useEffect(() => {
    // Handle connection status
    const unsubscribeConnected = socketService.on('connected', () => {
      setIsConnected(true);
      console.log('WebSocket connected');
    });

    const unsubscribeDisconnected = socketService.on('disconnected', () => {
      setIsConnected(false);
      console.log('WebSocket disconnected');
    });
    
    // Handle upload progress updates
    const unsubscribeProgress = socketService.on('upload_progress', (data: UploadStatus) => {
      console.log('Upload progress update:', data);
      
      setUploadStatuses(prevStatuses => {
        // Find and update existing status
        const existingIndex = prevStatuses.findIndex(status => status.id === data.id);
        if (existingIndex >= 0) {
          const newStatuses = [...prevStatuses];
          
          // If we're getting page progress updates, adjust the overall progress
          if (data.processedPages !== undefined && data.totalPages !== undefined) {
            // Calculate the total progress based on processed pages
            const newProgress = Math.min(
              Math.round((data.processedPages / data.totalPages) * 100),
              100
            );
            
            newStatuses[existingIndex] = {
              ...data,
              progress: newProgress
            };
          } else {
            newStatuses[existingIndex] = data;
          }
          
          return newStatuses;
        } else {
          return [...prevStatuses, data];
        }
      });

      // Add completed file ID to the list when all processing is done
      if (data.status === 'completed' && data.fileId) {
        setUploadedPdfIds(prev => {
          if (!prev.includes(data.fileId)) {
            return [...prev, data.fileId];
          }
          return prev;
        });
      }
    });

    // Handle streaming token events with clear debug logging
    const unsubscribeToken = socketService.on('token', (data) => {
      console.log('%c InputForm received token ', 'background: #e74c3c; color: white; padding: 4px;', data);
      if (data && data.token) {
        console.log('%c Calling onStreamToken ', 'background: #9b59b6; color: white; padding: 4px;', data.token);
        onStreamToken(data.token);
        
        // Log after callback
        console.log('%c onStreamToken called ', 'background: #34495e; color: white; padding: 4px;');
      }
    });

    // Handle query processing status
    const unsubscribeQueryProcessing = socketService.on('query_processing', (data) => {
      console.log('Query processing:', data);
      if (!isMessageLoading) {
        setIsMessageLoading(true);
      }
    });

    // Handle query results
    const unsubscribeQueryResult = socketService.on('query_result', (data) => {
      console.log('Query result received:', data);
      
      // Check if this is the query we're waiting for
      if (data.queryId === currentQueryId || currentQueryId === null) {
        // IMPORTANT: Call onQueryResponse first before changing loading state
        // This ensures that the complete streamed content is used
        onQueryResponse(data.answer, data.sources || []);
        
        // Now we can update loading state
        setIsMessageLoading(false);
        setCurrentQueryId(null);
      }
    });

    // Handle query errors
    const unsubscribeQueryError = socketService.on('query_error', (data) => {
      console.error('Query error:', data);
      if (data.queryId === currentQueryId || currentQueryId === null) {
        onQueryResponse(`Error: ${data.error || 'Unknown error'}`, []);
        setIsMessageLoading(false);
        setCurrentQueryId(null);
      }
    });

    // Clean up event listeners on component unmount
    return () => {
      unsubscribeConnected();
      unsubscribeDisconnected();
      unsubscribeProgress();
      unsubscribeToken();
      unsubscribeQueryProcessing();
      unsubscribeQueryResult();
      unsubscribeQueryError();
    };
  }, [onStreamToken, onQueryResponse, currentQueryId, isMessageLoading]);

  // Handle PDF upload via HTTP
  const handlePdfUpload = async (files: File[]) => {
    if (files.length === 0) return;
    
    // First update UI
    onPdfUpload(files);
    
    // Process each file
    for (const file of files) {
      const uploadId = `upload-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      
      // Add to status tracking
      setUploadStatuses(prev => [
        ...prev,
        {
          id: uploadId,
          fileId: '',
          fileName: file.name,
          progress: 0,
          status: 'uploading',
          message: 'Preparing upload...'
        }
      ]);
      
      try {
        // Create form data
        const formData = new FormData();
        formData.append('file', file);
        formData.append('uploadId', uploadId);
        formData.append('conversationId', conversationId || '');
        formData.append('socketId', socketService.getSocketId() || '');
        
        // Send the file via HTTP POST
        const response = await fetch(`${API_URL}/api/upload-pdf`, {
          method: 'POST',
          body: formData
        });
        
        const result = await response.json();
        
        if (!response.ok) {
          throw new Error(result.error || 'Failed to upload PDF');
        }
        
        // If upload was successful but processing will continue via WebSocket
        console.log('Upload successful, processing continues via WebSocket updates');
        
      } catch (error) {
        console.error('Error uploading PDF:', error);
        
        // Update status with error
        setUploadStatuses(prev => {
          const index = prev.findIndex(status => status.id === uploadId);
          if (index >= 0) {
            const newStatuses = [...prev];
            newStatuses[index] = {
              ...newStatuses[index],
              status: 'error',
              error: 'Failed to upload: ' + (error instanceof Error ? error.message : String(error))
            };
            return newStatuses;
          }
          return prev;
        });
      }
    }
  };

  const onDrop = useCallback((acceptedFiles: File[]) => {
    handlePdfUpload(acceptedFiles);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf']
    },
    multiple: true
  });

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const message = formData.get('message') as string;
    
    // If message is empty and no PDFs, do nothing
    if (!message.trim() && uploadedPdfIds.length === 0) return;
    
    // Pass the message to parent component to display the user message
    onSubmit(message, uploadedPdfIds);
    
    // Set loading state
    setIsMessageLoading(true);
    
    // Generate a unique query ID
    const queryId = `query-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    setCurrentQueryId(queryId);
    
    // Use WebSocket for streaming instead of HTTP
    if (socketService.isConnected()) {
      // Send query via WebSocket
      const success = socketService.send('query', {
        query: message,
        model: 'gpt-4o-mini',
        queryId: queryId,
        conversationId: conversationId
      });
      
      console.log('Query sent via WebSocket:', success);
      
      if (!success) {
        console.warn('WebSocket send failed, falling back to HTTP');
        fallbackToHttpQuery(message, queryId);
      }
    } else {
      console.log('WebSocket not connected, using HTTP fallback');
      fallbackToHttpQuery(message, queryId);
    }
    
    // Reset the form after submission
    (e.target as HTMLFormElement).reset();
  };
  
  // Fallback to HTTP query if WebSocket is not available
  const fallbackToHttpQuery = async (message: string, queryId: string) => {
    try {
      const response = await fetch(`${API_URL}/api/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          query: message,
          model: 'gpt-4o-mini',
          conversationId: conversationId
        })
      });
      
      if (!response.ok) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }
      
      const result = await response.json();
      
      // Call onQueryResponse with the result
      onQueryResponse(result.answer, result.sources || []);
      
      // Reset loading state
      setIsMessageLoading(false);
      setCurrentQueryId(null);
    } catch (error) {
      console.error('Error querying:', error);
      onQueryResponse(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`, []);
      setIsMessageLoading(false);
      setCurrentQueryId(null);
    }
  };

  // Calculate overall upload progress
  const isUploading = uploadStatuses.some(status => status.status === 'uploading');
  const overallProgress = isUploading
    ? Math.round(
        uploadStatuses.reduce((sum, status) => sum + (status.progress || 0), 0) / 
        Math.max(1, uploadStatuses.length)
      )
    : 0;

  // Handle PDF removal
  const handleRemovePdf = (index: number) => {
    onRemovePdf(index);
    
    // Also remove the corresponding status and ID if available
    if (index < pdfs.length) {
      const fileName = pdfs[index].name;
      
      // Find the status with matching filename
      const statusIndex = uploadStatuses.findIndex(status => status.fileName === fileName);
      if (statusIndex >= 0) {
        const fileId = uploadStatuses[statusIndex].fileId;
        
        // Remove status
        setUploadStatuses(prev => prev.filter((_, i) => i !== statusIndex));
        
        // Remove ID if it exists and is completed
        if (fileId && uploadedPdfIds.includes(fileId)) {
          setUploadedPdfIds(prev => prev.filter(id => id !== fileId));
        }
      }
    }
  };

  return (
    <div className="relative">
      {/* Connection status indicator */}
      <div className={`absolute top-0 right-0 -mt-6 text-xs ${isConnected ? 'text-green-500' : 'text-red-500'}`}>
        {isConnected ? '● Connected' : '● Disconnected'}
      </div>
      
      {/* PDF upload area that appears on hover */}
      <div 
        className={`absolute bottom-full left-0 w-full transition-all duration-300 overflow-hidden ${
          isUploadVisible ? 'max-h-96 opacity-100 mb-4' : 'max-h-0 opacity-0'
        }`}
        onMouseEnter={() => setIsUploadVisible(true)}
        onMouseLeave={() => setIsUploadVisible(false)}
      >
        <PdfUpload 
          pdfs={pdfs}
          isDragActive={isDragActive}
          getRootProps={getRootProps}
          getInputProps={getInputProps}
          onRemovePdf={handleRemovePdf}
          isUploading={isUploading}
          uploadProgress={uploadStatuses}
          overallProgress={overallProgress}
        />
      </div>
      
      <form 
        onSubmit={handleSubmit} 
        className="flex gap-2"
        onMouseEnter={() => setIsUploadVisible(true)}
        onMouseLeave={() => setIsUploadVisible(false)}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const pdfFiles = Array.from(e.dataTransfer.files).filter(
              file => file.type === 'application/pdf'
            );
            if (pdfFiles.length > 0) {
              handlePdfUpload(pdfFiles);
            }
          }
        }}
      >
        <div className="flex-1 relative">
          {/* Progress bar that appears when uploading */}
          {isUploading && (
            <div className="absolute top-0 left-0 right-0 h-1 bg-gray-700 overflow-hidden rounded-t-lg">
              <div 
                className="h-full bg-blue-500 transition-all duration-300"
                style={{ width: `${overallProgress}%` }}
              ></div>
            </div>
          )}
          
          <input
            ref={inputRef}
            type="text"
            name="message"
            placeholder={isUploading 
              ? `Uploading PDFs (${overallProgress}%)...` 
              : "Type your message or drop PDFs here..."}
            className="w-full bg-[#1A1A1A] rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-gray-600"
            disabled={isMessageLoading}
          />
        </div>
        <button
          type="submit"
          className={`bg-[#2A2A2A] hover:bg-[#3A3A3A] rounded-lg px-4 py-2 flex items-center gap-2 text-gray-200 ${
            isMessageLoading ? 'opacity-70 cursor-wait' : ''
          }`}
          disabled={isMessageLoading}
        >
          <MessageSquare className="w-5 h-5" />
          Send
        </button>
      </form>
    </div>
  );
};

export default InputForm;