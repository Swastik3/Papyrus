import React, { useState, useRef, useCallback, useEffect } from 'react';
import { MessageSquare } from 'lucide-react';
import { useDropzone } from 'react-dropzone';
import PdfUpload from './PdfUpload';
import { socketService } from '@/lib/WebSocketService';
import { pdfjs } from 'react-pdf';

// Initialize PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

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
  onStreamStart: () => void;
  onStreamToken: (token: string) => void;
  onStreamEnd: (answer: string, sources: string[]) => void;
  conversationId?: string;
}

const PAGES_PER_CHUNK = 10;

const InputForm: React.FC<InputFormProps> = ({ 
  onSubmit, 
  pdfs, 
  onPdfUpload, 
  onRemovePdf,
  onStreamStart,
  onStreamToken,
  onStreamEnd,
  conversationId
}) => {
  const [isUploadVisible, setIsUploadVisible] = useState<boolean>(false);
  const [uploadStatuses, setUploadStatuses] = useState<UploadStatus[]>([]);
  const [uploadedPdfIds, setUploadedPdfIds] = useState<string[]>([]);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isMessageLoading, setIsMessageLoading] = useState<boolean>(false);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [currentQueryId, setCurrentQueryId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Connect to WebSocket and set up event listeners
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
      if (data.status === 'completed' && data.fileId && 
          data.processedPages !== undefined && 
          data.totalPages !== undefined && 
          data.processedPages >= data.totalPages) {
        setUploadedPdfIds(prev => {
          if (!prev.includes(data.fileId)) {
            return [...prev, data.fileId];
          }
          return prev;
        });
      }
    });

    // Set up streaming handlers
    const unsubscribeTokenStream = socketService.on('token_stream', (data) => {
      if (data.queryId === currentQueryId) {
        onStreamToken(data.token);
      }
    });

    const unsubscribeQueryResult = socketService.on('query_result', (data) => {
      if (data.queryId === currentQueryId) {
        setIsStreaming(false);
        setIsMessageLoading(false);
        onStreamEnd(data.answer, data.sources || []);
        setCurrentQueryId(null);
      }
    });

    const unsubscribeQueryError = socketService.on('query_error', (data) => {
      if (data.queryId === currentQueryId) {
        setIsStreaming(false);
        setIsMessageLoading(false);
        // Send error message to chat
        onStreamEnd(`Error: ${data.error || 'An error occurred during processing.'}`, []);
        setCurrentQueryId(null);
      }
    });

    // Clean up event listeners on component unmount
    return () => {
      unsubscribeConnected();
      unsubscribeDisconnected();
      unsubscribeProgress();
      unsubscribeTokenStream();
      unsubscribeQueryResult();
      unsubscribeQueryError();
    };
  }, [currentQueryId, onStreamToken, onStreamEnd]);

  // Process PDF in chunks and send them to the server
  const processPdfInChunks = async (file: File, uploadId: string) => {
    try {
      // Read the PDF file
      const arrayBuffer = await file.arrayBuffer();
      const pdf = await pdfjs.getDocument({ data: arrayBuffer }).promise;
      
      const totalPages = pdf.numPages;
      
      // Update status with total pages
      setUploadStatuses(prev => {
        const index = prev.findIndex(status => status.id === uploadId);
        if (index >= 0) {
          const newStatuses = [...prev];
          newStatuses[index] = {
            ...newStatuses[index],
            totalPages,
            processedPages: 0
          };
          return newStatuses;
        }
        return prev;
      });
      
      // Generate a file ID to use across chunks
      const fileId = `file-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      
      // Process pages in chunks
      let processedPages = 0;
      for (let startPage = 1; startPage <= totalPages; startPage += PAGES_PER_CHUNK) {
        const endPage = Math.min(startPage + PAGES_PER_CHUNK - 1, totalPages);
        const chunkPages = endPage - startPage + 1;
        
        // Extract text from pages in this chunk
        const pageTexts = [];
        for (let pageNum = startPage; pageNum <= endPage; pageNum++) {
          const page = await pdf.getPage(pageNum);
          const textContent = await page.getTextContent();
          const pageText = textContent.items.map(item => 'str' in item ? item.str : '').join(' ');
          pageTexts.push({ pageNum, text: pageText });
        }
        
        // Create a chunk ID for this set of pages
        const chunkId = `${uploadId}_chunk_${startPage}_${endPage}`;
        
        // Send this chunk to the server
        socketService.send('upload_pdf_chunk', {
          uploadId,
          fileId,
          fileName: file.name,
          chunkId,
          startPage,
          endPage,
          totalPages,
          pageData: pageTexts
        });
        
        processedPages += chunkPages;
        
        // Update status with processed pages
        setUploadStatuses(prev => {
          const index = prev.findIndex(status => status.id === uploadId);
          if (index >= 0) {
            const newStatuses = [...prev];
            newStatuses[index] = {
              ...newStatuses[index],
              processedPages,
              fileId // Make sure we set the fileId
            };
            return newStatuses;
          }
          return prev;
        });
        
        // Small delay to avoid overwhelming the server
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      
    } catch (error) {
      console.error('Error processing PDF:', error);
      
      // Update status with error
      setUploadStatuses(prev => {
        const index = prev.findIndex(status => status.id === uploadId);
        if (index >= 0) {
          const newStatuses = [...prev];
          newStatuses[index] = {
            ...newStatuses[index],
            status: 'error',
            error: 'Failed to process PDF: ' + (error instanceof Error ? error.message : String(error))
          };
          return newStatuses;
        }
        return prev;
      });
    }
  };

  // Handle PDF upload
  const handlePdfUpload = async (files: File[]) => {
    if (files.length === 0) return;
    
    // First update UI
    onPdfUpload(files);
    
    // For each file, create an initial status and process in chunks
    files.forEach(file => {
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
          message: 'Analyzing PDF...'
        }
      ]);
      
      // Process PDF in chunks
      processPdfInChunks(file, uploadId).catch(error => {
        console.error('Error in PDF processing:', error);
      });
    });
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
    
    // Pass the message to parent component (this will display the user message)
    onSubmit(message, uploadedPdfIds);
    
    // Start streaming response
    setIsMessageLoading(true);
    setIsStreaming(true);
    onStreamStart();
    
    // Generate a query ID
    const queryId = `query-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    setCurrentQueryId(queryId);
    
    // Send the query via WebSocket
    socketService.send('query', {
      query: message,
      queryId: queryId,
      conversationId: conversationId
    });
    
    // Reset the form after submission
    (e.target as HTMLFormElement).reset();
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
            disabled={isMessageLoading || isStreaming}
          />
        </div>
        <button
          type="submit"
          className={`bg-[#2A2A2A] hover:bg-[#3A3A3A] rounded-lg px-4 py-2 flex items-center gap-2 text-gray-200 ${
            isMessageLoading || isStreaming ? 'opacity-70 cursor-wait' : ''
          }`}
          disabled={isMessageLoading || isStreaming}
        >
          <MessageSquare className="w-5 h-5" />
          Send
        </button>
      </form>
    </div>
  );
};

export default InputForm;