import React from 'react';
import { X, Upload, FileText, Loader2, Database, Zap, FileStack, BookOpen } from 'lucide-react';

// Import the UploadStatus type
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

interface PdfUploadProps {
  pdfs: File[];
  isDragActive: boolean;
  getRootProps: any;
  getInputProps: any;
  onRemovePdf: (index: number) => void;
  isUploading?: boolean;
  uploadProgress?: UploadStatus[];
  overallProgress?: number;
}

const PdfUpload: React.FC<PdfUploadProps> = ({
  pdfs,
  isDragActive,
  getRootProps,
  getInputProps,
  onRemovePdf,
  isUploading = false,
  uploadProgress = [],
  overallProgress = 0
}) => {
  // Find upload status for a specific file by name
  const getUploadStatus = (fileName: string) => {
    return uploadProgress.find(status => status.fileName === fileName);
  };

  // Get appropriate icon for current processing stage
  const getProcessingIcon = (message?: string) => {
    if (!message) return <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />;
    
    if (message.includes('Analyzing')) {
      return <BookOpen className="w-3 h-3 text-purple-400" />;
    } else if (message.includes('Extracting')) {
      return <FileText className="w-3 h-3 text-blue-400" />;
    } else if (message.includes('Chunking')) {
      return <FileStack className="w-3 h-3 text-blue-400" />;
    } else if (message.includes('Creating embeddings')) {
      return <Zap className="w-3 h-3 text-yellow-400" />;
    } else if (message.includes('Storing')) {
      return <Database className="w-3 h-3 text-green-400" />;
    }
    
    return <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />;
  };

  return (
    <div className="bg-[#1A1A1A] rounded-lg p-4 border border-gray-700">
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer transition-colors ${
          isDragActive
            ? 'border-blue-500 bg-blue-500/10'
            : 'border-gray-700 hover:border-gray-500'
        }`}
      >
        <input {...getInputProps()} />
        {isUploading ? (
          <div className="flex flex-col items-center">
            <Loader2 className="w-10 h-10 text-blue-400 animate-spin" />
            <p className="mt-2 text-sm text-blue-400 font-medium">
              Uploading & Processing... {overallProgress}%
            </p>
          </div>
        ) : (
          <>
            <Upload className="w-10 h-10 text-gray-400" />
            <p className="mt-2 text-sm text-gray-400">
              {isDragActive
                ? "Drop PDFs here..."
                : "Click or drag and drop PDFs here"}
            </p>
          </>
        )}
      </div>

      {pdfs.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-gray-300 mb-2">Uploaded PDFs</h4>
          <div className="space-y-2 max-h-40 overflow-y-auto pr-2">
            {pdfs.map((pdf, index) => {
              const status = getUploadStatus(pdf.name);
              const isFileUploading = status && status.status === 'uploading';
              const progress = status ? status.progress : 0;
              const isError = status && status.status === 'error';
              const isComplete = status && status.status === 'completed';
              const pageInfo = status?.totalPages 
                ? `${status.processedPages || 0}/${status.totalPages} pages` 
                : '';
              
              return (
                <div
                  key={index}
                  className="flex flex-col bg-[#2A2A2A] rounded p-2 text-sm"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2 truncate">
                      <FileText className={`w-4 h-4 ${isError ? 'text-red-400' : isComplete ? 'text-green-400' : 'text-blue-400'} flex-shrink-0`} />
                      <span className="truncate text-gray-300">{pdf.name}</span>
                      {pageInfo && (
                        <span className="text-xs text-gray-500 ml-1">({pageInfo})</span>
                      )}
                    </div>
                    <button
                      onClick={() => onRemovePdf(index)}
                      disabled={isFileUploading}
                      className={`p-1 rounded-full hover:bg-gray-700 ${
                        isFileUploading ? 'opacity-50 cursor-not-allowed' : ''
                      }`}
                    >
                      <X className="w-4 h-4 text-gray-400" />
                    </button>
                  </div>
                  
                  {/* Progress bar */}
                  {status && (
                    <div className="mt-1">
                      <div className="w-full h-1 bg-gray-700 rounded-full overflow-hidden">
                        <div 
                          className={`h-full ${isError ? 'bg-red-500' : 'bg-blue-500'} transition-all duration-300`}
                          style={{ width: `${progress}%` }}
                        ></div>
                      </div>
                      
                      {/* Processing status with icons */}
                      <div className="flex justify-between items-center mt-1">
                        <div className="flex items-center space-x-1">
                          {isFileUploading && status.message && getProcessingIcon(status.message)}
                          <span className="text-xs text-gray-400 truncate max-w-[180px]">
                            {isError 
                              ? status.error || 'Error' 
                              : isComplete 
                                ? 'Indexed successfully' 
                                : status.message || `${progress}%`
                            }
                          </span>
                        </div>
                        {isFileUploading && !status.message && (
                          <span className="text-xs text-gray-400">{progress}%</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default PdfUpload;