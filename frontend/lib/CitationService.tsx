/* lib/CitationService.ts */

export interface CitationTextResponse {
    text: string;
    source: string;
    page?: number;
    error?: string;
  }
  
  export class CitationService {
    private apiUrl: string;
    
    constructor(baseUrl: string = 'http://localhost:5001') {
      this.apiUrl = baseUrl;
    }
    
    /**
     * Get the text content for a specific citation
     */
    async getCitationText(
      source: string, 
      conversationId?: string
    ): Promise<CitationTextResponse> {
      try {
        const response = await fetch(`${this.apiUrl}/api/citation-text`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            source,
            conversationId
          })
        });
        
        if (!response.ok) {
          throw new Error(`Failed to fetch citation text: ${response.statusText}`);
        }
        
        return await response.json();
      } catch (error) {
        console.error('Error fetching citation text:', error);
        return {
          text: 'Error loading citation text',
          source,
          error: error instanceof Error ? error.message : 'Unknown error'
        };
      }
    }
    
    /**
     * Get the PDF URL for a specific filename with conversation context
     */
    getPdfUrl(filename: string, conversationId?: string): string {
      // Build the URL to fetch the PDF
      const url = `${this.apiUrl}/api/pdf/${filename}`;
      if (conversationId) {
        return `${url}?conversation_id=${conversationId}`;
      }
      return url;
    }
    
    /**
     * Parse a citation source string into filename and page number
     */
    parseCitationSource(source: string): { filename: string; page?: number } {
      // Regular expression to match "filename.pdf (page X)" format
      const match = source.match(/(.+?)(?: \(page (\d+)\))?$/);
      
      if (match) {
        return {
          filename: match[1],
          page: match[2] ? parseInt(match[2], 10) : undefined
        };
      }
      
      return { filename: source };
    }
  }
  
  // Export a singleton instance
  export const citationService = new CitationService();