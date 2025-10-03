import React, { useState, useEffect } from 'react';

// Import all your components
import AuthPage from './components/AuthPage';
import ChatSidebar from './components/ChatSidebar';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';
import Locator from './components/Locator';
import Appointments from './components/Appointments';
import './App.css';

// --- Chat users (could be fetched from backend later) ---
const chatUsers = [
  { name: 'Aarogya Saathi', avatar: '/bot-avatar.png', preview: 'AI assistant is online...', status: 'online' },
  { name: 'Dr. Sharma', avatar: '/doctor-avatar.png', preview: 'Your report looks good.', status: 'offline' },
  { name: 'Support Team', avatar: '/support-avatar.png', preview: 'Welcome! How can we help?', status: 'online' },
];

// Backend base URL (your ngrok URL)
const BACKEND_URL = 'https://1d897642e66b.ngrok-free.app';

// This function holds the bot's conversation logic. It now accepts the active chat name
const getBotResponse = (userInput, chatName = 'Aarogya Saathi') => {
  const text = (userInput || '').toLowerCase();

  // If the user is chatting with Support Team, return a support acknowledgement (simulated)
  if (chatName === 'Support Team') {
    return {
      text: "Support received your message. Our team will respond shortly.",
      options: []
    };
  }

  let response = {
    text: "Sorry, I didn't understand that. Please choose an option.",
    options: ["First-Aid (प्राथमिक उपचार)", "Schedule a Call"]
  };

  if (text.includes("first-aid")) {
    response = {
      text: "Aapko kis cheez ke liye first-aid chahiye?",
      options: ["Chot Lagnā (Cut/Wound)", "Bukhar (Fever)"]
    };
  } else if (text.includes("chot") || text.includes("wound")) {
    response = {
      text: "Agar khoon beh raha hai toh yeh steps follow karein:\n1. Ghaav ko saaf paani se dhoyein.",
      options: ["Schedule a Call"]
    };
  } else if (text.includes("schedule a call")) {
    response = {
      text: "This feature will be available in the Scheduler tab soon.",
      options: ["First-Aid (प्राथमिक उपचार)"]
    };
  }
  return response;
};


