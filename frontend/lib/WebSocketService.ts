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

export class WebSocketService {
  private socket: Socket | null = null;
  private listeners: { [event: string]: ((data: any) => void)[] } = {};
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectInterval = 2000; // 2 seconds
  private isConnecting = false;
  private isReconnecting = false;
  private tokenBuffer: string[] = []; // Buffer for token batching
  private tokenTimerId: NodeJS.Timeout | null = null;

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
        autoConnect: true,
        forceNew: true
      });

      this.socket.on('connect', () => {
        console.log('WebSocket connected with ID:', this.socket?.id);
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
        console.error('Connection error:', error);
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

      // Set up specific listeners for progress updates
      this.socket.on('upload_progress', (data) => {
        console.log('Upload progress received:', data);
        this.emit('upload_progress', data);
      });

      // Add listeners for streaming tokens with batching for smoother animation
      this.socket.on('token', (data) => {
        if (data && data.token) {
          // Add token to buffer
          this.tokenBuffer.push(data.token);
          
          // If timer is not running, start it
          if (!this.tokenTimerId) {
            this.tokenTimerId = setTimeout(() => {
              this.flushTokenBuffer();
            }, 16); // ~60fps refresh rate (16ms)
          }
        }
      });

      // Add listeners for query processing status
      this.socket.on('query_processing', (data) => {
        console.log('Query processing:', data);
        this.emit('query_processing', data);
      });

      // Add listeners for query results
      this.socket.on('query_result', (data) => {
        console.log('Query result:', data);
        // Flush any remaining tokens
        this.flushTokenBuffer();
        this.emit('query_result', data);
      });

      // Add listeners for query errors
      this.socket.on('query_error', (data) => {
        console.error('Query error:', data);
        // Flush any remaining tokens
        this.flushTokenBuffer();
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

  // Flush token buffer to emit tokens with better performance
  private flushTokenBuffer() {
    if (this.tokenBuffer.length > 0) {
      const combinedToken = this.tokenBuffer.join('');
      console.log(`Flushing ${this.tokenBuffer.length} tokens: "${combinedToken.substring(0, 20)}${combinedToken.length > 20 ? '...' : ''}"`);
      this.emit('token', { token: combinedToken });
      this.tokenBuffer = [];
    }
    
    // Clear the timer
    if (this.tokenTimerId) {
      clearTimeout(this.tokenTimerId);
      this.tokenTimerId = null;
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
    
    console.log(`Sending ${event} event:`, data.query ? `query: ${data.query.substring(0, 30)}...` : data);
    this.socket.emit(event, data);
    return true;
  }

  public getSocketId(): string | null {
    return this.socket?.id || null;
  }

  public isConnected(): boolean {
    return !!this.socket?.connected;
  }

  public disconnect() {
    // Clear any pending token flush
    if (this.tokenTimerId) {
      clearTimeout(this.tokenTimerId);
      this.tokenTimerId = null;
    }
    
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
      this.isConnecting = false;
      this.isReconnecting = false;
    }
  }
}

// Export singleton instance
export const socketService = new WebSocketService();