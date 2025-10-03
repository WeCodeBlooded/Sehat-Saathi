import React, { useEffect, useRef } from 'react';
import InlineScheduler from './InlineScheduler';
import './ChatWindow.css';
import './InlineScheduler.css';

const OptionButton = ({ text, onClick }) => (
  <button className="option-button" onClick={() => onClick(text)}>
    {text}
  </button>
);

function ChatWindow({ messages, isTyping, onOptionClick }) {
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);
  
  const lastMessage = messages[messages.length - 1];
  
  return (
    <div className="chat-messages">
      {messages.map((msg) => (
        <div key={msg.id} className={`message ${msg.sender === 'bot' ? 'bot-message' : 'user-message'}`}>
          <div className="message-text">{msg.text}</div>
          {/* attachments */}
          {msg.files && msg.files.length > 0 && (
            <div style={{ marginTop:8, display:'flex', gap:8 }}>
              {msg.files.map((f, i) => (
                <div key={i} style={{ width:140, height:90, overflow:'hidden', borderRadius:6, background:'#fafafa' }}>
                  {f.url && f.type && f.type.startsWith('image') ? (
                    <img src={f.url} alt={f.name} style={{ width:'100%', height:'100%', objectFit:'cover' }} />
                  ) : f.url && f.type && f.type.startsWith('video') ? (
                    <video src={f.url} controls style={{ width:'100%', height:'100%', objectFit:'cover' }} />
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {/* reactions */}
          <div style={{ marginTop:6 }}>
            <button className="option-button" onClick={() => { /* placeholder: add reaction */ }}>👍</button>
            <button className="option-button" onClick={() => { /* placeholder: add reaction */ }}>❤️</button>
            <button className="option-button" onClick={() => { /* placeholder: add reaction */ }}>😮</button>
          </div>
          <div className="message-meta">
            <span>{new Date(msg.id).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            {msg.sender === 'user' && (
              <i className={`fa-solid fa-check-double ${msg.read ? 'read-tick' : 'sent-tick'}`}></i>
            )}
          </div>
        </div>
      ))}

      {isTyping && (
        <div className="message bot-message typing-indicator">
          <span></span><span></span><span></span>
        </div>
      )}
      
      {lastMessage?.sender === 'bot' && !isTyping && (
        lastMessage.component === 'inline_scheduler' ? (
          <InlineScheduler onSchedule={onOptionClick} onCancel={onOptionClick} />
        ) : lastMessage.options && lastMessage.options.length > 0 ? (
          <div className="options-container">
            {lastMessage.options.map(optionText => (
              <OptionButton key={optionText} text={optionText} onClick={onOptionClick} />
            ))}
          </div>
        ) : null
      )}

      <div ref={chatEndRef} />
    </div>
  );
}

export default ChatWindow;

