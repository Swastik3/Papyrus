/* components/PDFViewer.tsx */
import React, { useState, useEffect } from 'react';
import { X, ChevronLeft, ChevronRight, Download, Maximize2, Minimize2, FileText, Columns } from 'lucide-react';

interface PDFViewerProps {
  pdfSource: string;
  fileName: string;
  initialPage?: number;
  onClose: () => void;
}

const PDFViewer: React.FC<PDFViewerProps> = ({ 
  pdfSource,
  fileName,
  initialPage = 1,
  onClose
}) => {
  const [currentPage, setCurrentPage] = useState<number>(initialPage || 1);
  const [totalPages, setTotalPages] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'sidebar' | 'fullscreen'>('sidebar');

  // Properly prepare the PDF source URL with page information
  const getPdfSourceUrl = () => {
    // Split the URL to separate any existing hash
    const [baseUrl, existingHash] = pdfSource.split('#');
    
    // Create a clean URL with the page parameter
    return `${baseUrl}#page=${currentPage}`;
  };

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    
    // If we have a new PDF source, reset the current page to the initial page
    if (initialPage) {
      setCurrentPage(initialPage);
    }
  }, [pdfSource, initialPage]);

  // Handle changing pages
  const nextPage = () => {
    if (currentPage < totalPages) {
      setCurrentPage(currentPage + 1);
    }
  };

  const prevPage = () => {
    if (currentPage > 1) {
      setCurrentPage(currentPage - 1);
    }
  };

  // Toggle view mode
  const toggleViewMode = () => {
    setViewMode(prev => prev === 'sidebar' ? 'fullscreen' : 'sidebar');
  };

  // When iframe loads, check if it loaded successfully
  const handleIframeLoad = () => {
    setIsLoading(false);
  };

  const handleIframeError = () => {
    setIsLoading(false);
    setError("Failed to load PDF. Please try again.");
  };

  // Determine the appropriate classes based on view mode
  const getContainerClasses = () => {
    switch (viewMode) {
      case 'sidebar':
        return 'fixed right-0 top-0 bottom-0 w-2/5 z-20 transition-all duration-300 ease-in-out';
      case 'fullscreen':
        return 'fixed inset-4 z-50 transition-all duration-300 ease-in-out';
      default:
        return '';
    }
  };

  return (
    <div 
      className={`
        ${getContainerClasses()} 
        bg-[#1A1A1A] border border-gray-700 rounded-lg 
        flex flex-col overflow-hidden shadow-2xl
      `}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 bg-[#242424]">
        <div className="flex items-center">
          <FileText className="text-blue-400 mr-2 h-4 w-4" />
          <h3 className="font-medium text-sm text-gray-200 truncate">{fileName}</h3>
        </div>
        
        <div className="flex items-center space-x-2">
          {/* View mode toggle */}
          <button
            onClick={toggleViewMode}
            className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded"
            title={viewMode === 'sidebar' ? 'Fullscreen' : 'Sidebar'}
          >
            {viewMode === 'sidebar' ? <Maximize2 size={16} /> : <Columns size={16} />}
          </button>
          
          {/* Download button */}
          <a
            href={pdfSource}
            download={fileName}
            className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded"
            title="Download PDF"
          >
            <Download size={16} />
          </a>
          
          {/* Close button */}
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded"
          >
            <X size={16} />
          </button>
        </div>
      </div>
      
      {/* PDF Viewer */}
      <div className="flex-1 relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#1A1A1A] bg-opacity-80 z-10">
            <div className="flex flex-col items-center">
              <div className="w-10 h-10 border-2 border-t-blue-500 border-gray-500 rounded-full animate-spin mb-2"></div>
              <p className="text-sm text-gray-300">Loading PDF...</p>
            </div>
          </div>
        )}
        
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#1A1A1A] text-center p-4">
            <div>
              <p className="text-red-400 mb-2">{error}</p>
              <button 
                onClick={() => {
                  setIsLoading(true);
                  setError(null);
                  // Force iframe refresh by adding a timestamp parameter
                  const iframe = document.querySelector('iframe');
                  if (iframe) {
                    iframe.src = `${getPdfSourceUrl()}&_t=${Date.now()}`;
                  }
                }} 
                className="px-3 py-1 bg-blue-500 text-white rounded text-sm"
              >
                Retry
              </button>
            </div>
          </div>
        )}
        
        <iframe
          src={getPdfSourceUrl()}
          className="w-full h-full"
          onLoad={handleIframeLoad}
          onError={handleIframeError}
          title={`PDF Viewer - ${fileName}`}
        />
      </div>
      
      {/* Footer with page controls */}
      <div className="px-4 py-2 border-t border-gray-700 bg-[#242424] flex items-center justify-center space-x-4">
        <button
          onClick={prevPage}
          disabled={currentPage <= 1}
          className={`p-1 rounded ${
            currentPage <= 1 ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
          }`}
        >
          <ChevronLeft size={20} />
        </button>
        
        <span className="text-sm text-gray-300">
          Page <span className="font-medium text-white">{currentPage}</span>
          {totalPages > 0 && <> of <span className="font-medium text-white">{totalPages}</span></>}
        </span>
        
        <button
          onClick={nextPage}
          disabled={currentPage >= totalPages && totalPages > 0}
          className={`p-1 rounded ${
            currentPage >= totalPages && totalPages > 0 ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
          }`}
        >
          <ChevronRight size={20} />
        </button>
      </div>
    </div>
  );
};

export default PDFViewer;