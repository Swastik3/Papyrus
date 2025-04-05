/* components/InputForm.tsx */
import React, { useState, useRef, useCallback, useEffect } from "react";
import { Send, X, Image, Upload } from "lucide-react";
import { useDropzone } from "react-dropzone";
import PdfUpload from "./PdfUpload";
import { socketService } from "@/lib/WebSocketService";

interface UploadStatus {
  id: string;
  fileId: string;
  fileName: string;
  progress: number;
  status: "uploading" | "completed" | "error";
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
  onQueryResponse: (answer: string, sources: string[], structured_data?: any) => void;
  onStreamToken: (token: string) => void;
  conversationId: string;
}

const InputForm: React.FC<InputFormProps> = ({
  onSubmit,
  pdfs,
  onPdfUpload,
  onRemovePdf,
  onQueryResponse,
  onStreamToken,
  conversationId,
}) => {
  const [message, setMessage] = useState<string>("");
  const [showPdfUpload, setShowPdfUpload] = useState<boolean>(false);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<UploadStatus[]>([]);
  const [uploadedPdfIds, setUploadedPdfIds] = useState<string[]>([]);
  const [isSocketConnected, setIsSocketConnected] = useState<boolean>(false);
  const [isQueryInProgress, setIsQueryInProgress] = useState<boolean>(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [isScanningInProgress, setIsScanningInProgress] =
    useState<boolean>(false);

  // Add a new state to track scan progress separately
  const [scanProgress, setScanProgress] = useState<{
    id: string;
    fileId: string;
    progress: number;
    status: "uploading" | "completed" | "error";
    message?: string;
    fileName?: string;
  } | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dropzoneRef = useRef<HTMLDivElement>(null);

  // Socket connection and event handlers
  useEffect(() => {
    // Check if already connected
    if (socketService.isConnected()) {
      setIsSocketConnected(true);
    }

    // Set up event listeners
    const unsubConnect = socketService.on("connected", () =>
      setIsSocketConnected(true)
    );
    const unsubDisconnect = socketService.on("disconnected", () =>
      setIsSocketConnected(false)
    );

    // Upload progress tracking
    const unsubProgress = socketService.on(
      "upload_progress",
      (data: UploadStatus) => {
        console.log("DEBUG: Received upload_progress event:", data);

        // Update progress for this file
        setUploadProgress((prev) => {
          const exists = prev.some((p) => p.id === data.id);
          if (exists) {
            return prev.map((p) => (p.id === data.id ? data : p));
          } else {
            return [...prev, data];
          }
        });

        // Make sure isUploading state correctly reflects ongoing uploads
        const isStillUploading = data.status === "uploading";
        if (isStillUploading) {
          setIsUploading(true);
        } else if (data.status === "completed" && data.fileId) {
          // Track completed file IDs
          setUploadedPdfIds((prev) => {
            const updatedSet = new Set([...prev, data.fileId]);
            return Array.from(updatedSet);
          });
        }

        // Check if any uploads are still in progress
        setTimeout(() => {
          setUploadProgress((prevProgress) => {
            const anyUploading = prevProgress.some(
              (p) => p.status === "uploading"
            );
            setIsUploading(anyUploading);
            return prevProgress;
          });
        }, 100);
      }
    );

    // Add a new event listener for scan_progress
    const unsubScanProgress = socketService.on("scan_progress", (data) => {
      console.log("DEBUG: Received scan_progress event:", data);

      // Update scan progress
      setScanProgress(data);

      // Update scanning state based on status
      if (data.status === "uploading") {
        setIsScanningInProgress(true);
        console.log(`DEBUG: Scan in progress - ${data.progress}%`);
      } else if (data.status === "completed") {
        setIsScanningInProgress(false);
        console.log("DEBUG: Scan completed successfully");

        // Add the file ID to uploaded PDFs if available
        if (data.fileId) {
          setUploadedPdfIds((prev) => {
            const updatedSet = new Set([...prev, data.fileId]);
            return Array.from(updatedSet);
          });
        }
      } else if (data.status === "error") {
        setIsScanningInProgress(false);
        console.error("DEBUG: Scan error:", data.error || "Unknown error");
      }
    });

    // Other socket events
    const unsubToken = socketService.on("token", (data) => {
      if (data && data.token) onStreamToken(data.token);
    });

    const unsubQueryResult = socketService.on("query_result", (data) => {
      setIsQueryInProgress(false);
      console.log("Query result received with structured data:", data);

      if (data && data.answer) {
        // Pass structured_data to onQueryResponse if available
        onQueryResponse(
          data.answer, 
          data.sources || [], 
          data.structured_data || []
        );
      }
    });

    const unsubQueryError = socketService.on("query_error", (data) => {
      setIsQueryInProgress(false);
      const errorMessage = data?.error
        ? `Error: ${data.error}`
        : "Query error occurred";
      onQueryResponse(errorMessage, []);
    });

    // Scan completion event
    const unsubScanComplete = socketService.on("scan_complete", (data) => {
      console.log("DEBUG: Received scan_complete event:", data);
      setIsScanningInProgress(false);

      if (data && data.success) {
        // Add the scanned file to the PDFs list if it's not already there
        if (data.fileId) {
          setUploadedPdfIds((prev) => {
            const updatedSet = new Set([...prev, data.fileId]);
            return Array.from(updatedSet);
          });
        }
      }
    });

    // Cleanup
    return () => {
      unsubConnect();
      unsubDisconnect();
      unsubProgress();
      unsubToken();
      unsubQueryResult();
      unsubQueryError();
      unsubScanComplete();
      unsubScanProgress();
    };
  }, [onQueryResponse, onStreamToken]);

  // Keep track of which PDFs have been processed
  const [processedPdfs, setProcessedPdfs] = useState<Set<string>>(new Set());

  // Modified auto-upload effect to only upload new PDFs
  useEffect(() => {
    if (pdfs.length === 0) {
      // Reset processed PDFs when all are removed
      setProcessedPdfs(new Set());
      return;
    }

    // If already uploading, don't start new uploads
    if (isUploading) return;

    // Check which PDFs are new and need uploading
    const pdfSignatures = pdfs.map(
      (pdf) => `${pdf.name}-${pdf.size}-${pdf.lastModified}`
    );
    
    // Filter to only get new PDFs that haven't been processed yet
    const newPdfs = pdfs.filter((pdf, index) => {
      const signature = pdfSignatures[index];
      return !processedPdfs.has(signature);
    });

    // Only upload if we have new PDFs
    if (newPdfs.length > 0) {
      // Mark all current PDFs as processed
      const updatedProcessed = new Set(processedPdfs);
      pdfSignatures.forEach((sig) => updatedProcessed.add(sig));
      setProcessedPdfs(updatedProcessed);

      // Upload only the new PDFs
      uploadSelectedPdfs(newPdfs);
    }
  }, [pdfs]); // Remove isUploading from dependencies to prevent loop

  // Auto-size textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  }, [message]);

  // Handle pending message submission after uploads complete
  useEffect(() => {
    if (!isUploading && pendingMessage !== null) {
      sendMessage(pendingMessage);
      setPendingMessage(null);
    }
  }, [isUploading, pendingMessage]); // eslint-disable-line react-hooks/exhaustive-deps

  // Handle outside clicks to close dropzone
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        showPdfUpload &&
        dropzoneRef.current &&
        !dropzoneRef.current.contains(event.target as Node) &&
        !isUploading
      ) {
        setShowPdfUpload(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showPdfUpload, isUploading]);

  // Calculate overall progress
  const calculateOverallProgress = useCallback(() => {
    if (uploadProgress.length === 0) return 0;
    const total = uploadProgress.reduce((sum, curr) => sum + curr.progress, 0);
    return Math.round(total / uploadProgress.length);
  }, [uploadProgress]);

  // Upload selected PDF files to server
  const uploadSelectedPdfs = async (filesToUpload: File[]) => {
    if (filesToUpload.length === 0 || isUploading) return;

    setIsUploading(true);
    const socketId = socketService.getSocketId();

    if (!socketId) {
      alert("WebSocket connection not available. Please refresh the page.");
      setIsUploading(false);
      return;
    }

    // Create an array of upload promises to execute in parallel
    const uploadPromises = filesToUpload.map(async (file, index) => {
      const uploadId = `upload-${Date.now()}-${index}`;

      try {
        // Add to progress tracking
        setUploadProgress((prev) => [
          ...prev,
          {
            id: uploadId,
            fileId: "",
            fileName: file.name,
            progress: 0,
            status: "uploading",
            message: "Starting upload...",
          },
        ]);

        // Upload file
        const formData = new FormData();
        formData.append("file", file);
        formData.append("socketId", socketId);
        formData.append("uploadId", uploadId);
        formData.append("conversationId", conversationId);

        const response = await fetch("http://localhost:5001/api/upload-pdf", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.error || "Upload failed");
        }

        // Update with server response
        const result = await response.json();
        if (result.success && result.fileId) {
          setUploadedPdfIds((prev) => {
            const updatedSet = new Set([...prev, result.fileId]);
            return Array.from(updatedSet);
          });
        }

        return { success: true, uploadId };
      } catch (error) {
        console.error(`Error uploading ${file.name}:`, error);
        setUploadProgress((prev) =>
          prev.map((p) =>
            p.id === uploadId
              ? {
                  ...p,
                  status: "error",
                  error:
                    error instanceof Error ? error.message : "Upload failed",
                }
              : p
          )
        );

        return { success: false, uploadId, error };
      }
    });

    // Execute all uploads simultaneously
    await Promise.all(uploadPromises);

    // Note: isUploading will be set to false by the socket events when all uploads complete
  };

  // Upload and process scanned images/PDFs for OCR
  const handleScanUpload = async () => {
    // Create a file input element
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*,application/pdf";
    fileInput.multiple = true;

    // Add change listener
    fileInput.addEventListener("change", async () => {
      if (fileInput.files && fileInput.files.length > 0) {
        setIsScanningInProgress(true);
        const socketId = socketService.getSocketId();

        if (!socketId) {
          alert("WebSocket connection not available. Please refresh the page.");
          setIsScanningInProgress(false);
          return;
        }

        // Create form data
        const formData = new FormData();
        for (let i = 0; i < fileInput.files.length; i++) {
          formData.append("scans", fileInput.files[i]);
        }
        formData.append("socketId", socketId);
        formData.append("conversationId", conversationId);

        try {
          console.log("DEBUG: Sending scan_pdf request to server");
          // Make API call
          const response = await fetch("http://localhost:5001/api/scan_pdf", {
            method: "POST",
            body: formData,
          });

          if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || "Scan upload failed");
          }

          const result = await response.json();
          console.log("DEBUG: Received scan_pdf response:", result);

          if (result.success) {
            // Success message will be handled by socket event
            console.log("DEBUG: Scan initiated successfully:", result);
          } else {
            throw new Error(result.error || "Scan processing failed");
          }
        } catch (error) {
          console.error("ERROR: Error uploading scans:", error);
          alert(
            `Error uploading scans: ${
              error instanceof Error ? error.message : "Unknown error"
            }`
          );
          setIsScanningInProgress(false);
        }
      }
    });

    // Trigger file selection
    fileInput.click();
  };

  // Send message to server
  const sendMessage = (text: string) => {
    if (!text.trim() && pdfs.length === 0) return;

    // If uploads are in progress, store message for later
    if (isUploading) {
      setPendingMessage(text);
      return;
    }

    // Send message with any uploaded PDF IDs
    onSubmit(text, uploadedPdfIds.length > 0 ? uploadedPdfIds : undefined);
    setMessage("");

    // Send query via WebSocket
    if (socketService.isConnected()) {
      setIsQueryInProgress(true);
      socketService.send("query", {
        query: text,
        conversationId: conversationId,
        model: "gpt-4o-mini",
        queryId: `query-${Date.now()}`,
      });
    } else {
      alert("WebSocket connection lost. Please refresh the page.");
    }
  };

  // Handle key press (Ctrl/Cmd + Enter to send)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      sendMessage(message);
    }
  };

  // Dropzone configuration
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (acceptedFiles) => {
      const pdfFiles = acceptedFiles.filter(
        (file) => file.type === "application/pdf"
      );
      if (pdfFiles.length > 0) {
        onPdfUpload(pdfFiles);
        setShowPdfUpload(true);
      }
    },
    accept: {
      "application/pdf": [".pdf"],
    },
    maxFiles: 5,
    multiple: true,
  });

  return (
    <div className="mt-auto">
      {/* OCR Scan Progress Display */}
      {scanProgress && (
        <div className="mb-4 border border-gray-700 rounded-lg p-3 bg-gray-800">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-300">
              {scanProgress.fileName || "OCR Processing"}
            </span>
            <div className="flex items-center">
              <span className="text-sm font-medium text-blue-400 mr-2">
                {scanProgress.progress}%
              </span>
              <button
                onClick={() => setScanProgress(null)}
                className="p-1 rounded-md hover:bg-gray-700 text-gray-400 hover:text-gray-200"
                title="Close"
              >
                <X size={14} />
              </button>
            </div>
          </div>
          <div className="w-full h-1 bg-gray-700 rounded-full overflow-hidden mt-1">
            <div
              className="h-full bg-blue-500 transition-all duration-300"
              style={{ width: `${scanProgress.progress}%` }}
            ></div>
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {scanProgress.message || "Processing..."}
          </div>
        </div>
      )}

      {/* PDF Upload UI */}
      {showPdfUpload && (
        <div
          className="mb-4 border border-gray-700 rounded-lg"
          ref={dropzoneRef}
        >
          <div className="flex justify-between items-center bg-gray-800 p-2 rounded-t-lg">
            <h3 className="text-sm font-medium text-gray-300">
              Upload PDF Documents
            </h3>
            <button
              onClick={() => !isUploading && setShowPdfUpload(false)}
              className={`p-1 rounded-md ${
                isUploading
                  ? "text-gray-500 cursor-not-allowed"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-700"
              }`}
              disabled={isUploading}
            >
              <X size={16} />
            </button>
          </div>
          <div className="p-2">
            <PdfUpload
              pdfs={pdfs}
              isDragActive={isDragActive}
              getRootProps={getRootProps}
              getInputProps={getInputProps}
              onRemovePdf={onRemovePdf}
              isUploading={isUploading}
              uploadProgress={uploadProgress}
              overallProgress={calculateOverallProgress()}
            />
          </div>
        </div>
      )}

      {/* Input Area */}
      <div className="flex flex-col bg-[#1A1A1A] rounded-lg p-3 border border-gray-700">
        <div className="flex items-start">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message... (Ctrl+Enter to send)"
            className="flex-1 bg-transparent border-none outline-none resize-none text-gray-200 placeholder-gray-500 min-h-[40px] max-h-[200px] py-2"
            style={{ overflowY: "auto" }}
          />

          {/* Action buttons container */}
          <div className="flex space-x-2">
            {/* Upload PDF button */}
            {!showPdfUpload && (
              <button
                onClick={() => setShowPdfUpload(true)}
                className="p-2 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded-md transition-colors"
                title="Upload PDF"
              >
                <Upload size={20} />
              </button>
            )}

            {/* Scan Upload button */}
            <button
              onClick={handleScanUpload}
              disabled={isScanningInProgress}
              className={`p-2 ${
                isScanningInProgress
                  ? "text-gray-500 cursor-not-allowed"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-700"
              } rounded-md transition-colors`}
              title="Upload Images/PDFs for OCR"
            >
              {isScanningInProgress ? (
                <div className="w-5 h-5 border-2 border-t-gray-400 border-gray-700 rounded-full animate-spin"></div>
              ) : (
                <Image size={20} />
              )}
            </button>

            {/* Send button */}
            <button
              onClick={() => sendMessage(message)}
              disabled={
                (!message.trim() && pdfs.length === 0) || isQueryInProgress
              }
              className={`p-2 ml-2 rounded-md transition-all ${
                (!message.trim() && pdfs.length === 0) || isQueryInProgress
                  ? "bg-blue-500/30 text-blue-300/50 cursor-not-allowed"
                  : "bg-blue-500 text-white hover:bg-blue-600"
              }`}
            >
              {isUploading || isQueryInProgress ? (
                <div className="w-5 h-5 border-2 border-t-blue-200 border-blue-500 rounded-full animate-spin"></div>
              ) : (
                <Send size={20} />
              )}
            </button>
          </div>
        </div>

        {/* Status bar */}
        <div className="flex justify-between text-xs text-gray-500 mt-1 px-2">
          <div className="flex space-x-2">
            {isSocketConnected ? (
              <span className="flex items-center">
                <span className="w-2 h-2 bg-green-500 rounded-full mr-1"></span>
                Connected
              </span>
            ) : (
              <span className="flex items-center">
                <span className="w-2 h-2 bg-red-500 rounded-full mr-1"></span>
                Disconnected
              </span>
            )}
            {isScanningInProgress && (
              <span className="flex items-center">
                <span className="w-2 h-2 bg-blue-500 rounded-full mr-1 animate-pulse"></span>
                Processing OCR
              </span>
            )}
          </div>
          <div>
            {message.length > 0 &&
              `${message.length} character${message.length !== 1 ? "s" : ""}`}
            {isUploading && (
              <span className="ml-2">
                Uploading: {calculateOverallProgress()}%
              </span>
            )}
            {pendingMessage && (
              <span className="ml-2 text-blue-400">Message pending...</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default InputForm;