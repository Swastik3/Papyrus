/* components/Sidebar.tsx*/

import React, { useState, useEffect, useRef } from 'react';
import { Message } from '../app/page';

interface SidebarProps {
  messages: Message[];
  onExpandChange: (expanded: boolean) => void;
}

const Sidebar: React.FC<SidebarProps> = ({ messages, onExpandChange }) => {
  const [isHovered, setIsHovered] = useState(false);
  const sidebarRef = useRef<HTMLDivElement>(null);

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
          <h2 className="text-xl font-bold mb-4 text-white">Conversation History</h2>
          <div className="space-y-4">
            {messages.map((msg, i) => (
              <div key={i} className={`p-2 rounded ${msg.role === 'user' ? 'bg-[#2A2A2A]' : 'bg-[#1A1A1A]'}`}>
                <p className="text-sm text-gray-200">{msg.content}</p>
              </div>
            ))}
            {messages.length === 0 && (
              <p className="text-gray-500 text-sm">No conversations yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Sidebar;