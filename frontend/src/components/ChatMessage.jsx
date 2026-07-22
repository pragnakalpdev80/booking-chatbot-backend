import React from 'react';

const ChatMessage = ({ role, content, onOptionClick }) => {
  // Simple markdown-like link parsing
  const renderContent = (text) => {
    if (!text) return null;
    
    // Split by newlines
    const paragraphs = text.split('\n').filter(p => p.trim() !== '');
    
    return paragraphs.map((paragraph, i) => {
      // Parse URLs and **bold** text
      const renderFormattedText = (text) => {
        // split by URLs first
        const parts = text.split(/(https?:\/\/[^\s<]+)/g);
        
        return parts.map((part, j) => {
          if (part.match(/^https?:\/\//)) {
            // Strip trailing > if it was wrapped in < >
            const url = part.endsWith('>') ? part.slice(0, -1) : part;
            return (
              <a key={j} href={url} target="_blank" rel="noopener noreferrer">
                {url}
              </a>
            );
          }
          
          // non-url text: parse **bold**
          const boldParts = part.split(/\*\*(.*?)\*\*/g);
          return boldParts.map((bp, k) => {
            if (k % 2 === 1) return <strong key={`${j}-${k}`}>{bp}</strong>;
            return bp;
          });
        });
      };

      // If it's an assistant message and starts with a dash or asterisk, render as a clickable option button
      // Restrictions: don't make it a button if it contains ** (structured field), is a link, or is too long.
      const isBullet = paragraph.trim().startsWith('- ') || paragraph.trim().startsWith('* ');
      if (role === 'assistant' && isBullet) {
        let optionText = paragraph.trim().substring(2).trim();
        // Remove brackets if the AI still hallucinates them from previous memory
        optionText = optionText.replace(/^\[(.*)\]$/, '$1').trim();
        
        if (!optionText.includes('**') && !optionText.includes('http') && optionText.length < 60) {
          return (
            <button 
              key={i} 
              className="chat-option-btn"
              onClick={() => onOptionClick && onOptionClick(optionText)}
            >
              {optionText}
            </button>
          );
        }
      }

      // Render as regular text if it's not a button
      let pText = paragraph;
      if (isBullet) pText = pText.substring(2);

      return (
        <p key={i} style={{ marginBottom: i < paragraphs.length - 1 ? '0.5rem' : 0 }}>
          {renderFormattedText(pText)}
        </p>
      );
    });
  };

  return (
    <div className={`message-wrapper ${role}`}>
      <div className="message-bubble">
        {renderContent(content)}
      </div>
    </div>
  );
};

export default ChatMessage;
