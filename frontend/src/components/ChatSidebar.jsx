import React from 'react';
import './ChatSidebar.css';

// This component is now data-driven and interactive
function ChatSidebar({ users, activeChat, onChatSelect }) {
  return (
    <aside className="sidebar-container">
      <div className="sidebar-header">
        <img
          src="/profile-pic.png"
          alt="User"
          className="sidebar-profile-pic"
          onError={(e) => { e.target.onerror = null; e.target.src = '/logo192.png'; }}
        />
        <input type="text" placeholder="Search or start new chat" className="search-bar" />
      </div>

      <div className="chat-list">
        {/* Maps over the users array to create the list dynamically */}
        {users.map(user => (
          <div 
            key={user.name}
            className={`chat-list-item ${activeChat === user.name ? 'active' : ''}`}
            onClick={() => onChatSelect(user.name)}
          >
            <img src={user.avatar} alt={user.name} className="chat-avatar" />
            <div className="chat-info">
              <h4 className="chat-name">{user.name}</h4>
              <p className="chat-preview">{user.preview}</p>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

export default ChatSidebar;

