import React, { useState, useEffect, useRef } from 'react';
import ChatMessage from '../components/ChatMessage';
import TypingIndicator from '../components/TypingIndicator';

const API_BASE = '/api';

function App() {
  const [sessionKey, setSessionKey] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState(null);
  
  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  // Start session on mount
  useEffect(() => {
    const startSession = async () => {
      try {
        const response = await fetch(`${API_BASE}/chat/sessions/`, {
          method: 'POST',
        });
        if (!response.ok) throw new Error('Failed to start session');
        
        const data = await response.json();
        setSessionKey(data.session_key);
        
        // Initial greeting
        setMessages([
          { role: 'assistant', content: 'Hello! I am your AI scheduling assistant. How can I help you today?' }
        ]);
      } catch (err) {
        console.error(err);
        setError('Could not connect to the server. Is Django running?');
      }
    };

    startSession();
  }, []);

  const handleSend = async (textOverride) => {
    const userMessage = (typeof textOverride === 'string' ? textOverride : inputValue).trim();
    if (!userMessage || !sessionKey || isTyping) return;

    if (typeof textOverride !== 'string') {
      setInputValue('');
    }
    setError(null);
    
    // Add user message to UI
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsTyping(true);

    try {
      const response = await fetch(`${API_BASE}/chat/message/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_key: sessionKey,
          message: userMessage,
        }),
      });

      if (!response.ok) throw new Error('Failed to get response');

      const data = await response.json();
      
      setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
    } catch (err) {
      console.error(err);
      setError('An error occurred while sending the message.');
      // Remove the typing indicator if error
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleSend();
    }
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        <div className="chat-header-avatar">
          <img src="https://ui-avatars.com/api/?name=AI&background=ffffff&color=0066FF" alt="Bot Avatar" />
          <div className="status-dot"></div>
        </div>
        <div className="chat-header-info">
          <h1>Scheduling Bot</h1>
          <p>Typically replies instantly</p>
        </div>
      </div>
      
      <div className="messages-area">
        {messages.map((msg, idx) => (
          <ChatMessage 
            key={idx} 
            role={msg.role} 
            content={msg.content} 
            onOptionClick={handleSend}
          />
        ))}
        {isTyping && <TypingIndicator />}
        {error && (
          <div className="message-wrapper assistant">
            <div className="message-bubble" style={{ color: '#ff6b6b' }}>
              {error}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <input 
          type="text" 
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask for an appointment..."
          disabled={!sessionKey || isTyping}
        />
        <button 
          className="send-btn"
          onClick={handleSend}
          disabled={!inputValue.trim() || !sessionKey || isTyping}
          aria-label="Send message"
        >
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </div>
    </div>
  );
}

export default App;