function App() {
  const [user, setUser] = useState(null);
  // messagesByChat stores arrays of messages keyed by chat name
  const [messagesByChat, setMessagesByChat] = useState({});
  const [isTyping, setIsTyping] = useState(false);
  const [activeChat, setActiveChat] = useState(chatUsers[0].name);
  const [viewMode, setViewMode] = useState('chat'); // 'chat' or 'locator'
  const [selectedHospital, setSelectedHospital] = useState(null);

  // This function is called by AuthPage on successful login
  const handleLoginSuccess = (uid) => {
    setUser(uid);
    localStorage.setItem('user_uid', uid);
  };

  // Explicit logout action clears stored uid and returns to AuthPage
  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem('user_uid');
    setMessagesByChat({});
    setActiveChat(chatUsers[0].name);
    setViewMode('chat');
  };

  // Save current chat to backend
  const handleSaveChat = async () => {
    try {
      const uid = localStorage.getItem('user_uid');
      const msgs = messagesByChat[activeChat] || [];
      const res = await fetch(`${BACKEND_URL}/save_chat`, { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ uid, chatName: activeChat, messages: msgs }) });
      if (res.ok) alert('Chat saved to your records.');
      else { const d = await res.json(); alert(d.message || 'Save failed'); }
    } catch (e) { console.error(e); alert('Failed to save chat'); }
  };

  // Initialize a chat's messages if not present
  const ensureChatInitialized = (chatName) => {
    setMessagesByChat(prev => {
      if (prev[chatName]) return prev;
      const initial = chatName === 'Aarogya Saathi'
        ? [{ id: Date.now(), text: "Namaste! Main Aarogya Saathi hoon. Main aapki kya sahayata kar sakta hoon?", sender: 'bot', options: ["First-Aid (प्राथमिक उपचार)", "Schedule a Call"] }]
        : [{ id: Date.now(), text: `This is your chat with ${chatName}. How can we help?`, sender: 'bot', options: [] }];
      return { ...prev, [chatName]: initial };
    });
  };

  // When user selects a chat from the sidebar
  const handleChatSelect = (chatName) => {
    setActiveChat(chatName);
    ensureChatInitialized(chatName);
  };

  // This function handles all chat messages and stores them per chat
  const handleUserInput = (text) => {
    if (!text || !text.trim()) return;
    const newUserMessage = { id: Date.now(), text, sender: 'user', read: false };

    setMessagesByChat(prev => {
      const chatMsgs = prev[activeChat] || [];
      return { ...prev, [activeChat]: [...chatMsgs, newUserMessage] };
    });

    setIsTyping(true);
    // If active chat is Support Team, call backend endpoint, otherwise local bot simulation
    if (activeChat === 'Support Team') {
      // POST message to backend support endpoint
      (async () => {
        try {
          const res = await fetch(`${BACKEND_URL}/support/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid: user, message: text })
          });

          if (!res.ok) throw new Error(`Server returned ${res.status}`);

          const data = await res.json();
          // backend may return { reply } or { replies: [] }
          const replies = data.replies || (data.reply ? [data.reply] : []);

          if (replies.length === 0) {
            // fallback message
            replies.push('Support received your message. Our team will respond shortly.');
          }

          // append replies
          setMessagesByChat(prev => {
            const chatMsgs = prev[activeChat] || [];
            const botMessages = replies.map(r => ({ id: Date.now() + Math.random(), text: r, sender: 'bot', options: [] }));
            return { ...prev, [activeChat]: [...chatMsgs, ...botMessages] };
          });
        } catch (err) {
          // show error message in chat
          setMessagesByChat(prev => {
            const chatMsgs = prev[activeChat] || [];
            return { ...prev, [activeChat]: [...chatMsgs, { id: Date.now() + 1, text: 'Failed to send to support. Please try again later.', sender: 'bot', options: [] }] };
          });
        } finally {
          setIsTyping(false);
          setTimeout(() => {
            setMessagesByChat(prev => {
              const chatMsgs = (prev[activeChat] || []).map(msg => 
                msg.id === newUserMessage.id ? { ...msg, read: true } : msg
              );
              return { ...prev, [activeChat]: chatMsgs };
            });
          }, 500);
        }
      })();
    } else {
      // local bot simulation for other chats
      setTimeout(() => {
        const botData = getBotResponse(text, activeChat);
        const botMessage = { id: Date.now() + 1, text: botData.text, sender: 'bot', options: botData.options };

        setMessagesByChat(prev => {
          const chatMsgs = prev[activeChat] || [];
          return { ...prev, [activeChat]: [...chatMsgs, botMessage] };
        });

        setIsTyping(false);

        setTimeout(() => {
          setMessagesByChat(prev => {
            const chatMsgs = (prev[activeChat] || []).map(msg => 
              msg.id === newUserMessage.id ? { ...msg, read: true } : msg
            );
            return { ...prev, [activeChat]: chatMsgs };
          });
        }, 500);
      }, 800);
    }
  };

  // This checks if a user was already logged in
  // NOTE: don't auto-login from localStorage on app load. We want the user
  // to explicitly log in first. If you prefer automatic sign-in, re-enable
  // reading the saved uid here.

  // When user logs in, initialize the active chat messages
  useEffect(() => {
    if (user) {
      ensureChatInitialized(activeChat);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // If no user is logged in, show the AuthPage
  if (!user) {
    return <AuthPage onLoginSuccess={handleLoginSuccess} />;
  }

  // If a user IS logged in, show the desktop layout
  return (
    <div className="desktop-container">
      <ChatSidebar users={chatUsers} activeChat={activeChat} onChatSelect={handleChatSelect} />
      <div className="chat-container">
        <div className="chat-header">
          <img src={chatUsers.find(u => u.name === activeChat)?.avatar || '/bot-avatar.png'} alt="Avatar" className="avatar" />
          <div className="header-info">
            <h3>{activeChat}</h3>
            <p>{isTyping ? 'typing...' : (chatUsers.find(u => u.name === activeChat)?.status || 'online')}</p>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
            <button onClick={() => setViewMode('appointments')} style={{ padding: '6px 10px' }}>Appointments</button>
            <button onClick={() => setViewMode('chat')} style={{ padding: '6px 10px' }}>Chat</button>
            <button onClick={() => setViewMode('locator')} style={{ padding: '6px 10px' }}>Locator</button>
            <button onClick={handleSaveChat} style={{ padding: '6px 10px' }}>Save chat</button>
            <button onClick={handleLogout} style={{ padding: '6px 10px', background:'#fff', border:'1px solid #ddd' }}>Logout</button>
          </div>
        </div>
        {viewMode === 'chat' ? (
          <>
            <ChatWindow messages={messagesByChat[activeChat] || []} isTyping={isTyping} onOptionClick={handleUserInput} />
            <MessageInput onSendMessage={handleUserInput} />
          </>
        ) : viewMode === 'locator' ? (
          <Locator onSelectHospital={(h) => { setSelectedHospital(h); setViewMode('appointments'); }} />
        ) : viewMode === 'appointments' ? (
          <Appointments selectedHospital={selectedHospital} />
        ) : null}
      </div>
    </div>
  );
}

export default App;

