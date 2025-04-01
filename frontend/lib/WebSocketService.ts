import { io, Socket } from 'socket.io-client';

interface UploadStatus {
  id: string;
  fileId: string;
  fileName: string;
  progress: number;
  status: 'uploading' | 'completed' | 'error';
  error?: string;
  message?: string;
}

interface QueryResult {
  queryId: string;
  status: 'processing' | 'completed' | 'error';
  answer?: string;
  sources?: string[];
  has_context?: boolean;
  error?: string;
}

export class WebSocketService {
  private socket: Socket | null = null;
  private listeners: { [event: string]: ((data: any) => void)[] } = {};
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectInterval = 2000; // 2 seconds
  private isConnecting = false;
  private isReconnecting = false;

  constructor(private url: string = 'http://localhost:5001') {
    this.connect();
  }

  private connect() {
    if (this.isConnecting || this.socket?.connected) {
      console.log('Already connected or connecting, skipping connection attempt');
      return;
    }

    this.isConnecting = true;
    console.log('Connecting to WebSocket server at:', this.url);
    
    try {
      // Disconnect existing socket if any
      if (this.socket) {
        this.socket.disconnect();
        this.socket = null;
      }
      
      this.socket = io(this.url, {
        transports: ['websocket'],
        reconnection: true,
        reconnectionAttempts: this.maxReconnectAttempts,
        reconnectionDelay: this.reconnectInterval,
        timeout: 20000,
        // Disable automatic reconnection to handle it manually
        autoConnect: true,
        forceNew: true
      });

      this.socket.on('connect', () => {
        console.log('WebSocket connected');
        this.isConnecting = false;
        this.isReconnecting = false;
        this.reconnectAttempts = 0;
        this.emit('connected', { status: 'connected' });
      });

      this.socket.on('disconnect', (reason) => {
        console.log('WebSocket disconnected:', reason);
        this.isConnecting = false;
        this.emit('disconnected', { status: 'disconnected', reason });
        
        // Don't attempt to reconnect if this was an explicit disconnect
        if (reason === 'io client disconnect' || reason === 'io server disconnect') {
          console.log('Explicit disconnect, not attempting to reconnect');
          return;
        }
        
        // Avoid multiple reconnection attempts running simultaneously
        if (!this.isReconnecting) {
          this.isReconnecting = true;
          console.log('Will attempt to reconnect...');
          setTimeout(() => {
            this.isReconnecting = false;
            this.connect();
          }, this.reconnectInterval);
        }
      });

      this.socket.on('connect_error', (error) => {
        // console.error('Connection error:', error);
        this.isConnecting = false;
        this.reconnectAttempts++;
        
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
          console.error('Max reconnect attempts reached');
          this.emit('error', { error: 'Failed to connect to server' });
        } else if (!this.isReconnecting) {
          this.isReconnecting = true;
          console.log(`Connection error, will retry in ${this.reconnectInterval}ms`);
          setTimeout(() => {
            this.isReconnecting = false;
            this.connect();
          }, this.reconnectInterval);
        }
      });

      // Forward all server events to our listeners
      this.socket.onAny((eventName, ...args) => {
        if (this.listeners[eventName]) {
          this.listeners[eventName].forEach(callback => callback(args[0]));
        }
      });

      // Set up specific listeners to handle upload events
      this.socket.on('upload_progress', (data) => {
        console.log('Upload progress received:', data);
        this.emit('upload_progress', data);
      });

      this.socket.on('upload_started', (data) => {
        console.log('Upload started:', data);
        this.emit('upload_started', data);
      });

      // Set up listeners for query events
      this.socket.on('query_processing', (data) => {
        console.log('Query processing:', data);
        this.emit('query_processing', data);
      });

      this.socket.on('query_result', (data) => {
        console.log('Query result received:', data);
        this.emit('query_result', data);
      });

      this.socket.on('query_error', (data) => {
        console.error('Query error:', data);
        this.emit('query_error', data);
      });

      this.socket.on('error', (data) => {
        console.error('Server error:', data);
        this.emit('error', data);
      });
    } catch (error) {
      console.error('Error initializing socket:', error);
      this.isConnecting = false;
    }
  }

  public on(event: string, callback: (data: any) => void) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
    return () => {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    };
  }

  public emit(event: string, data: any) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => callback(data));
    }
  }

  public send(event: string, data: any) {
    if (!this.socket) {
      console.error('Socket not initialized');
      this.connect();
      return false;
    }
    
    if (!this.socket.connected) {
      console.warn('Socket not connected, attempting reconnection');
      this.connect();
      return false;
    }
    
    console.log(`Sending ${event} event:`, data.fileName || data);
    this.socket.emit(event, data);
    return true;
  }

  public uploadPdf(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      if (!this.socket) {
        reject(new Error('Socket not initialized'));
        this.connect();
        return;
      }
      
      if (!this.socket.connected) {
        reject(new Error('Socket not connected'));
        this.connect();
        return;
      }

      const uploadId = `upload-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      
      // Set up listener for this upload
      const unsubscribe = this.on('upload_progress', (data: UploadStatus) => {
        if (data.id === uploadId) {
          if (data.status === 'completed' && data.fileId) {
            unsubscribe();
            resolve(data.fileId);
          } else if (data.status === 'error') {
            unsubscribe();
            reject(new Error(data.error || 'Upload failed'));
          }
        }
      });

      // Read file as base64
      const reader = new FileReader();
      reader.onloadend = () => {
        // Send to server - the entire file at once for simplicity
        this.send('upload_pdf', {
          uploadId,
          fileName: file.name,
          fileData: reader.result
        });
      };
      reader.onerror = () => {
        unsubscribe();
        reject(new Error('Failed to read file'));
      };
      reader.readAsDataURL(file);
    });
  }

  public searchPdfContent(query: string): Promise<any> {
    return fetch(`${this.url}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query }),
    }).then(response => response.json());
  }

  public queryPdfContent(query: string, model: string = 'gpt-4o-mini'): Promise<any> {
    return fetch(`${this.url}/api/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query, model }),
    }).then(response => response.json());
  }

  public queryPdfContentRealtime(query: string, model: string = 'gpt-4o-mini'): Promise<QueryResult> {
    return new Promise((resolve, reject) => {
      if (!this.socket) {
        reject(new Error('Socket not initialized'));
        this.connect();
        return;
      }
      
      if (!this.socket.connected) {
        reject(new Error('Socket not connected'));
        this.connect();
        return;
      }

      const queryId = `query-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      
      // Set up listeners for the query
      const unsubscribeResult = this.on('query_result', (data: QueryResult) => {
        if (data.queryId === queryId) {
          unsubscribeResult();
          unsubscribeError();
          resolve(data);
        }
      });
      
      const unsubscribeError = this.on('query_error', (data: QueryResult) => {
        if (data.queryId === queryId) {
          unsubscribeResult();
          unsubscribeError();
          reject(new Error(data.error || 'Query failed'));
        }
      });

      // Send query through WebSocket
      this.send('query', {
        queryId,
        query,
        model
      });
    });
  }

  public disconnect() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
      this.isConnecting = false;
      this.isReconnecting = false;
    }
  }

  public isConnected(): boolean {
    return !!this.socket?.connected;
  }
}

// Export singleton instance
export const socketService = new WebSocketService();